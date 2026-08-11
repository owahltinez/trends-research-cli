"""The one component that actually holds the API key.

Every other test substitutes a fake transport, which is exactly how a key leak
survived here: the suite asserted that `Client` and `build_params` never carry
the key, and neither of them ever could. These tests exercise the real class.
"""

import json

import pytest
import urllib3

from trends_research_cli.api.client import Client
from trends_research_cli.api.endpoints import Endpoint
from trends_research_cli.api.errors import ApiError, TransportError
from trends_research_cli.api.transport import Urllib3Transport

KEY = "AIzaSyNOT-A-REAL-KEY-0123456789"
URL = "https://www.googleapis.com/trends/v1beta/regions"
PARAMS = [("term", "influenza"), ("restrictions.geo", "US")]


class FakePool:
    """Stands in for urllib3, recording the request or raising like it does."""

    def __init__(self, *, status=200, body=None, raises=None):
        self.status = status
        self.body = body if body is not None else {"regions": []}
        self.raises = raises
        self.calls: list[dict] = []

    def request(self, method, url, *, fields, headers):
        self.calls.append(
            {"method": method, "url": url, "fields": fields, "headers": headers}
        )
        if self.raises is not None:
            raise self.raises

        return urllib3.HTTPResponse(
            body=json.dumps(self.body).encode(), status=self.status
        )


def transport_with(pool: FakePool) -> Urllib3Transport:
    transport = Urllib3Transport(KEY)
    transport._pool = pool
    return transport


def test_the_key_travels_as_a_header_not_in_the_query():
    """urllib3 puts the URL in its exception messages; the query string is
    therefore the one place the key must never be."""
    pool = FakePool()

    transport_with(pool).get(URL, PARAMS)

    call = pool.calls[0]
    assert call["headers"]["x-goog-api-key"] == KEY
    assert not any(
        KEY in str(value) for pair in call["fields"] for value in pair
    )
    assert KEY not in call["url"]


@pytest.mark.parametrize(
    "failure",
    [
        urllib3.exceptions.MaxRetryError(
            urllib3.HTTPSConnectionPool("www.googleapis.com"),
            URL,
            reason=Exception("dns"),
        ),
        urllib3.exceptions.ConnectTimeoutError("timed out"),
        urllib3.exceptions.SSLError("bad certificate"),
        urllib3.exceptions.ProtocolError("connection aborted"),
    ],
)
def test_no_network_failure_ever_reveals_the_key(failure):
    """The regression this file exists for: every one of these used to print
    the full request URL, key included, as an uncaught traceback."""
    transport = transport_with(FakePool(raises=failure))

    with pytest.raises(TransportError) as caught:
        transport.get(URL, PARAMS)

    message = str(caught.value)
    assert KEY not in message
    assert "www.googleapis.com" in message, "the host is useful, the URL is not"


def test_a_network_failure_names_the_host_and_the_kind_of_failure():
    transport = transport_with(
        FakePool(raises=urllib3.exceptions.ConnectTimeoutError("slow"))
    )

    with pytest.raises(TransportError, match="ConnectTimeoutError"):
        transport.get(URL, PARAMS)


def test_a_non_200_returns_the_status_without_a_body():
    """The error envelope is not data; `client` diagnoses the status instead."""
    response = transport_with(FakePool(status=403)).get(URL, PARAMS)

    assert response == (403, None)


def test_a_200_is_decoded():
    pool = FakePool(body={"regions": [{"regionCode": "US-CA"}]})

    response = transport_with(pool).get(URL, PARAMS)

    assert response.status == 200
    assert response.body == {"regions": [{"regionCode": "US-CA"}]}


# --- the client's half of the contract ---------------------------------------


class FailingTransport:
    def __init__(self, *failures):
        self.failures = list(failures)
        self.calls = 0

    def get(self, url, params):
        self.calls += 1
        raise self.failures.pop(0)


def test_network_failures_are_retried_then_reported_as_an_api_error():
    """A dropped connection is transient in the same way a 503 is."""
    transport = FailingTransport(*[TransportError("could not reach host")] * 4)
    client = Client(transport, sleep=lambda _: None, now=lambda: 0.0)

    with pytest.raises(ApiError) as caught:
        client.fetch(Endpoint.REGIONS, PARAMS)

    assert transport.calls == 4
    assert "could not reach host" in str(caught.value)


def test_a_transport_failure_never_escapes_as_a_raw_exception():
    """Anything but ApiError reaching the command layer becomes a traceback."""
    transport = FailingTransport(*[TransportError("could not reach host")] * 4)
    client = Client(transport, sleep=lambda _: None, now=lambda: 0.0)

    with pytest.raises(ApiError):
        client.fetch(Endpoint.REGIONS, PARAMS)
