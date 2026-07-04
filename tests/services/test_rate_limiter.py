"""Tests for the RateLimiter used by the dashboard API."""

from __future__ import annotations

import time

from paper_trading.api.common import RateLimiter


class TestRateLimiter:
    def test_allows_requests_under_limit(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60.0)
        for _ in range(5):
            assert limiter.is_allowed("127.0.0.1") is True

    def test_blocks_request_at_limit(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60.0)
        for _ in range(3):
            limiter.is_allowed("127.0.0.1")
        assert limiter.is_allowed("127.0.0.1") is False

    def test_tracks_per_ip_independently(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60.0)
        assert limiter.is_allowed("client_a") is True
        assert limiter.is_allowed("client_a") is True
        assert limiter.is_allowed("client_a") is False  # client_a blocked
        assert limiter.is_allowed("client_b") is True  # client_b still allowed

    def test_remaining_returns_correct_count(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60.0)
        assert limiter.remaining("127.0.0.1") == 5
        limiter.is_allowed("127.0.0.1")
        assert limiter.remaining("127.0.0.1") == 4
        limiter.is_allowed("127.0.0.1")
        assert limiter.remaining("127.0.0.1") == 3

    def test_window_expires_old_requests(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=0.05)
        assert limiter.is_allowed("127.0.0.1") is True
        assert limiter.is_allowed("127.0.0.1") is True
        assert limiter.is_allowed("127.0.0.1") is False  # blocked
        time.sleep(0.06)
        assert limiter.is_allowed("127.0.0.1") is True  # window expired

    def test_different_ips_dont_interfere(self) -> None:
        limiter = RateLimiter(max_requests=1, window_seconds=60.0)
        assert limiter.is_allowed("10.0.0.1") is True
        assert limiter.is_allowed("10.0.0.1") is False  # blocked
        assert limiter.is_allowed("10.0.0.2") is True  # different IP

    def test_zero_max_requests_blocks_everything(self) -> None:
        limiter = RateLimiter(max_requests=0, window_seconds=60.0)
        assert limiter.is_allowed("127.0.0.1") is False
        assert limiter.is_allowed("10.0.0.1") is False

    def test_default_rate_limit_is_100_per_minute(self) -> None:
        limiter = RateLimiter()
        assert limiter.max_requests == 100
        assert limiter.window_seconds == 60.0
