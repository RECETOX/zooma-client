"""Health checks, against the v3 endpoint only (§Phase 2)."""

import pytest
import requests
import responses

from zooma_client import Client, ServiceUnavailableError, UnexpectedResponseError

BASE = "https://zooma.test"
HEALTH_URL = f"{BASE}/v3/api/health"


@responses.activate
def test_health_ok_text_plain():
    responses.get(HEALTH_URL, body="All systems are operational.", content_type="text/plain")
    assert Client(base_url=BASE).health() is True


@responses.activate
def test_health_http_error_raises():
    responses.get(HEALTH_URL, body="something broke", status=503)
    with pytest.raises(ServiceUnavailableError, match="HTTP 503"):
        Client(base_url=BASE).health()


@responses.activate
def test_health_transport_error_raises_with_cause():
    responses.get(HEALTH_URL, body=requests.ConnectionError("connection refused"))
    with pytest.raises(ServiceUnavailableError, match="unavailable") as excinfo:
        Client(base_url=BASE).health()
    assert isinstance(excinfo.value.__cause__, requests.ConnectionError)


@responses.activate
def test_health_html_is_not_healthy():
    # Any unknown path under /spot/zooma/ answers 200 with the web app's
    # HTML; a naive health check would report healthy no matter what.
    responses.get(HEALTH_URL, body="<html><body>Zooma</body></html>", content_type="text/html")
    with pytest.raises(UnexpectedResponseError, match="HTML"):
        Client(base_url=BASE).health()
