from src.core.state.state import ConversationState


def test_as_prompt_without_history_uses_user_input_only():
    state = ConversationState(input="add 1 and 2")

    assert state.as_prompt() == "User: add 1 and 2"


def test_as_prompt_includes_history_entries():
    state = ConversationState(input="hello")
    state.append_llm("I can help")
    state.append_tool("echo", {"text": "hello"})

    assert state.as_prompt() == "User: hello\nLLM: I can help\nTOOL echo: {'text': 'hello'}"


def test_append_error_records_error_entry():
    state = ConversationState(input="run")
    state.append_error("echo", "failure")

    assert state.history == ["TOOL echo ERROR: failure"]


def test_reset_clears_runtime_state_and_preserves_input():
    state = ConversationState(input="run")
    state.append_llm("hello")
    state.last_result = object()
    state.last_error = "oops"
    state.step_count = 2
    state.metadata["k"] = "v"
    state.trace.append(object())

    state.reset()

    assert state.input == "run"
    assert state.history == []
    assert state.last_result is None
    assert state.last_error is None
    assert state.step_count == 0
    assert state.metadata == {}
    assert state.trace == []
