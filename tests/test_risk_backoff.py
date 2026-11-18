"""Offline tests for upstream rate-limit detection and local cooldown."""

import pytest

from doubao2api import unified_server as us


def test_looks_rate_limited_variants():
    assert us._looks_rate_limited(710022004, "rate limited")
    assert us._looks_rate_limited(710022004, "Rate Limit exceeded")
    assert us._looks_rate_limited(0, "too many requests")
    assert us._looks_rate_limited(710022004, "请求过于频繁，已限流")
    assert not us._looks_rate_limited(710022004, "please complete verification")
    assert not us._looks_rate_limited(500, "internal error")


def test_cooldown_helpers(monkeypatch):
    monkeypatch.setattr(us, "_risk_backoff_until", 0.0)
    assert us._risk_backoff_remaining() == 0
    us._check_risk_backoff()  # no raise when clear

    monkeypatch.setattr(us, "_risk_backoff_until", us.time.time() + 30)
    assert us._risk_backoff_remaining() > 0
    with pytest.raises(Exception) as excinfo:
        us._check_risk_backoff()
    assert getattr(excinfo.value, "status_code", None) == 429
