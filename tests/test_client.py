"""Transport behaviour: retries, diagnostics and archiving (§7).

Every test here runs offline against a fake transport, so the suite stays fast
and never depends on the API being reachable.
"""

import json

import pytest
from fakes import FakeTransport

from gtrendscli.api.client import ApiError, Client, Response
from gtrendscli.api.endpoints import Endpoint

PARAMS = [("term", "flu"), ("restrictions.geo", "US")]


def client_with(*responses, **kwargs) -> tuple[Client, FakeTransport]:
    transport = FakeTransport(*responses)
    return Client(transport, sleep=lambda _: None, **kwargs), transport


def test_a_successful_response_returns_its_body():
    client, transport = client_with(Response(200, {"lines": []}))

    assert client.fetch(Endpoint.REGIONS, PARAMS) == {"lines": []}
    assert transport.calls[0][0].endswith("/regions")


def test_rate_limiting_is_retried_then_succeeds():
    client, transport = client_with(
        Response(429, None), Response(200, {"ok": True})
    )

    assert client.fetch(Endpoint.REGIONS, PARAMS) == {"ok": True}
    assert len(transport.calls) == 2


def test_a_500_is_never_retried():
    """Verified live: these endpoints answer a caller error with a 500, so
    retrying turns a user's typo into a backoff storm."""
    client, transport = client_with(Response(500, None))

    with pytest.raises(ApiError):
        client.fetch(Endpoint.TOP_QUERIES, PARAMS)

    assert len(transport.calls) == 1


def test_a_500_on_a_month_endpoint_names_the_likely_cause():
    client, _ = client_with(Response(500, None))

    with pytest.raises(ApiError, match="whole month"):
        client.fetch(Endpoint.TOP_QUERIES, PARAMS)


def test_a_400_names_the_parameter_family_as_the_likely_cause():
    client, _ = client_with(Response(400, None))

    with pytest.raises(ApiError, match="parameter"):
        client.fetch(Endpoint.TIMELINES, PARAMS)


def test_a_403_points_at_the_key_rather_than_the_request():
    client, _ = client_with(Response(403, None))

    with pytest.raises(ApiError, match="key"):
        client.fetch(Endpoint.REGIONS, PARAMS)


def test_retries_give_up_and_report_the_last_status():
    client, transport = client_with(*[Response(503, None)] * 4)

    with pytest.raises(ApiError, match="503"):
        client.fetch(Endpoint.REGIONS, PARAMS)

    assert len(transport.calls) == 4


def test_raw_responses_are_archived_for_provenance(tmp_path):
    """The API is sampled; the same query need not return the same numbers."""
    client, _ = client_with(Response(200, {"lines": [1]}), raw_dir=tmp_path)

    client.fetch(Endpoint.REGIONS, PARAMS)

    archived = list(tmp_path.glob("*.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text())["body"] == {"lines": [1]}


def test_the_archive_holds_what_a_re_check_would_need(tmp_path):
    """A published number has to stay defensible, so the archive records the
    call as well as the answer -- but the key is not part of either."""
    client, _ = client_with(Response(200, {"regions": []}), raw_dir=tmp_path)

    client.fetch(Endpoint.REGIONS, PARAMS)

    archived = json.loads(list(tmp_path.glob("*.json"))[0].read_text())
    assert archived["endpoint"] == "regions"
    assert archived["params"] == [list(pair) for pair in PARAMS]
    assert archived["retrieved_at"].endswith("+00:00"), "UTC, for provenance"
    # The transport adds the credential, so nothing here can carry it. The
    # real guarantee is exercised in tests/test_transport.py.
    assert "x-goog-api-key" not in json.dumps(archived).lower()


def test_requests_are_throttled_to_the_documented_rate_limit():
    """The API is limited to 2 queries per second; exceeding it is our fault."""
    slept: list[float] = []
    clock = iter([0.0, 0.0, 0.1, 0.1, 0.6, 0.6, 0.6, 0.6])

    client = Client(
        FakeTransport(*[Response(200, {})] * 3),
        sleep=slept.append,
        now=lambda: next(clock),
    )
    for _ in range(3):
        client.fetch(Endpoint.REGIONS, PARAMS)

    assert slept and all(delay > 0 for delay in slept)
    assert max(slept) <= 0.5


def test_a_500_names_an_unknown_category_as_well_as_a_short_range():
    """Both are caller mistakes this API reports as a server error; naming
    only one sends people hunting the wrong bug."""
    client, _ = client_with(Response(500, None))

    with pytest.raises(ApiError) as caught:
        client.fetch(Endpoint.TOP_QUERIES, PARAMS)

    message = str(caught.value)
    assert "whole month" in message
    assert "category id that does not exist" in message
    assert "--category-id" in message


def test_a_500_on_the_timelines_endpoint_mentions_neither():
    """It is day-granular and ignores categories, so neither cause applies."""
    client, _ = client_with(Response(500, None))

    with pytest.raises(ApiError) as caught:
        client.fetch(Endpoint.TIMELINES, PARAMS)

    assert "whole month" not in str(caught.value)
