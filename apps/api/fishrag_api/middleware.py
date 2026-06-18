from __future__ import annotations

import logging
import time
from uuid import uuid4

from fishrag_common.logging import bind_request_id, bind_trace_context
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from fishrag_api.observability import (
    TRACEPARENT_HEADER,
    metrics_registry,
    parse_or_create_trace_context,
    route_template,
)

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER, str(uuid4()))
        trace_context = parse_or_create_trace_context(request.headers.get(TRACEPARENT_HEADER))
        bind_request_id(request_id)
        bind_trace_context(trace_context.trace_id, trace_context.span_id)
        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_seconds = time.perf_counter() - started_at
            path = route_template(request)
            metrics_registry.record_http_request(
                method=request.method,
                path=path,
                status_code=500,
                duration_seconds=duration_seconds,
            )
            logger.exception(
                "HTTP request failed",
                extra={
                    "_fishrag_extra": {
                        "method": request.method,
                        "path": path,
                        "status_code": 500,
                        "duration_ms": round(duration_seconds * 1000, 2),
                    }
                },
            )
            raise

        duration_seconds = time.perf_counter() - started_at
        path = route_template(request)
        duration_ms = round(duration_seconds * 1000, 2)
        metrics_registry.record_http_request(
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_seconds=duration_seconds,
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACEPARENT_HEADER] = trace_context.header_value
        logger.info(
            "HTTP request completed",
            extra={
                "_fishrag_extra": {
                    "method": request.method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }
            },
        )
        return response
