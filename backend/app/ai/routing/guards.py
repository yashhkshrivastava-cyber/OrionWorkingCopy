"""Keeping a failing or busy provider from making everything slow: circuit breakers, a request-rate window, and cost estimates."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from app.ai import config


class CircuitBreaker:
    """After ``failures`` failures in a row the provider is left alone for ``cooldown`` seconds, then tried again once."""

    def __init__(self, failures: Callable[[], int] = config.breaker_failures, cooldown: Callable[[], int] = config.breaker_seconds, clock: Callable[[], float] = time.monotonic) -> None:
        self._failures, self._cooldown, self._clock = failures, cooldown, clock
        self._count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if self._clock() - self._opened_at >= self._cooldown():
                return False  # the cooldown is over: one attempt is let through (half open)
            return True

    def success(self) -> None:
        with self._lock:
            self._count, self._opened_at = 0, None

    def failure(self) -> None:
        with self._lock:
            self._count += 1
            if self._count >= self._failures():
                self._opened_at = self._clock()

    def reset(self) -> None:
        self.success()


class RateWindow:
    """At most ``limit()`` calls in any ``seconds`` (the cloud provider's rate, shared by everyone)."""

    def __init__(self, limit: Callable[[], int] = config.cloud_rpm, seconds: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit, self._seconds, self._clock = limit, seconds, clock
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def room(self) -> bool:
        with self._lock:
            self._trim()
            return len(self._hits) < self._limit()

    def take(self) -> bool:
        with self._lock:
            self._trim()
            if len(self._hits) >= self._limit():
                return False
            self._hits.append(self._clock())
            return True

    def _trim(self) -> None:
        now = self._clock()
        while self._hits and now - self._hits[0] > self._seconds:
            self._hits.popleft()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


local_breaker = CircuitBreaker()
cloud_breaker = CircuitBreaker()
cloud_rate = RateWindow()


def reset_all() -> None:
    local_breaker.reset()
    cloud_breaker.reset()
    cloud_rate.reset()


# ------------------------------------------------------------------------------------------------------- cost


def estimate_cost(tokens_in: int, tokens_out: int) -> float:
    """US dollars for a cloud answer. With prices configured it is from the tokens; without, a flat figure per answer."""
    price_in, price_out = config.cloud_prices()
    if price_in or price_out:
        return (tokens_in * price_in + tokens_out * price_out) / 1_000_000
    return config.cloud_flat_estimate()


def estimate_before(prompt_chars: int, max_output_tokens: int) -> float:
    """What a cloud answer might cost, before it is asked for: the most it could use."""
    return estimate_cost(prompt_chars // 4 + 1, max_output_tokens) if any(config.cloud_prices()) else config.cloud_flat_estimate()
