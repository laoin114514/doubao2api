"""Offline unit tests for the pure helpers in :mod:`doubao2api.tool_calling`.

These tests never touch the network, a browser, or a login flow; they only
exercise prompt rendering, XML/JSON tool-call parsing and small detection
helpers that are shared by the live streaming code paths.
"""
import inspect
import json
import re

import pytest

from doubao2api.tool_calling import (
    PRIORITY_TOOLS,
    StreamingGuard,
    build_tool_system_prompt,
    detect_truncated_tool_call,
    format_tools_for_prompt,
    has_complete_tool_calls,
    is_tool_call_start,
    parse_tool_calls_xml,
)

WEATHER_ARGS = {"location": "Paris", "unit": "celsius"}


def make_tool(name="get_weather", description="Get the current weather", properties=None, required=None):
    """Build a single OpenAI-format function tool definition."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {} if properties is None else properties,
                "required": [] if required is None else required,
            },
        },
    }


def official_call(name="get_weather", arguments=None):
    """Build the official ``<tool_call>{json}</tool_call>`` format."""
    if arguments is None:
        arguments = WEATHER_ARGS
    return f'<tool_call>{{"name": "{name}", "arguments": {json.dumps(arguments)}}}</tool_call>'


class TestFormatToolsForPrompt:
    def test_required_and_optional_markers(self):
        tool = make_tool(
            properties={
                "location": {"type": "string", "description": "City name"},
                "unit": {"type": "string"},
            },
            required=["location"],
        )
        rendered = format_tools_for_prompt([tool])
        assert "location!: string" in rendered
        assert "unit?: string" in rendered
        assert "/* City name */" in rendered

    def test_everything_optional_when_required_list_missing(self):
        tool = make_tool(properties={"q": {"type": "string"}}, required=[])
        assert "q?: string" in format_tools_for_prompt([tool])

    def test_enum_and_array_types_are_compressed(self):
        tool = make_tool(
            properties={
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            required=[],
        )
        rendered = format_tools_for_prompt([tool])
        assert '"celsius"|"fahrenheit"' in rendered
        assert "tags?: string[]" in rendered

    def test_exact_signature_for_canonical_tool(self):
        tool = make_tool(
            properties={
                "location": {"type": "string", "description": "City name"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            required=["location"],
        )
        assert format_tools_for_prompt([tool]) == (
            "- get_weather{location!: string /* City name */, "
            'unit?: "celsius"|"fahrenheit"}: Get the current weather'
        )

    def test_non_function_entries_are_skipped(self):
        rendered = format_tools_for_prompt(
            [{"type": "not-a-function"}, make_tool(name="x", properties={}, required=[])]
        )
        assert rendered == "- x{}: Get the current weather"

    def test_empty_tool_list_renders_empty_string(self):
        assert format_tools_for_prompt([]) == ""

    def test_long_description_truncated_to_120_chars(self):
        description = "A" * 130
        rendered = format_tools_for_prompt([make_tool(description=description, properties={}, required=[])])
        assert "A" * 120 + "..." in rendered
        assert "A" * 121 not in rendered

    def test_many_tools_expand_priority_only(self):
        tools = [
            make_tool(
                name="bash",
                description="Run a shell command",
                properties={"command": {"type": "string"}},
                required=["command"],
            )
        ]
        tools += [
            make_tool(
                name=f"tool_{i}",
                description="d",
                properties={"p": {"type": "string"}},
                required=["p"],
            )
            for i in range(12)
        ]
        assert len(tools) == 13
        rendered = format_tools_for_prompt(tools).splitlines()
        assert "bash" in PRIORITY_TOOLS
        assert rendered[0] == "- bash{command!: string}: Run a shell command"
        assert rendered[1] == "- tool_0: d"
        assert "{" not in rendered[1]

    def test_many_tools_truncate_compact_description_to_80_chars(self):
        tools = [make_tool(name="bash", properties={}, required=[])]
        tools += [
            make_tool(name=f"tool_{i}", description="B" * 100, properties={}, required=[])
            for i in range(12)
        ]
        rendered = format_tools_for_prompt(tools).splitlines()
        assert rendered[1] == "- tool_0: " + "B" * 80 + "..."


class TestBuildToolSystemPrompt:
    def test_contains_tool_definition(self):
        prompt = build_tool_system_prompt(
            [
                make_tool(
                    properties={
                        "location": {"type": "string", "description": "City name"},
                        "unit": {"type": "string"},
                    },
                    required=["location"],
                )
            ]
        )
        assert "get_weather" in prompt
        assert "location!: string" in prompt
        assert "unit?: string" in prompt

    def test_contains_invocation_format_and_rules(self):
        prompt = build_tool_system_prompt([make_tool()])
        assert '<tool_call>\n{"name": "工具名", "arguments": {"参数名": "参数值"}}\n</tool_call>' in prompt
        assert "!为必填" in prompt
        assert "?为可选" in prompt
        assert "多个工具可并行调用" in prompt

    def test_multiple_tools_all_listed(self):
        prompt = build_tool_system_prompt(
            [
                make_tool(name="alpha", properties={}, required=[]),
                make_tool(name="beta", properties={}, required=[]),
            ]
        )
        assert "- alpha{}:" in prompt
        assert "- beta{}:" in prompt


class TestParseOfficialFormat:
    def test_single_call(self):
        calls = parse_tool_calls_xml(official_call())
        assert isinstance(calls, list)
        assert len(calls) == 1
        call = calls[0]
        assert call["type"] == "function"
        assert re.fullmatch(r"call_[0-9a-f]{24}", call["id"])
        assert call["function"]["name"] == "get_weather"
        arguments = call["function"]["arguments"]
        assert isinstance(arguments, str)  # OpenAI wire format expects a JSON string
        assert json.loads(arguments) == WEATHER_ARGS

    def test_multiple_calls_preserve_order_and_get_unique_ids(self):
        text = official_call("get_weather") + "\n" + official_call("get_time", {"tz": "UTC"})
        calls = parse_tool_calls_xml(text)
        assert [c["function"]["name"] for c in calls] == ["get_weather", "get_time"]
        assert [json.loads(c["function"]["arguments"]) for c in calls] == [WEATHER_ARGS, {"tz": "UTC"}]
        assert len({c["id"] for c in calls}) == 2

    def test_prose_around_blocks_is_ignored(self):
        text = "Sure, let me check.\n\n" + official_call() + "\n\nAnything else?"
        calls = parse_tool_calls_xml(text)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "get_weather"

    def test_arguments_already_a_json_string_are_preserved(self):
        text = '<tool_call>{"name": "f", "arguments": "{\\"a\\": 1}"}</tool_call>'
        calls = parse_tool_calls_xml(text)
        assert calls[0]["function"]["arguments"] == '{"a": 1}'

    def test_scalar_arguments_are_serialized(self):
        text = '<tool_call>{"name": "f", "arguments": 5}</tool_call>'
        assert parse_tool_calls_xml(text)[0]["function"]["arguments"] == "5"

    def test_missing_arguments_default_to_empty_object(self):
        text = '<tool_call>{"name": "f"}</tool_call>'
        assert parse_tool_calls_xml(text)[0]["function"]["arguments"] == "{}"

    def test_unquoted_keys_and_values_are_repaired(self):
        text = "<tool_call>{name: get_weather, arguments: {location: Paris}}</tool_call>"
        calls = parse_tool_calls_xml(text)
        assert calls[0]["function"]["name"] == "get_weather"
        assert json.loads(calls[0]["function"]["arguments"]) == {"location": "Paris"}

    def test_nested_arguments_are_preserved(self):
        arguments = {"opts": {"deep": [1, 2]}, "flag": True}
        calls = parse_tool_calls_xml(official_call("f", arguments))
        assert json.loads(calls[0]["function"]["arguments"]) == arguments


class TestParseFallbacks:
    def test_missing_opening_tag(self):
        text = 'I will call it now: {"name": "get_weather", "arguments": {"location": "Paris"}}</tool_call>'
        calls = parse_tool_calls_xml(text)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "get_weather"

    def test_bare_json_without_any_tags(self):
        text = 'Calling {"name": "get_weather", "arguments": {"location": "Paris"}} directly'
        calls = parse_tool_calls_xml(text)
        assert len(calls) == 1
        assert json.loads(calls[0]["function"]["arguments"]) == {"location": "Paris"}

    def test_legacy_invoke_format(self):
        text = (
            '<tool_calls><invoke name="get_weather">'
            '<parameter name="location">Paris</parameter>'
            '<parameter name="unit">celsius</parameter>'
            "</invoke></tool_calls>"
        )
        calls = parse_tool_calls_xml(text)
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "get_weather"
        assert json.loads(calls[0]["function"]["arguments"]) == {
            "location": "Paris",
            "unit": "celsius",
        }

    def test_legacy_multiple_invokes(self):
        text = (
            '<tool_calls><invoke name="a"><parameter name="x">1</parameter></invoke>'
            '<invoke name="b"></invoke></tool_calls>'
        )
        calls = parse_tool_calls_xml(text)
        assert [c["function"]["name"] for c in calls] == ["a", "b"]
        assert json.loads(calls[0]["function"]["arguments"]) == {"x": "1"}
        assert json.loads(calls[1]["function"]["arguments"]) == {}

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "hello world",
            "<tool_call></tool_call>",
            "<tool_call>not json</tool_call>",
            "<tool_calls></tool_calls>",
            '{"foo": 1}',
        ],
    )
    def test_unparseable_input_returns_none(self, text):
        assert parse_tool_calls_xml(text) is None


class TestValidToolNamesFilter:
    def test_none_means_no_filtering(self):
        calls = parse_tool_calls_xml(official_call("hallucinated"), valid_tool_names=None)
        assert calls is not None
        assert calls[0]["function"]["name"] == "hallucinated"

    def test_declared_tool_is_kept(self):
        calls = parse_tool_calls_xml(official_call("get_weather"), valid_tool_names={"get_weather"})
        assert calls is not None
        assert calls[0]["function"]["name"] == "get_weather"
        assert json.loads(calls[0]["function"]["arguments"]) == WEATHER_ARGS

    def test_unknown_tool_is_dropped(self):
        assert parse_tool_calls_xml(official_call("rm_rf"), valid_tool_names={"get_weather"}) is None

    def test_filtering_is_case_sensitive(self):
        assert parse_tool_calls_xml(official_call("Get_Weather"), valid_tool_names={"get_weather"}) is None
        assert parse_tool_calls_xml(official_call("get_weather"), valid_tool_names={"Get_Weather"}) is None
        assert parse_tool_calls_xml(official_call("Get_Weather"), valid_tool_names={"Get_Weather"}) is not None

    def test_mixed_calls_keep_only_declared_tools(self):
        text = "\n".join(
            [
                official_call("ghost_tool"),
                official_call("get_weather"),
                official_call("another_ghost"),
            ]
        )
        calls = parse_tool_calls_xml(text, valid_tool_names={"get_weather"})
        assert [c["function"]["name"] for c in calls] == ["get_weather"]

    def test_empty_whitelist_drops_everything(self):
        assert parse_tool_calls_xml(official_call(), valid_tool_names=set()) is None

    def test_filter_applies_to_partial_format(self):
        text = '{"name": "ghost_tool", "arguments": {"x": 1}}</tool_call>'
        assert parse_tool_calls_xml(text, valid_tool_names={"get_weather"}) is None
        assert parse_tool_calls_xml(text, valid_tool_names={"ghost_tool"}) is not None

    def test_filter_applies_to_bare_json_fallback(self):
        text = 'Calling {"name": "ghost_tool", "arguments": {"x": 1}} directly'
        assert parse_tool_calls_xml(text, valid_tool_names={"get_weather"}) is None
        calls = parse_tool_calls_xml(text, valid_tool_names={"ghost_tool"})
        assert calls is not None
        assert calls[0]["function"]["name"] == "ghost_tool"

    def test_filter_drops_call_without_name(self):
        text = '<tool_call>{"arguments": {"x": 1}}</tool_call>'
        assert parse_tool_calls_xml(text, valid_tool_names={"get_weather"}) is None

    def test_filter_applies_to_legacy_invoke_format(self):
        text = (
            '<tool_calls><invoke name="ghost_tool">'
            '<parameter name="x">1</parameter></invoke></tool_calls>'
        )
        assert parse_tool_calls_xml(text, valid_tool_names={"get_weather"}) is None
        calls = parse_tool_calls_xml(text, valid_tool_names={"ghost_tool"})
        assert calls is not None
        assert json.loads(calls[0]["function"]["arguments"]) == {"x": "1"}

    def test_filter_legacy_format_keeps_only_declared_invokes(self):
        text = (
            '<tool_calls><invoke name="ghost_tool"></invoke>'
            '<invoke name="get_weather"><parameter name="location">Paris</parameter></invoke>'
            "</tool_calls>"
        )
        calls = parse_tool_calls_xml(text, valid_tool_names={"get_weather"})
        assert [c["function"]["name"] for c in calls] == ["get_weather"]

    def test_signature_exposes_optional_whitelist(self):
        parameters = inspect.signature(parse_tool_calls_xml).parameters
        assert "valid_tool_names" in parameters
        assert parameters["valid_tool_names"].default is None


class TestDetectionHelpers:
    @pytest.mark.parametrize(
        "text",
        [
            "<tool_call>",
            '<tool_call>\n{"name": "f"}',
            "<tool_calls>",
            '{"name": "f"',
        ],
    )
    def test_is_tool_call_start_true(self, text):
        assert is_tool_call_start(text) is True

    @pytest.mark.parametrize("text", ["", "hello", "Here: <tool_call>", '{"arguments": {}}'])
    def test_is_tool_call_start_false(self, text):
        assert is_tool_call_start(text) is False

    @pytest.mark.parametrize(
        "text",
        [
            "x</tool_call>",
            "x</tool_calls>",
            '{"name":"f","arguments":{"a":1}}',
        ],
    )
    def test_has_complete_tool_calls_true(self, text):
        assert has_complete_tool_calls(text) is True

    @pytest.mark.parametrize("text", ["", '{"name":"f"}', "<tool_call>{\"name\": \"f\"", '{"arguments":{}}'])
    def test_has_complete_tool_calls_false(self, text):
        assert has_complete_tool_calls(text) is False

    @pytest.mark.parametrize(
        "text",
        [
            '<tool_call>{"name": "f", "arguments": {}}',
            "some text {",
            'raw "name"',
            'text {"',
        ],
    )
    def test_detect_truncated_tool_call_true(self, text):
        assert detect_truncated_tool_call(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "",
            '<tool_call>{"name": "f"}</tool_call>',
            "just some complete prose",
            "<tool_calls>done</tool_calls>",
        ],
    )
    def test_detect_truncated_tool_call_false(self, text):
        assert detect_truncated_tool_call(text) is False


class TestStreamingGuard:
    def test_warmup_buffers_until_threshold(self):
        guard = StreamingGuard()
        assert guard.feed("a" * 10) == ""
        assert guard.feed("b" * 69) == ""
        # 80 chars: warmup satisfied, but the guard window still holds everything back.
        assert guard.feed("c") == ""
        assert guard.full_buffer == "a" * 10 + "b" * 69 + "c"

    def test_emitted_chunks_plus_flush_cover_full_buffer(self):
        guard = StreamingGuard()
        chunks = ["x" * 100, "y" * 300, "z" * 50]
        emitted = "".join(guard.feed(chunk) for chunk in chunks)
        emitted += guard.flush()
        assert emitted == "".join(chunks)
        assert guard.flush() == ""

    def test_incomplete_tool_call_detection(self):
        guard = StreamingGuard()
        guard.feed('<tool_call>{"name": "f"}')
        assert guard.has_incomplete_tool_call() is True
        guard.feed("</tool_call>")
        assert guard.has_incomplete_tool_call() is False
