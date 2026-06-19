from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

DEFAULT_BASE_URL = "http://localhost:8000/api/v1"
NO_PROXY_OPENER = build_opener(ProxyHandler({}))


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    text: str

    def json(self) -> object:
        return json.loads(self.text)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    status_code: int
    duration_ms: float
    detail: str
    url: str


@dataclass(frozen=True)
class AcceptanceReport:
    base_url: str
    results: list[CheckResult]

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.results if result.ok)


def run_acceptance_checks(
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 5.0,
) -> AcceptanceReport:
    normalized_base_url = base_url.rstrip("/")
    checks = (
        ("health", _endpoint(normalized_base_url, "health"), _check_health),
        ("metrics", _endpoint(normalized_base_url, "metrics"), _check_metrics),
        ("rag_score", _endpoint(normalized_base_url, "evaluations/rag/score"), _check_rag_score),
    )
    results: list[CheckResult] = []
    for name, url, check in checks:
        results.append(_run_check(name=name, url=url, timeout=timeout, check=check))
    return AcceptanceReport(base_url=normalized_base_url, results=results)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run FishRag MVP acceptance smoke checks.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    report = run_acceptance_checks(base_url=args.base_url, timeout=args.timeout)
    if args.json:
        print(json.dumps(_report_to_dict(report), ensure_ascii=False, indent=2))
    else:
        _print_report(report)
    return 0 if report.ok else 1


def _run_check(
    *,
    name: str,
    url: str,
    timeout: float,
    check: Callable[[str, float], tuple[bool, int, str]],
) -> CheckResult:
    started_at = time.perf_counter()
    try:
        ok, status_code, detail = check(url, timeout)
    except Exception as exc:  # noqa: BLE001 - CLI smoke checks should report every failure.
        ok = False
        status_code = 0
        detail = str(exc)
    duration_ms = (time.perf_counter() - started_at) * 1000
    return CheckResult(
        name=name,
        ok=ok,
        status_code=status_code,
        duration_ms=duration_ms,
        detail=detail,
        url=url,
    )


def _check_health(url: str, timeout: float) -> tuple[bool, int, str]:
    response = _request("GET", url, timeout=timeout)
    try:
        payload = _as_mapping(response.json())
    except json.JSONDecodeError:
        return False, response.status_code, "health endpoint did not return JSON"
    has_request_id = bool(response.headers.get("x-request-id"))
    has_traceparent = bool(response.headers.get("traceparent"))
    is_healthy = (
        response.status_code == 200
        and payload is not None
        and payload.get("status") == "ok"
        and has_request_id
        and has_traceparent
    )
    if is_healthy:
        return True, response.status_code, "service ok with request and trace headers"
    return (
        False,
        response.status_code,
        "expected 200 status=ok plus X-Request-ID and traceparent headers",
    )


def _check_metrics(url: str, timeout: float) -> tuple[bool, int, str]:
    response = _request("GET", url, timeout=timeout)
    expected_metrics = ("fishrag_app_info", "fishrag_http_requests_total")
    missing = [metric for metric in expected_metrics if metric not in response.text]
    if response.status_code == 200 and not missing:
        return True, response.status_code, "prometheus metrics exported"
    detail = "missing metrics: " + ", ".join(missing) if missing else "metrics endpoint failed"
    return False, response.status_code, detail


def _check_rag_score(url: str, timeout: float) -> tuple[bool, int, str]:
    payload = {
        "examples": [
            {
                "id": "acceptance-1",
                "query": "What evidence supports the answer?",
                "relevant_chunk_ids": ["chunk-a"],
                "retrieved_chunk_ids": ["chunk-a", "chunk-b"],
                "cited_chunk_ids": ["chunk-a"],
                "answer": "The answer is supported by chunk-a [C1].",
            }
        ],
        "ks": [1, 3],
    }
    response = _request("POST", url, timeout=timeout, payload=payload)
    try:
        body = _as_mapping(response.json())
    except json.JSONDecodeError:
        return False, response.status_code, "rag score endpoint did not return JSON"
    aggregate = _as_mapping(body.get("aggregate")) if body is not None else None
    recall_at_k = _as_mapping(aggregate.get("recall_at_k")) if aggregate is not None else None
    total_examples = aggregate.get("total_examples") if aggregate is not None else None
    recall_at_1 = _lookup_number(recall_at_k, "1")
    if response.status_code == 200 and total_examples == 1 and recall_at_1 == 1.0:
        return True, response.status_code, "rag evaluation scoring pipeline works"
    return False, response.status_code, "expected total_examples=1 and recall@1=1.0"


def _request(
    method: str,
    url: str,
    *,
    timeout: float,
    payload: dict[str, object] | None = None,
) -> HttpResponse:
    data: bytes | None = None
    headers = {"User-Agent": "fishrag-acceptance-smoke"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            raw_body = response.read()
            return HttpResponse(
                status_code=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                text=raw_body.decode("utf-8", errors="replace"),
            )
    except HTTPError as exc:
        raw_body = exc.read()
        return HttpResponse(
            status_code=exc.code,
            headers={key.lower(): value for key, value in exc.headers.items()},
            text=raw_body.decode("utf-8", errors="replace"),
        )
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc.reason}") from exc


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _as_mapping(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _lookup_number(mapping: dict[str, object] | None, key: str) -> float | None:
    if mapping is None:
        return None
    value = mapping.get(key)
    return float(value) if isinstance(value, int | float) else None


def _report_to_dict(report: AcceptanceReport) -> dict[str, object]:
    return {
        "base_url": report.base_url,
        "ok": report.ok,
        "passed": report.passed_count,
        "total": len(report.results),
        "results": [
            {
                "name": result.name,
                "ok": result.ok,
                "status_code": result.status_code,
                "duration_ms": round(result.duration_ms, 2),
                "detail": result.detail,
                "url": result.url,
            }
            for result in report.results
        ],
    }


def _print_report(report: AcceptanceReport) -> None:
    print(f"FishRag acceptance smoke: {report.base_url}")
    for result in report.results:
        status = "PASS" if result.ok else "FAIL"
        print(
            f"[{status}] {result.name} status={result.status_code} "
            f"duration_ms={result.duration_ms:.2f} - {result.detail}"
        )
    print(f"summary: {report.passed_count}/{len(report.results)} passed")


if __name__ == "__main__":
    sys.exit(main())
