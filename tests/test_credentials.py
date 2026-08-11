"""Credential resolution order.

A `gcloud` token lapsing mid-collection killed a long run once, which is why
the environment is consulted before `gcloud`, not after.
"""

import pytest

from trends_research_cli.credentials import (
    CredentialsError,
    resolve_credential,
    resolve_key,
)


def test_an_explicit_key_wins_over_everything():
    key = resolve_key(
        "explicit", env={"TRENDS_API_KEY": "env"}, gcloud=lambda: "g"
    )

    assert key == "explicit"


def test_the_environment_is_preferred_over_gcloud():
    key = resolve_key(
        None, env={"TRENDS_API_KEY": "env"}, gcloud=lambda: "gcloud"
    )

    assert key == "env"


def test_gcloud_is_the_last_resort():
    assert resolve_key(None, env={}, gcloud=lambda: "gcloud") == "gcloud"


def test_a_failing_gcloud_is_reported_as_no_credentials():
    def boom():
        raise OSError("gcloud not on PATH")

    with pytest.raises(CredentialsError, match="TRENDS_API_KEY"):
        resolve_key(None, env={}, gcloud=boom)


def test_the_guidance_says_how_to_obtain_a_key_not_just_supply_one():
    """The commonest first-run failure, and the one place a stranger looks.

    Listing four ways to supply a key is useless for an allow-listed API that
    will not issue one without an application, so the request URL is the part
    that has to be here. It must not say "run `gtrends doctor`" either, since
    `doctor` is usually what printed it.
    """
    with pytest.raises(CredentialsError) as caught:
        resolve_key(None, env={}, gcloud=lambda: None)

    message = str(caught.value)
    assert "TRENDS_API_KEY" in message
    assert "support.google.com/trends/contact/trends_api" in message
    assert "allow-listed" in message
    assert "gtrends doctor" not in message


def test_a_resolved_key_is_never_put_in_the_source_label():
    """`doctor` prints the source; printing the key with it would be a leak."""
    credential = resolve_credential(
        None, env={"TRENDS_API_KEY": "AIzaSySECRET"}, gcloud=lambda: None
    )

    assert credential.key == "AIzaSySECRET"
    assert "AIzaSySECRET" not in credential.source
