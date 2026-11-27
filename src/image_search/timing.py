"""Request-local diagnostic spans; nested spans must not be summed as total latency."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

_current = ContextVar("search_timing", default=None)


@contextmanager
def capture():
    values = {}
    token = _current.set(values)
    try:
        yield values
    finally:
        _current.reset(token)


@contextmanager
def span(name):
    values = _current.get()
    if values is None:
        yield
        return
    start = perf_counter()
    try:
        yield
    finally:
        values[name] = values.get(name, 0.0) + (perf_counter() - start) * 1000


def timed(name):
    def decorate(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            with span(name):
                return fn(*args, **kwargs)

        return call

    return decorate


def profile_result(fn):
    """Attach diagnostic spans to a search result without shared mutable request state."""

    @wraps(fn)
    def call(*args, **kwargs):
        with capture() as values:
            start = perf_counter()
            result = fn(*args, **kwargs)
            values["service_ms"] = (perf_counter() - start) * 1000
        result.setdefault("timing_ms", {}).update(values)
        return result

    return call
