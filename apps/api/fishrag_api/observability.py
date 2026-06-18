from __future__ import annotations

import re
from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from starlette.requests import Request

TRACEPARENT_HEADER = "traceparent"
TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<trace_flags>[0-9a-f]{2})$"
)
REQUEST_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    trace_flags: str = "01"

    @property
    def header_value(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._request_totals: dict[tuple[str, str, str], int] = {}
        self._duration_sums: dict[tuple[str, str], float] = {}
        self._duration_counts: dict[tuple[str, str], int] = {}
        self._duration_buckets: dict[tuple[str, str, float], int] = {}

    def record_http_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        method = method.upper()
        status = str(status_code)
        labels = (method, path)
        with self._lock:
            self._request_totals[(method, path, status)] = (
                self._request_totals.get((method, path, status), 0) + 1
            )
            self._duration_sums[labels] = self._duration_sums.get(labels, 0.0) + duration_seconds
            self._duration_counts[labels] = self._duration_counts.get(labels, 0) + 1
            for bucket in REQUEST_DURATION_BUCKETS:
                if duration_seconds <= bucket:
                    key = (method, path, bucket)
                    self._duration_buckets[key] = self._duration_buckets.get(key, 0) + 1

    def render_prometheus(self, *, service: str, environment: str) -> str:
        lines = [
            "# HELP fishrag_app_info FishRag application information.",
            "# TYPE fishrag_app_info gauge",
            (
                'fishrag_app_info{'
                f'service="{_escape_label(service)}",environment="{_escape_label(environment)}"'
                "} 1"
            ),
            "# HELP fishrag_http_requests_total Total HTTP requests.",
            "# TYPE fishrag_http_requests_total counter",
        ]
        with self._lock:
            request_totals = dict(self._request_totals)
            duration_sums = dict(self._duration_sums)
            duration_counts = dict(self._duration_counts)
            duration_buckets = dict(self._duration_buckets)

        for (method, path, status), count in sorted(request_totals.items()):
            lines.append(
                'fishrag_http_requests_total{'
                f'method="{method}",path="{_escape_label(path)}",status_code="{status}"'
                f"}} {count}"
            )

        lines.extend(
            [
                "# HELP fishrag_http_request_duration_seconds HTTP request duration in seconds.",
                "# TYPE fishrag_http_request_duration_seconds histogram",
            ]
        )
        for method, path in sorted(duration_counts):
            labels = f'method="{method}",path="{_escape_label(path)}"'
            running_count = 0
            for bucket in REQUEST_DURATION_BUCKETS:
                running_count = duration_buckets.get((method, path, bucket), running_count)
                lines.append(
                    "fishrag_http_request_duration_seconds_bucket{"
                    f'{labels},le="{_format_bucket(bucket)}"'
                    f"}} {running_count}"
                )
            lines.append(
                "fishrag_http_request_duration_seconds_bucket{"
                f'{labels},le="+Inf"'
                f"}} {duration_counts[(method, path)]}"
            )
            lines.append(
                f"fishrag_http_request_duration_seconds_count{{{labels}}} "
                f"{duration_counts[(method, path)]}"
            )
            lines.append(
                f"fishrag_http_request_duration_seconds_sum{{{labels}}} "
                f"{duration_sums[(method, path)]:.6f}"
            )
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        with self._lock:
            self._request_totals.clear()
            self._duration_sums.clear()
            self._duration_counts.clear()
            self._duration_buckets.clear()


metrics_registry = MetricsRegistry()


def parse_or_create_trace_context(traceparent: str | None) -> TraceContext:
    if traceparent:
        match = TRACEPARENT_RE.match(traceparent.strip())
        if match and match.group("trace_id") != "0" * 32 and match.group("span_id") != "0" * 16:
            return TraceContext(
                trace_id=match.group("trace_id"),
                span_id=_new_span_id(),
                trace_flags=match.group("trace_flags"),
            )
    return TraceContext(trace_id=uuid4().hex, span_id=_new_span_id())


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return request.url.path


def _new_span_id() -> str:
    return uuid4().hex[:16]


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_bucket(value: float) -> str:
    return f"{value:g}"
