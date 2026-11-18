"""Offline unit tests for :mod:`doubao2api.sse` (server-sent-event parsing)."""
import asyncio

from doubao2api.sse import _safe_json_loads, iter_sse_events


async def _collect(chunks):
    """Feed line chunks (bytes or str) through the async SSE parser."""

    async def _stream():
        for chunk in chunks:
            yield chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")

    return [event async for event in iter_sse_events(_stream())]


def parse(chunks):
    """Synchronously collect every event produced for ``chunks``."""
    return asyncio.run(_collect(chunks))


class TestIterSseEvents:
    def test_single_data_event(self):
        events = parse([b'data: {"a": 1}\n', b"\n"])
        assert events == [{"event": "message", "data": '{"a": 1}', "json": {"a": 1}}]

    def test_named_event(self):
        events = parse([b"event: partial\n", b'data: {"delta": "x"}\n', b"\n"])
        assert len(events) == 1
        assert events[0]["event"] == "partial"
        assert events[0]["json"] == {"delta": "x"}

    def test_event_name_is_stripped_and_empty_defaults_to_message(self):
        events = parse([b"event:   custom  \n", b"data: {}\n", b"\n", b"event:\n", b"data: {}\n", b"\n"])
        assert [event["event"] for event in events] == ["custom", "message"]

    def test_multiple_data_lines_are_joined_with_newline(self):
        events = parse([b'data: {"x":\n', b"data: 1}\n", b"\n"])
        assert len(events) == 1
        assert events[0]["data"] == '{"x":\n1}'
        assert events[0]["json"] == {"x": 1}

    def test_comment_lines_are_ignored(self):
        events = parse([b": keep-alive\n", b": another comment\n", b'data: {"a": 1}\n', b"\n"])
        assert events == [{"event": "message", "data": '{"a": 1}', "json": {"a": 1}}]

    def test_unknown_fields_are_ignored(self):
        events = parse([b"retry: 3000\n", b"id: 42\n", b'data: {"a": 1}\n', b"\n"])
        assert len(events) == 1
        assert events[0]["json"] == {"a": 1}

    def test_event_without_trailing_blank_line_is_flushed(self):
        events = parse([b'data: {"a": 1}\n'])
        assert len(events) == 1
        assert events[0]["json"] == {"a": 1}

    def test_trailing_blank_lines_do_not_duplicate_events(self):
        events = parse([b'data: {"a": 1}\n', b"\n", b"\n", b"\n"])
        assert len(events) == 1

    def test_malformed_json_is_returned_with_json_none(self):
        events = parse([b"data: not-json\n", b"\n"])
        assert events == [{"event": "message", "data": "not-json", "json": None}]

    def test_non_object_json_is_returned_with_json_none(self):
        events = parse([b"data: [1, 2]\n", b"\n"])
        assert events[0]["json"] is None
        assert events[0]["data"] == "[1, 2]"

    def test_empty_data_payload_is_emitted(self):
        events = parse([b"data:\n", b"\n"])
        assert events == [{"event": "message", "data": "", "json": None}]

    def test_leading_space_after_data_field_is_removed(self):
        events = parse([b"data:  hello\n", b"\n"])
        assert events[0]["data"] == "hello"

    def test_event_state_resets_between_events(self):
        events = parse([b"event: first\n", b"data: {}\n", b"\n", b'data: {"b": 2}\n', b"\n"])
        assert [event["event"] for event in events] == ["first", "message"]
        assert events[1]["json"] == {"b": 2}

    def test_crlf_line_endings_are_supported(self):
        events = parse([b'data: {"a": 1}\r\n', b"\r\n"])
        assert events == [{"event": "message", "data": '{"a": 1}', "json": {"a": 1}}]

    def test_empty_stream_yields_nothing(self):
        assert parse([]) == []

    def test_only_comments_yield_nothing(self):
        assert parse([b": ping\n", b"\n"]) == []


class TestSafeJsonLoads:
    def test_object_is_returned(self):
        assert _safe_json_loads('{"a": 1}') == {"a": 1}

    def test_invalid_json_returns_none(self):
        assert _safe_json_loads("{not json") is None

    def test_non_object_json_returns_none(self):
        assert _safe_json_loads("[1, 2]") is None
        assert _safe_json_loads('"text"') is None
        assert _safe_json_loads("42") is None
