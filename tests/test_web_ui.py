import json
from http.client import HTTPConnection

from carrera_control.web_ui import WebState, start_web_ui


def test_web_ui_serves_status_and_jpeg_with_query_string() -> None:
    state = WebState()
    state.update(stage=5)
    server = start_web_ui(state, port=0)
    try:
        port = server.server_address[1]
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request("GET", "/api/status")
        status_response = connection.getresponse()
        assert status_response.status == 200
        assert json.loads(status_response.read()) == {"stage": 5}

        connection.request("GET", "/frame.jpg?cache_bust=1")
        frame_response = connection.getresponse()
        assert frame_response.status == 200
        assert frame_response.getheader("Content-Type") == "image/jpeg"
        assert frame_response.read() == b""
        connection.close()
    finally:
        server.shutdown()
        server.server_close()