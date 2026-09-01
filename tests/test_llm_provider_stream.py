from types import SimpleNamespace
from unittest.mock import patch

from backend.llm.provider import chat_completion_stream


def _chunk(*, content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls or []))]
    )


def test_provider_stream_accumulates_text_and_fragmented_tool_arguments():
    chunks = [
        _chunk(content="בודקת "),
        _chunk(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id="call_1",
                    function=SimpleNamespace(name="propose_student_lock", arguments='{"student":"STUDENT_1",'),
                )
            ]
        ),
        _chunk(
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id=None,
                    function=SimpleNamespace(name=None, arguments='"locked":true,"rationale_hebrew":"קיבוע"}'),
                )
            ]
        ),
    ]
    completions = SimpleNamespace(create=lambda **kwargs: chunks)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    deltas = []

    with patch("backend.llm.provider._client", return_value=fake_client):
        result = chat_completion_stream("system", [{"role": "user", "content": "lock"}], [], deltas.append)

    assert deltas == ["בודקת "]
    assert result.text == "בודקת "
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "propose_student_lock"
    assert result.tool_calls[0].arguments["locked"] is True
    assert result.raw_message["tool_calls"][0]["function"]["arguments"].endswith('"קיבוע"}')
