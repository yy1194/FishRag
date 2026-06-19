from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from tools.acceptance_smoke import run_acceptance_checks


class AcceptanceApiHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/v1/health":
            self._write_json(
                {
                    "status": "ok",
                    "service": "FishRag",
                    "environment": "test",
                },
                headers={
                    "X-Request-ID": "acceptance-test",
                    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                },
            )
            return
        if self.path == "/api/v1/metrics":
            self._write_text(
                "\n".join(
                    [
                        "# HELP fishrag_app_info FishRag app info.",
                        "fishrag_app_info{service=\"FishRag\"} 1",
                        "# HELP fishrag_http_requests_total Total HTTP requests.",
                        "fishrag_http_requests_total{method=\"GET\",status_code=\"200\"} 1",
                    ]
                )
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/api/v1/evaluations/rag/score":
            self.send_error(404)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        json.loads(self.rfile.read(content_length))
        self._write_json(
            {
                "ks": [1, 3],
                "aggregate": {
                    "recall_at_k": {"1": 1.0, "3": 1.0},
                    "precision_at_k": {"1": 1.0, "3": 0.5},
                    "ndcg_at_k": {"1": 1.0, "3": 1.0},
                    "mrr": 1.0,
                    "faithfulness": 1.0,
                    "citation_coverage": 1.0,
                    "total_examples": 1,
                    "answered_examples": 1,
                },
                "examples": [],
            }
        )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _write_json(
        self,
        payload: dict[str, object],
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        response_headers = {"Content-Type": "application/json", **(headers or {})}
        self._write_body(body, status_code=status_code, headers=response_headers)

    def _write_text(self, payload: str, *, status_code: int = 200) -> None:
        self._write_body(
            payload.encode("utf-8"),
            status_code=status_code,
            headers={"Content-Type": "text/plain"},
        )

    def _write_body(
        self,
        body: bytes,
        *,
        status_code: int,
        headers: Mapping[str, str],
    ) -> None:
        self.send_response(status_code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def acceptance_api_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), AcceptanceApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_acceptance_smoke_passes_against_expected_api(acceptance_api_url: str) -> None:
    report = run_acceptance_checks(base_url=acceptance_api_url, timeout=1.0)

    assert report.ok
    assert report.passed_count == 3
    assert [result.name for result in report.results] == ["health", "metrics", "rag_score"]
