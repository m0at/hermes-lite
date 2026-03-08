"""Tests for the Rust-accelerated agent loop state machine."""

import pytest

try:
    from hermes_rs import (
        AgentLoopMachine,
        LoopState,
        Action,
        ResponseKind,
        strip_think_blocks,
        strip_tool_call_blocks,
        has_content_after_think,
    )
    HAS_HERMES_RS = True
except ImportError:
    HAS_HERMES_RS = False

pytestmark = pytest.mark.skipif(not HAS_HERMES_RS, reason="hermes_rs not built")


# ── Helpers ──────────────────────────────────────────────────────────────


def drive_to_state(m, target_state, response_kind=None):
    """Step through the state machine until we reach target_state."""
    if response_kind is None:
        response_kind = ResponseKind.Text
    m.begin_iteration()
    for _ in range(20):  # safety limit
        t = m.step(response_kind)
        if t.state == target_state:
            return t
    raise RuntimeError(f"Did not reach {target_state}")


def full_cycle_to_validate(m, adapter=False):
    """Drive one full iteration to ValidateToolCalls state."""
    m.begin_iteration()
    m.step(ResponseKind.Text)  # CheckInterrupt → PrepareRequest
    m.step(ResponseKind.Text)  # PrepareRequest → ApiCall
    m.step(ResponseKind.Text)  # ApiCall → ValidateResponse
    m.step(ResponseKind.Text)  # ValidateResponse → ParseResponse
    t = m.step(ResponseKind.Text)  # ParseResponse → AdaptToolCalls or ValidateToolCalls
    if adapter:
        # AdaptToolCalls → ValidateToolCalls
        return m.step(ResponseKind.ToolCalls)
    return t


def full_cycle_to_adapt(m):
    """Drive one full iteration to AdaptToolCalls state (needs_tool_adapter=True)."""
    m.begin_iteration()
    m.step(ResponseKind.Text)  # CheckInterrupt
    m.step(ResponseKind.Text)  # PrepareRequest
    m.step(ResponseKind.Text)  # ApiCall
    m.step(ResponseKind.Text)  # ValidateResponse
    return m.step(ResponseKind.Text)  # ParseResponse → AdaptToolCalls


# ── 1. Initialization ───────────────────────────────────────────────────

class TestInit:
    def test_default_state(self):
        m = AgentLoopMachine(max_iterations=10)
        assert m.state == LoopState.CheckInterrupt
        assert m.iteration == 0
        assert not m.interrupted
        assert not m.completed

    def test_custom_params(self):
        m = AgentLoopMachine(max_iterations=5, needs_tool_adapter=True, is_codex=True)
        assert m.state == LoopState.CheckInterrupt

    def test_repr(self):
        m = AgentLoopMachine(max_iterations=10)
        assert "AgentLoopMachine" in repr(m)


# ── 2. Basic text response flow ─────────────────────────────────────────

class TestTextFlow:
    def test_full_text_flow_no_adapter(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=False)
        m.begin_iteration()

        t = m.step(ResponseKind.Text)  # CheckInterrupt → PrepareRequest
        assert t.state == LoopState.PrepareRequest

        t = m.step(ResponseKind.Text)  # PrepareRequest → ApiCall
        assert t.state == LoopState.ApiCall

        t = m.step(ResponseKind.Text)  # ApiCall → ValidateResponse
        assert t.state == LoopState.ValidateResponse

        t = m.step(ResponseKind.Text)  # ValidateResponse → ParseResponse
        assert t.state == LoopState.ParseResponse

        t = m.step(ResponseKind.Text)  # ParseResponse → ValidateToolCalls (no adapter)
        assert t.state == LoopState.ValidateToolCalls

        t = m.step(ResponseKind.Text)  # ValidateToolCalls (no tools) → HandleFinalResponse
        assert t.state == LoopState.HandleFinalResponse

        t = m.step(ResponseKind.Text)  # HandleFinalResponse → Complete
        assert t.state == LoopState.Complete
        assert t.action == Action.Break

    def test_full_text_flow_with_adapter(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=True)
        m.begin_iteration()

        m.step(ResponseKind.Text)  # CheckInterrupt
        m.step(ResponseKind.Text)  # PrepareRequest
        m.step(ResponseKind.Text)  # ApiCall
        m.step(ResponseKind.Text)  # ValidateResponse
        t = m.step(ResponseKind.Text)  # ParseResponse → AdaptToolCalls
        assert t.state == LoopState.AdaptToolCalls

        t = m.step(ResponseKind.Text)  # AdaptToolCalls (no tools) → HandleFinalResponse
        assert t.state == LoopState.HandleFinalResponse

        t = m.step(ResponseKind.Text)
        assert t.state == LoopState.Complete


# ── 3. Tool call flow ───────────────────────────────────────────────────

class TestToolCallFlow:
    def test_native_tool_calls(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=False)
        m.begin_iteration()
        m.step(ResponseKind.Text)  # CheckInterrupt
        m.step(ResponseKind.Text)  # PrepareRequest
        m.step(ResponseKind.Text)  # ApiCall
        m.step(ResponseKind.Text)  # ValidateResponse
        m.step(ResponseKind.Text)  # ParseResponse

        t = m.step(ResponseKind.ToolCalls)  # ValidateToolCalls → ExecuteTools
        assert t.state == LoopState.ExecuteTools

        t = m.step(ResponseKind.Text)  # ExecuteTools → CheckInterrupt (next iter)
        assert t.state == LoopState.CheckInterrupt

    def test_adapted_tool_calls(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=True)
        m.begin_iteration()
        m.step(ResponseKind.Text)  # CheckInterrupt
        m.step(ResponseKind.Text)  # PrepareRequest
        m.step(ResponseKind.Text)  # ApiCall
        m.step(ResponseKind.Text)  # ValidateResponse
        m.step(ResponseKind.Text)  # ParseResponse → AdaptToolCalls

        t = m.step(ResponseKind.ToolCalls)  # AdaptToolCalls → ValidateToolCalls
        assert t.state == LoopState.ValidateToolCalls

        t = m.step(ResponseKind.ToolCalls)  # ValidateToolCalls → ExecuteTools
        assert t.state == LoopState.ExecuteTools


# ── 4. Truncated tool call handling ──────────────────────────────────────

class TestTruncatedToolCall:
    def test_nudge_on_truncated(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=True)
        full_cycle_to_adapt(m)
        t = m.step(ResponseKind.TruncatedToolCall)
        assert t.action == Action.Nudge
        assert t.state == LoopState.PrepareRequest
        assert "1/3" in t.message

    def test_fail_after_3_truncations(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=True)

        for i in range(3):
            full_cycle_to_adapt(m)
            t = m.step(ResponseKind.TruncatedToolCall)

        # After 3 truncations, should go to HandleFinalResponse
        assert t.state == LoopState.HandleFinalResponse


# ── 5. Invalid tool names ───────────────────────────────────────────────

class TestInvalidToolNames:
    def test_retry_then_fail(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=False)

        for i in range(2):
            full_cycle_to_validate(m)
            t = m.step(ResponseKind.InvalidToolNames)
            assert t.action == Action.Retry

        full_cycle_to_validate(m)
        t = m.step(ResponseKind.InvalidToolNames)
        assert t.action == Action.Fail


# ── 6. Invalid JSON args ────────────────────────────────────────────────

class TestInvalidJsonArgs:
    def test_retry_then_nudge(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=False)

        for i in range(2):
            full_cycle_to_validate(m)
            t = m.step(ResponseKind.InvalidToolJson)
            assert t.action == Action.Retry

        full_cycle_to_validate(m)
        t = m.step(ResponseKind.InvalidToolJson)
        assert t.action == Action.Nudge  # nudge after 3, not fail


# ── 7. Empty after think ────────────────────────────────────────────────

class TestEmptyAfterThink:
    def test_nudge_then_fail(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=False)

        # Drive to HandleFinalResponse and report EmptyAfterThink
        m.begin_iteration()
        m.step(ResponseKind.Text)  # CheckInterrupt
        m.step(ResponseKind.Text)  # PrepareRequest
        m.step(ResponseKind.Text)  # ApiCall
        m.step(ResponseKind.Text)  # ValidateResponse
        m.step(ResponseKind.Text)  # ParseResponse
        m.step(ResponseKind.Text)  # ValidateToolCalls → HandleFinalResponse

        t = m.step(ResponseKind.EmptyAfterThink)
        assert t.action == Action.Nudge
        assert "1/3" in t.message


# ── 8. Interrupt ─────────────────────────────────────────────────────────

class TestInterrupt:
    def test_interrupt_at_check(self):
        m = AgentLoopMachine(max_iterations=10)
        m.begin_iteration()
        m.set_interrupted()
        t = m.step(ResponseKind.Text)
        assert t.state == LoopState.Complete
        assert t.action == Action.Break
        assert m.interrupted

    def test_interrupt_flag(self):
        m = AgentLoopMachine(max_iterations=10)
        assert not m.interrupted
        m.set_interrupted()
        assert m.interrupted


# ── 9. Max iterations ───────────────────────────────────────────────────

class TestMaxIterations:
    def test_exceed_max(self):
        m = AgentLoopMachine(max_iterations=1)
        m.begin_iteration()  # iter 1 OK
        # Complete one full cycle with tools to trigger loop back
        m.step(ResponseKind.Text)  # CheckInterrupt
        m.step(ResponseKind.Text)  # PrepareRequest
        m.step(ResponseKind.Text)  # ApiCall
        m.step(ResponseKind.Text)  # ValidateResponse
        m.step(ResponseKind.Text)  # ParseResponse
        m.step(ResponseKind.ToolCalls)  # ValidateToolCalls → ExecuteTools
        m.step(ResponseKind.Text)  # ExecuteTools → CheckInterrupt

        r = m.begin_iteration()  # iter 2 > max 1
        assert r is not None
        assert r.state == LoopState.Complete
        assert r.action == Action.Break


# ── 10. API retries ──────────────────────────────────────────────────────

class TestApiRetries:
    def test_retry_on_invalid_response(self):
        m = AgentLoopMachine(max_iterations=10, max_api_retries=3)
        m.begin_iteration()
        m.step(ResponseKind.Text)  # CheckInterrupt
        m.step(ResponseKind.Text)  # PrepareRequest

        # First invalid response → retry
        t = m.step(ResponseKind.Invalid)
        assert t.action == Action.Retry
        assert t.state == LoopState.ApiCall

    def test_fail_after_max_retries(self):
        m = AgentLoopMachine(max_iterations=10, max_api_retries=2)
        m.begin_iteration()
        m.step(ResponseKind.Text)  # CheckInterrupt
        m.step(ResponseKind.Text)  # PrepareRequest

        m.step(ResponseKind.Invalid)  # retry 1
        t = m.step(ResponseKind.Invalid)  # retry 2 → fail
        assert t.action == Action.Fail


# ── 11. Incomplete scratchpad ────────────────────────────────────────────

class TestIncompleteScratchpad:
    def test_retry_twice_then_fail(self):
        m = AgentLoopMachine(max_iterations=10, needs_tool_adapter=False)

        # First try
        m.begin_iteration()
        m.step(ResponseKind.Text)  # CheckInterrupt
        m.step(ResponseKind.Text)  # PrepareRequest
        m.step(ResponseKind.Text)  # ApiCall
        m.step(ResponseKind.Text)  # ValidateResponse
        t = m.step(ResponseKind.IncompleteScratchpad)  # ParseResponse
        assert t.state == LoopState.CheckScratchpad

        t = m.step(ResponseKind.Text)  # CheckScratchpad → retry 1
        assert t.action == Action.Retry

        # Second try
        m.begin_iteration()
        m.step(ResponseKind.Text)
        m.step(ResponseKind.Text)
        m.step(ResponseKind.Text)
        m.step(ResponseKind.Text)
        m.step(ResponseKind.IncompleteScratchpad)
        t = m.step(ResponseKind.Text)  # retry 2
        assert t.action == Action.Retry

        # Third try → fail
        m.begin_iteration()
        m.step(ResponseKind.Text)
        m.step(ResponseKind.Text)
        m.step(ResponseKind.Text)
        m.step(ResponseKind.Text)
        m.step(ResponseKind.IncompleteScratchpad)
        t = m.step(ResponseKind.Text)
        assert t.action == Action.Fail


# ── 12. Debug counters ──────────────────────────────────────────────────

class TestDebugCounters:
    def test_counters_dict(self):
        m = AgentLoopMachine(max_iterations=10)
        m.begin_iteration()
        c = m.debug_counters()
        assert isinstance(c, dict)
        assert c["iteration"] == 1
        assert c["api_retries"] == 0
        assert "truncated_tc_retries" in c

    def test_reset(self):
        m = AgentLoopMachine(max_iterations=10)
        m.begin_iteration()
        m.set_interrupted()
        m.reset()
        assert m.iteration == 0
        assert not m.interrupted
        assert m.state == LoopState.CheckInterrupt


# ── 13. classify_content ────────────────────────────────────────────────

class TestClassifyContent:
    def test_text(self):
        k = AgentLoopMachine.classify_content(
            "hello world", False, "stop", False, False, False, False, True, True
        )
        assert k == ResponseKind.Text

    def test_tool_calls(self):
        k = AgentLoopMachine.classify_content(
            "", True, "stop", False, False, False, False, True, True
        )
        assert k == ResponseKind.ToolCalls

    def test_truncated(self):
        k = AgentLoopMachine.classify_content(
            "x", False, "length", False, False, False, False, True, True
        )
        assert k == ResponseKind.Truncated

    def test_truncated_tool_call(self):
        k = AgentLoopMachine.classify_content(
            "<tool_call>{broken", False, "stop", False, True, False, False, True, True
        )
        assert k == ResponseKind.TruncatedToolCall

    def test_empty_after_think(self):
        k = AgentLoopMachine.classify_content(
            "<think>reasoning</think>", False, "stop", False, False, False, False, True, True
        )
        assert k == ResponseKind.EmptyAfterThink

    def test_incomplete_scratchpad(self):
        k = AgentLoopMachine.classify_content(
            "x", False, "stop", False, False, False, True, True, True
        )
        assert k == ResponseKind.IncompleteScratchpad

    def test_invalid_tool_names(self):
        k = AgentLoopMachine.classify_content(
            "", True, "stop", False, False, False, False, False, True
        )
        assert k == ResponseKind.InvalidToolNames

    def test_invalid_tool_json(self):
        k = AgentLoopMachine.classify_content(
            "", True, "stop", False, False, False, False, True, False
        )
        assert k == ResponseKind.InvalidToolJson

    def test_codex_incomplete(self):
        k = AgentLoopMachine.classify_content(
            "x", False, "incomplete", True, False, False, False, True, True
        )
        assert k == ResponseKind.CodexIncomplete

    def test_complete_tag_but_parse_failed(self):
        k = AgentLoopMachine.classify_content(
            "<tool_call>bad json</tool_call>", False, "stop", False, True, True, False, True, True
        )
        assert k == ResponseKind.TruncatedToolCall


# ── 14. strip_think_blocks (Rust) ────────────────────────────────────────

class TestStripThinkBlocks:
    def test_closed(self):
        assert strip_think_blocks("<think>reasoning</think>answer") == "answer"

    def test_unclosed(self):
        assert strip_think_blocks("<think>no close") == ""

    def test_orphaned(self):
        assert strip_think_blocks("orphaned</think>  answer") == "answer"

    def test_multiple(self):
        content = "<think>a</think>mid<think>b</think>end"
        assert strip_think_blocks(content) == "midend"

    def test_no_think(self):
        assert strip_think_blocks("plain text") == "plain text"

    def test_empty(self):
        assert strip_think_blocks("") == ""


# ── 15. strip_tool_call_blocks (Rust) ────────────────────────────────────

class TestStripToolCallBlocks:
    def test_complete(self):
        r = strip_tool_call_blocks('text <tool_call>{"name":"x"}</tool_call> more')
        assert "<tool_call>" not in r
        assert "text" in r
        assert "more" in r

    def test_truncated(self):
        r = strip_tool_call_blocks('text <tool_call>{"name":"x"')
        assert "<tool_call>" not in r
        assert "text" in r

    def test_no_tags(self):
        assert strip_tool_call_blocks("plain") == "plain"

    def test_only_tag(self):
        assert strip_tool_call_blocks('<tool_call>{"x":1}</tool_call>').strip() == ""


# ── 16. has_content_after_think (Rust) ───────────────────────────────────

class TestHasContentAfterThink:
    def test_with_content(self):
        assert has_content_after_think("<think>x</think>real content") is True

    def test_without_content(self):
        assert has_content_after_think("<think>x</think>") is False

    def test_whitespace_only(self):
        assert has_content_after_think("<think>x</think>   ") is False

    def test_no_think(self):
        assert has_content_after_think("plain text") is True

    def test_empty(self):
        assert has_content_after_think("") is False


# ── 17. Integration wiring ──────────────────────────────────────────────

class TestIntegrationWiring:
    def test_loop_driver_available(self):
        from agent.loop_driver import is_available
        assert is_available() is True

    def test_classify_response_basic(self):
        from types import SimpleNamespace
        from agent.loop_driver import classify_response

        # Mock agent with valid_tool_names
        agent = SimpleNamespace(
            valid_tool_names={"execute_code", "read_file"},
            api_mode="chat",
        )
        msg = SimpleNamespace(
            content="Hello world",
            tool_calls=None,
        )
        kind = classify_response(agent, msg, "stop", "Hello world")
        assert kind == ResponseKind.Text

    def test_classify_truncated_tool_call(self):
        from types import SimpleNamespace
        from agent.loop_driver import classify_response

        agent = SimpleNamespace(
            valid_tool_names={"execute_code"},
            api_mode="chat",
        )
        msg = SimpleNamespace(
            content='<tool_call>{"name": "execute_code", "arguments": {"code": "x"',
            tool_calls=None,
        )
        kind = classify_response(agent, msg, "stop", msg.content)
        assert kind == ResponseKind.TruncatedToolCall
