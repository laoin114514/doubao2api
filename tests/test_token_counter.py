"""Offline unit tests for :mod:`doubao2api.token_counter`.

The token counter normally uses tiktoken; these tests force the deterministic
character-based fallback (or a fake encoder) so they pass without tiktoken and
without any network access.
"""
import builtins

import pytest

from doubao2api import token_counter


class FakeEncoder:
    """Minimal stand-in for a tiktoken encoding."""

    def __init__(self, token_count):
        self.token_count = token_count
        self.encoded_texts = []

    def encode(self, text):
        self.encoded_texts.append(text)
        return list(range(self.token_count))


@pytest.fixture(autouse=True)
def force_fallback_encoder(monkeypatch):
    """Make every test deterministic by pinning the fallback estimator."""
    monkeypatch.setattr(token_counter, "_encoder", "fallback")


class TestCountTokens:
    def test_empty_text_is_zero(self):
        assert token_counter.count_tokens("") == 0

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("x", 0),
            ("hello", 2),
            ("hello world!", 6),
            ("x" * 25, 13),
            ("x" * 100, 52),
            ("你好世界", 2),
        ],
    )
    def test_fallback_estimation(self, text, expected):
        assert token_counter.count_tokens(text) == expected

    @pytest.mark.parametrize("length", [1, 2, 5, 10, 100, 1000])
    def test_fallback_applies_safety_factor(self, length):
        text = "a" * length
        expected = int(length / 2.5 * token_counter.SAFETY_FACTOR)
        assert token_counter.count_tokens(text) == expected

    def test_count_grows_with_text_length(self):
        counts = [token_counter.count_tokens("a" * length) for length in (1, 5, 10, 100, 1000)]
        assert counts == sorted(counts)
        assert counts[-1] > counts[0]

    def test_tiktoken_encoder_path_is_used_when_available(self, monkeypatch):
        fake = FakeEncoder(10)
        monkeypatch.setattr(token_counter, "_encoder", fake)
        assert token_counter.count_tokens("hello") == int(10 * token_counter.SAFETY_FACTOR)
        assert fake.encoded_texts == ["hello"]

    def test_missing_tiktoken_falls_back_to_character_estimation(self, monkeypatch):
        monkeypatch.setattr(token_counter, "_encoder", None)
        real_import = builtins.__import__

        def import_without_tiktoken(name, *args, **kwargs):
            if name == "tiktoken":
                raise ImportError("tiktoken unavailable (simulated)")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", import_without_tiktoken)
        assert token_counter._get_encoder() == "fallback"
        assert token_counter._encoder == "fallback"
        assert token_counter.count_tokens("hello") == 2

    def test_existing_encoder_is_cached(self, monkeypatch):
        fake = FakeEncoder(3)
        monkeypatch.setattr(token_counter, "_encoder", fake)
        assert token_counter._get_encoder() is fake

    def test_tiktoken_initialisation_error_falls_back(self, monkeypatch):
        monkeypatch.setattr(token_counter, "_encoder", None)

        class BrokenTiktoken:
            @staticmethod
            def get_encoding(_name):
                raise RuntimeError("vocab download failed (simulated)")

        real_import = builtins.__import__

        def import_broken_tiktoken(name, *args, **kwargs):
            if name == "tiktoken":
                return BrokenTiktoken
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", import_broken_tiktoken)
        assert token_counter._get_encoder() == "fallback"
        assert token_counter._encoder == "fallback"


class TestCountMessagesTokens:
    def test_empty_messages_only_base_overhead(self):
        assert token_counter.count_messages_tokens([]) == 3

    def test_single_message_overhead_and_content(self):
        messages = [{"role": "user", "content": "hello"}]
        assert token_counter.count_messages_tokens(messages) == 3 + 4 + 2

    def test_multiple_messages_are_summed(self):
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"},
        ]
        # base 3 + (4 + 7) + (4 + 1)
        assert token_counter.count_messages_tokens(messages) == 3 + 11 + 5

    def test_missing_or_null_content_still_counts_overhead(self):
        assert token_counter.count_messages_tokens([{"role": "assistant", "content": None}]) == 3 + 4

    def test_tool_call_name_and_arguments_are_counted(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "f", "arguments": '{"a": 1}'},
                    }
                ],
            }
        ]
        # base 3 + message overhead 4 + name tokens 0 + arguments tokens 4
        assert token_counter.count_messages_tokens(messages) == 3 + 4 + 0 + 4

    def test_multiple_tool_calls_are_counted(self):
        tool_calls = [
            {"function": {"name": "alpha", "arguments": '{"x": 1}'}},
            {"function": {"name": "beta", "arguments": '{"y": 2}'}},
        ]
        with_calls = token_counter.count_messages_tokens(
            [{"role": "assistant", "content": None, "tool_calls": tool_calls}]
        )
        expected = (
            3
            + 4
            + token_counter.count_tokens("alpha")
            + token_counter.count_tokens('{"x": 1}')
            + token_counter.count_tokens("beta")
            + token_counter.count_tokens('{"y": 2}')
        )
        assert with_calls == expected

    def test_tool_message_content_is_counted(self):
        messages = [{"role": "tool", "tool_call_id": "call_1", "content": "hello"}]
        assert token_counter.count_messages_tokens(messages) == 3 + 4 + 2

    def test_multimodal_text_parts_are_counted_images_ignored(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "image_url", "image_url": {"url": "http://example.invalid/x.png"}},
                ],
            }
        ]
        assert token_counter.count_messages_tokens(messages) == 3 + 4 + 2

    def test_multiple_multimodal_text_parts_are_summed(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": "hi"},
                ],
            }
        ]
        assert token_counter.count_messages_tokens(messages) == 3 + 4 + 2 + 1

    def test_unknown_content_type_only_counts_overhead(self):
        messages = [{"role": "user", "content": {"unexpected": True}}]
        assert token_counter.count_messages_tokens(messages) == 3 + 4

    def test_count_grows_when_messages_are_appended(self):
        base = [{"role": "user", "content": "hello"}]
        before = token_counter.count_messages_tokens(base)
        after = token_counter.count_messages_tokens(base + [{"role": "assistant", "content": "hi"}])
        assert after > before
