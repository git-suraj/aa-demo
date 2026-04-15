from __future__ import annotations

from contextvars import ContextVar
from typing import Any

TRACE_CONTEXT_HEADER_NAMES = ("traceparent", "tracestate", "baggage")

_CURRENT_TRACE_HEADERS: ContextVar[dict[str, str]] = ContextVar("current_trace_headers", default={})


def extract_trace_headers(headers: Any) -> dict[str, str]:
    trace_headers: dict[str, str] = {}
    for name in TRACE_CONTEXT_HEADER_NAMES:
        value = headers.get(name) if headers is not None else None
        if value:
            trace_headers[name] = str(value)
    return trace_headers


def set_trace_headers(headers: dict[str, str]):
    return _CURRENT_TRACE_HEADERS.set(dict(headers))


def set_trace_headers_from_request(request: Any):
    return set_trace_headers(extract_trace_headers(request.headers))


def reset_trace_headers(token: Any) -> None:
    _CURRENT_TRACE_HEADERS.reset(token)


def current_trace_headers() -> dict[str, str]:
    return dict(_CURRENT_TRACE_HEADERS.get())
