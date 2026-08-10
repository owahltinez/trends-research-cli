"""Resolving the API key.

Order: ``--api-key``, ``$TRENDS_API_KEY``, ``.env``, then ``gcloud``. The
environment comes first deliberately — a `gcloud` token lapsing part-way
through a long collection has killed a run before.

The key is never logged, echoed, or included in an error message.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

ENV_VAR = "TRENDS_API_KEY"

_GUIDANCE = (
    f"no API key found. Set ${ENV_VAR}, put it in .env, pass --api-key, or "
    "authenticate with `gcloud auth login`. Run `gtrends doctor` to check "
    "whether the key you have is allow-listed for this API."
)


class CredentialsError(RuntimeError):
    """No usable API key could be found."""


def _from_gcloud() -> str | None:
    """Ask `gcloud` for a key string, or give up quietly."""
    result = subprocess.run(
        ["gcloud", "services", "api-keys", "get-key-string"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.stdout.strip() or None


@dataclass(frozen=True)
class Credential:
    """A key and where it came from. The source prints; the key never does."""

    key: str
    source: str


def resolve_credential(
    explicit: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    gcloud: Callable[[], str | None] = _from_gcloud,
) -> Credential:
    """Return the first key found, in documented precedence order."""
    if explicit:
        return Credential(explicit, "--api-key")

    # `.env` only fills gaps in the real environment, so an exported variable
    # always wins over a stale file.
    if env is None:
        load_dotenv()
        env = os.environ

    if key := env.get(ENV_VAR):
        return Credential(key, f"${ENV_VAR} or .env")

    # `gcloud` may be absent, unauthenticated or slow; none of that is fatal
    # here, it just means there is no key.
    try:
        if key := gcloud():
            return Credential(key, "gcloud")
    except (OSError, subprocess.SubprocessError):
        pass

    raise CredentialsError(_GUIDANCE)


def resolve_key(
    explicit: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    gcloud: Callable[[], str | None] = _from_gcloud,
) -> str:
    """Return just the key, for callers that do not care where it came from."""
    return resolve_credential(explicit, env=env, gcloud=gcloud).key
