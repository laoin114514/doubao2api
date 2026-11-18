"""Offline tests for BrowserClient failure/captcha accounting."""

from doubao2api.browser_client import BrowserClient


def test_rate_limit_does_not_mark_captcha_or_failure():
    client = BrowserClient()
    client.record_failure(710022004, "rate limited")
    assert client.needs_captcha is False
    assert client.consecutive_failures == 0
    assert client.last_error_code == 710022004


def test_captcha_message_marks_captcha():
    client = BrowserClient()
    client.record_failure(710022004, "please complete verification")
    assert client.needs_captcha is True
    assert client.consecutive_failures == 1


def test_five_failures_mark_not_ready_and_success_resets():
    client = BrowserClient()
    client._ready = True
    for _ in range(5):
        client.record_failure(500, "boom")
    assert client.is_ready is False
    client.record_success()
    assert client.consecutive_failures == 0
    assert client.needs_captcha is False
