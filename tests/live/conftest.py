"""Fixtures for the live suite.

Skipped unless a key is present. Run with ``uv run pytest -m live``.

The fetch helper deliberately uses stdlib rather than the tool's own transport:
these tests exist to check what the *API* does, so they should not fail because
of a bug in our client. Once ``api/client.py`` lands it gets its own tests.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

import pytest
from dotenv import load_dotenv

from gtrendscli.api.endpoints import build_url


@pytest.fixture(scope="session")
def api_key() -> str:
    """Return the key, or skip the whole suite if there isn't one."""
    load_dotenv()
    key = os.environ.get("TRENDS_API_KEY")
    if not key:
        # Raised rather than `pytest.skip()` so the return type stays honest.
        raise pytest.skip.Exception("TRENDS_API_KEY not set; see .env.example")
    return key


@pytest.fixture(scope="session")
def fetch(api_key):
    """Return a ``(endpoint, params) -> (status, body)`` callable."""

    def _fetch(endpoint, params):
        # The key goes in a header, not the query string. urllib puts the URL
        # into its exception messages, so a key in the query would be printed
        # by any network failure -- the same leak the production transport was
        # fixed for, and this file is published too.
        request = urllib.request.Request(
            f"{build_url(endpoint)}?{urllib.parse.urlencode(list(params))}",
            headers={"x-goog-api-key": api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, None

    return _fetch
