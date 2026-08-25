"""Planning: the app working before any spreadsheet exists.

The chat used to open with `require(sess.mapped_df, ...)`, so the counselor
had to finish building the file before she could discuss what belongs in it
-- which is backwards, since the discussion is what determines the answer.
These cover the inverted flow: chat with no data, a checklist that comes out
of it, and the checklist ticking itself off once a workbook arrives.
"""

from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.llm.planning_tools import execute_planning_tool
from backend.llm.provider import ChatCompletion, ToolCall
from backend.session_store import store
from src.data_requirements import DataRequirement, summarize
from src.dataset_schema import detect_extra_columns


@pytest.fixture
def client():
    return TestClient(backend_main.app)


@pytest.fixture
def empty_session(client):
    """A session with no workbook at all -- not even loaded."""
    session_id = "planning-test-session"
    store.reset(session_id)
    headers = {"X-Session-Id": session_id}
    client.post("/api/session", headers=headers)
    yield headers
    store.reset(session_id)


def _tool_then_text(calls_spec, answer):
    """Model that makes the given tool calls on turn 1, then answers."""
    seen = []

    def fake(system_prompt, messages, tools):
        seen.append(system_prompt)
        if len(seen) == 1:
            return ChatCompletion(
                text=None,
                tool_calls=[ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls_spec)],
                raw_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": "{}"}}
                        for i, (n, _a) in enumerate(calls_spec)
                    ],
                },
            )
        return ChatCompletion(text=answer, tool_calls=[], raw_message={"role": "assistant", "content": answer})

    return fake, seen


def test_chat_answers_with_no_workbook_at_all(client, empty_session):
    """The gate this removes: previously a 409 with "complete earlier steps"."""
    fake, seen = _tool_then_text([("set_class_count", {"num_classes": 7})], "קבעתי שבע כיתות.")

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        resp = client.post("/api/chat/message", headers=empty_session, json={"message": "בוא נחלק לשבע כיתות"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"] == "קבעתי שבע כיתות."
    assert body["state_changed"] is True, "a planning tool wrote state; the UI must be told to refresh"
    assert client.get("/api/run-config", headers=empty_session).json()["num_classes"] == 7


def test_planning_prompt_says_there_is_no_data(client, empty_session):
    """The model has to know reading tools will come back empty, or it burns
    the whole step budget discovering that."""
    fake, seen = _tool_then_text([("get_data_requirements", {})], "עוד לא רשמנו כלום.")
    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        client.post("/api/chat/message", headers=empty_session, json={"message": "מה המצב?"})

    assert "תכנון מקדים" in seen[0]
    assert "טרם נטען קובץ" in seen[0]


def test_conversation_builds_the_excel_checklist(client, empty_session):
    fake, _seen = _tool_then_text(
        [
            ("note_required_data", {"label": "תאומות", "kind": "flag", "reason": "להפריד תאומות"}),
            (
                "note_required_data",
                {"label": "שכונה", "kind": "category", "reason": "לאזן לפי שכונה", "values": ["צפון", "דרום"]},
            ),
        ],
        "רשמתי שתי עמודות.",
    )
    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        client.post("/api/chat/message", headers=empty_session, json={"message": "תאומות בנפרד, ואיזון לפי שכונה"})

    out = client.get("/api/data-requirements", headers=empty_session).json()
    assert out["total"] == 2
    assert out["missing"] == 2, "nothing can be satisfied before a workbook exists"
    assert out["has_dataset"] is False
    by_label = {r["label"]: r for r in out["requirements"]}
    assert by_label["תאומות"]["kind"] == "flag"
    assert by_label["שכונה"]["values"] == ["צפון", "דרום"]
    # The counselor is told how to fill it, not just what to call it.
    assert by_label["תאומות"]["how_to_fill"]


def test_recording_the_same_column_twice_updates_rather_than_duplicates(client, empty_session):
    sess = store.get_or_create(empty_session["X-Session-Id"])
    execute_planning_tool("note_required_data", {"label": "תאומות", "kind": "flag", "reason": "ראשון"}, sess)
    execute_planning_tool("note_required_data", {"label": " תאומות ", "kind": "flag", "reason": "שני"}, sess)

    assert len(sess.data_requirements) == 1
    assert sess.data_requirements[0].reason == "שני"


def test_checklist_ticks_itself_off_against_a_loaded_workbook():
    """Matching is on the visible header, because that is what the counselor
    types into Excel -- she is copying the name off the checklist."""
    reqs = [
        DataRequirement(label="תאומות", kind="flag", reason="x"),
        DataRequirement(label="שכונה", kind="category", reason="y"),
    ]
    raw = pd.DataFrame({"  תאומות ": ["כן", "", "כן"], "משהו אחר": [1.5, 2.5, 3.5]})
    schema = detect_extra_columns(raw, set())

    out = summarize(reqs, schema)
    by_label = {r["label"]: r for r in out["requirements"]}
    assert by_label["תאומות"]["satisfied"] is True, "whitespace in the header must not break the match"
    assert by_label["תאומות"]["column_key"] == "x_תאומות"
    assert by_label["שכונה"]["satisfied"] is False
    assert out["satisfied"] == 1 and out["missing"] == 1


def test_a_requirement_can_be_dropped(client, empty_session):
    sess = store.get_or_create(empty_session["X-Session-Id"])
    execute_planning_tool("note_required_data", {"label": "תאומות", "kind": "flag", "reason": "x"}, sess)
    rid = sess.data_requirements[0].id

    assert client.delete(f"/api/data-requirements/{rid}", headers=empty_session).json()["removed"] is True
    assert client.get("/api/data-requirements", headers=empty_session).json()["total"] == 0


def test_planning_tool_bad_arguments_come_back_as_data(client, empty_session):
    sess = store.get_or_create(empty_session["X-Session-Id"])
    assert execute_planning_tool("note_required_data", {"label": "x", "kind": "nonsense", "reason": "r"}, sess)["error"] == "bad_kind"
    assert execute_planning_tool("set_class_count", {"num_classes": 99}, sess)["error"] == "bad_arguments"
    assert execute_planning_tool("drop_required_data", {"label": "nope"}, sess)["error"] == "not_found"


def test_planning_tools_do_not_become_confirmation_cards(client, empty_session):
    """Only rules need a confirm card. A checklist note is not a rule, and
    making the counselor approve one would be ceremony without safety."""
    fake, _ = _tool_then_text([("note_required_data", {"label": "אחיות", "kind": "flag", "reason": "r"})], "רשמתי.")
    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        body = client.post("/api/chat/message", headers=empty_session, json={"message": "אחיות בנפרד"}).json()

    assert body["pending_proposal"] is None
    assert body["steps"] == [{"tool": "note_required_data", "ok": True}]
