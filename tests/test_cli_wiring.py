"""The group callback that builds a real client.

Every other CLI test injects a prepared client via `obj`, so this seam was
never executed. That is where the `--raw-dir` collision bug lived: the archive
is only ever configured here.
"""

import json
import subprocess

import pytest
from click.testing import CliRunner

from trends_research_cli.api.client import Response
from trends_research_cli.cli import main
from trends_research_cli.credentials import CredentialsError, resolve_credential

RUNNER = CliRunner()

SERIES = [
    "series",
    "/m/0cycc",
    "--geo",
    "US",
    "--from",
    "2025-07-01",
    "--to",
    "2025-07-02",
]


@pytest.fixture
def offline(monkeypatch):
    """Let the real client be built, but answer without a network."""
    calls: list[tuple[str, list]] = []

    class Transport:
        def __init__(self, api_key, **_kwargs):
            self.api_key = api_key

        def get(self, url, params):
            calls.append((url, list(params)))
            return Response(
                200,
                {
                    "lines": [
                        {
                            "term": "flu",
                            "points": [{"date": "Jul 01 2025", "value": 1.0}],
                        }
                    ]
                },
            )

    monkeypatch.setattr("trends_research_cli.cli.Urllib3Transport", Transport)
    monkeypatch.setenv("TRENDS_API_KEY", "AIzaSyFAKE")
    return calls


def test_a_real_client_is_built_from_the_environment(offline):
    result = RUNNER.invoke(main, SERIES)

    assert result.exit_code == 0
    assert offline, "the constructed client actually issued the request"


def test_the_raw_archive_is_written_through_the_real_wiring(offline, tmp_path):
    """`--raw-dir` is only ever configured in the group callback."""
    result = RUNNER.invoke(main, ["--raw-dir", str(tmp_path), *SERIES])

    assert result.exit_code == 0
    archived = list(tmp_path.glob("*.json"))
    assert len(archived) == 1
    assert (
        json.loads(archived[0].read_text())["endpoint"] == "timelinesForHealth"
    )


def test_a_second_run_does_not_overwrite_the_first_archive(offline, tmp_path):
    for _ in range(2):
        RUNNER.invoke(main, ["--raw-dir", str(tmp_path), *SERIES])

    assert len(list(tmp_path.glob("*.json"))) == 2


def test_an_unwritable_raw_dir_is_reported_not_raised(offline, tmp_path):
    blocked = tmp_path / "afile"
    blocked.write_text("not a directory")

    result = RUNNER.invoke(main, ["--raw-dir", str(blocked / "under"), *SERIES])

    assert result.exit_code == 1, "a setup problem, not an API failure to retry"
    assert "filesystem error" in result.output
    assert "Traceback" not in result.output


def test_an_explicit_api_key_beats_the_environment(offline, monkeypatch):
    """Verified through the real construction path, not the resolver alone."""
    seen = {}

    class Recording:
        def __init__(self, api_key, **_kwargs):
            seen["key"] = api_key

        def get(self, url, params):
            return Response(200, {"lines": []})

    monkeypatch.setattr("trends_research_cli.cli.Urllib3Transport", Recording)
    monkeypatch.setenv("TRENDS_API_KEY", "from-env")

    RUNNER.invoke(main, ["--api-key", "from-flag", *SERIES])

    assert seen["key"] == "from-flag"


def test_a_missing_credential_is_carried_so_doctor_can_explain_it(monkeypatch):
    monkeypatch.delenv("TRENDS_API_KEY", raising=False)
    monkeypatch.setattr(
        "trends_research_cli.cli.resolve_credential", _no_credential
    )

    doctor = RUNNER.invoke(main, ["doctor"])
    series = RUNNER.invoke(main, SERIES)

    assert doctor.exit_code == 1 and "no key here" in doctor.output
    assert series.exit_code == 1 and "no key here" in series.output


def _no_credential(*_args, **_kwargs):
    raise CredentialsError("no key here")


# --- the gcloud fallback, which shells out ----------------------------------


def test_gcloud_supplies_a_key_when_nothing_else_does(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            [], 0, stdout="AIzaFromGcloud\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    credential = resolve_credential(None, env={})

    assert credential.key == "AIzaFromGcloud"
    assert credential.source == "gcloud"


def test_an_unauthenticated_gcloud_is_not_fatal_it_just_has_no_key(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            [], 1, stdout="", stderr="not logged in"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(CredentialsError):
        resolve_credential(None, env={})


def test_a_missing_gcloud_binary_is_not_fatal_either(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError("gcloud")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(CredentialsError, match="TRENDS_API_KEY"):
        resolve_credential(None, env={})


def test_a_hanging_gcloud_does_not_hang_the_tool(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="gcloud", timeout=30)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(CredentialsError):
        resolve_credential(None, env={})
