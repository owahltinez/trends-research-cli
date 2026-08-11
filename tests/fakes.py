"""Offline stand-ins for the network layer."""

from trends_research_cli.api.client import Response


class FakeTransport:
    """Returns queued responses and records what it was asked for."""

    def __init__(self, *responses: Response):
        """Queue responses to hand back in order."""
        self.queued = list(responses)
        self.calls: list[tuple[str, list[tuple[str, str]]]] = []

    def get(self, url, params):
        """Record the call and pop the next queued response."""
        self.calls.append((url, list(params)))
        return self.queued.pop(0)


def timeline_body(*points: tuple[str, float], term: str = "flu") -> dict:
    """Build a `timelinesForHealth` payload in the API's own shape."""
    return {
        "lines": [
            {
                "term": term,
                "points": [
                    {"date": text, "value": value} for text, value in points
                ],
            }
        ]
    }
