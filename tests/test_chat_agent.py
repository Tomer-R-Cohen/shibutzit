"""The agent loop: read tools execute and their results reach the model.

The bug these cover: a counselor asked "why does ז3 have two more students"
and got a paragraph of "ייתכן ש..." because the model had never been told
the class sizes and had no way to ask. So the assertions here are mostly
about *what the model was actually shown* on its second call, not just
about the final string.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.llm.provider import ChatCompletion, ToolCall
from backend.llm.read_tools import execute_read_tool
from backend.session_store import store


@pytest.fixture
def client():
    return TestClient(backend_main.app)


@pytest.fixture
def session_headers(client):
    session_id = "chat-agent-test-session"
    store.reset(session_id)
    headers = {"X-Session-Id": session_id}
    client.post("/api/session", headers=headers)
    client.post("/api/workbook/load", headers=headers)
    guess = client.get("/api/mapping/guess", headers=headers).json()
    client.post(
        "/api/mapping/apply",
        headers=headers,
        json={"mapping": guess["mapping"], "manual_fields": guess["manual_fields"]},
    )
    yield headers
    store.reset(session_id)


@pytest.fixture
def solved_headers(client, session_headers):
    """A session with a real (fast) solve behind it, so the result-reading
    tools have something to read."""
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    opt = client.post("/api/optimize", headers=session_headers)
    assert opt.status_code == 200
    assert opt.json()["is_feasible"] is True
    return session_headers


def _tool_then_text(tool_name, args, answer):
    """Two-step model: call one read tool, then answer. Captures the message
    list it was handed on each call so tests can assert on what it saw."""
    seen = []

    def fake(system_prompt, messages, tools):
        seen.append({"system": system_prompt, "messages": list(messages), "tools": tools})
        if len(seen) == 1:
            return ChatCompletion(
                text=None,
                tool_calls=[ToolCall(id="c1", name=tool_name, arguments=args)],
                raw_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": tool_name, "arguments": "{}"}}],
                },
            )
        return ChatCompletion(text=answer, tool_calls=[], raw_message={"role": "assistant", "content": answer})

    return fake, seen


def test_read_tool_result_is_fed_back_to_the_model(client, solved_headers):
    fake, seen = _tool_then_text("get_class_sizes", {}, "ז3 גדולה בשתיים כי חוק הגודל מתיר טווח.")

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        resp = client.post("/api/chat/message", headers=solved_headers, json={"message": "למה ז3 גדולה יותר?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_proposal"] is None
    assert body["reply"].startswith("ז3")

    # The loop ran twice, and the second call carried a tool result.
    assert len(seen) == 2
    tool_msgs = [m for m in seen[1]["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    payload = tool_msgs[0]["content"]
    # The thing the old architecture could never provide: real numbers.
    assert '"classes"' in payload and '"size_rule"' in payload
    assert "how_size_is_decided" in payload

    # And the UI is told what it looked at.
    assert body["steps"] == [{"tool": "get_class_sizes", "ok": True}]


def test_write_tool_still_short_circuits_to_a_proposal(client, session_headers):
    """Reads execute; writes never do. A propose_* call must end the turn as
    a pending proposal, not run."""
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    a, b = students[0], students[1]
    message = f"{a['first_name']} {a['last_name']} ו{b['first_name']} {b['last_name']} לא יכולות להיות באותה כיתה"

    import re

    def fake(system_prompt, messages, tools):
        tokens = re.findall(r"STUDENT_\w+", messages[-1]["content"])
        return ChatCompletion(
            text=None,
            tool_calls=[
                ToolCall(
                    id="w1",
                    name="propose_separate",
                    arguments={"student_a": tokens[0], "student_b": tokens[1], "hard": True, "rationale_hebrew": "בקשה מפורשת"},
                )
            ],
        )

    before = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        resp = client.post("/api/chat/message", headers=session_headers, json={"message": message})

    assert resp.json()["pending_proposal"]["kind"] == "propose"
    after = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    assert after == before, "a write tool must not apply anything before confirmation"


def test_step_limit_forces_a_real_answer(client, solved_headers):
    """A model that only ever calls tools must still produce something for
    the counselor -- not an empty reply."""
    calls = []

    def always_tool(system_prompt, messages, tools):
        calls.append(tools)
        if not tools:  # the forced final call
            return ChatCompletion(text="הנה מה שמצאתי.", tool_calls=[], raw_message={"role": "assistant", "content": "x"})
        return ChatCompletion(
            text=None,
            tool_calls=[ToolCall(id=f"c{len(calls)}", name="get_solve_summary", arguments={})],
            raw_message={
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": f"c{len(calls)}", "type": "function", "function": {"name": "get_solve_summary", "arguments": "{}"}}],
            },
        )

    with patch("backend.llm.agent.chat_completion", side_effect=always_tool):
        resp = client.post("/api/chat/message", headers=solved_headers, json={"message": "תבדוק הכל"})

    assert resp.status_code == 200
    assert resp.json()["reply"] == "הנה מה שמצאתי."
    assert calls[-1] == [], "the final call must offer no tools, or the loop can't terminate"


# ------------------------------------------------------- read tools directly

def test_class_sizes_reports_real_sizes_and_the_governing_rule(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    out = execute_read_tool("get_class_sizes", {}, sess)

    assert len(out["classes"]) == sess.run_config.num_classes
    assert sum(c["size"] for c in out["classes"]) == len(sess.mapped_df)
    assert out["classes"][0]["class"] == 1, "class numbers must be 1-based, matching the UI"
    assert out["size_rule"] is not None
    assert out["size_rule"]["min"] is not None and out["size_rule"]["max"] is not None
    assert out["all_sizes_within_rule"] is True
    assert out["spread"] == out["largest"] - out["smallest"]


def test_result_tools_say_so_before_any_solve(client, session_headers):
    sess = store.get_or_create(session_headers["X-Session-Id"])
    for name in ("get_class_sizes", "get_solve_summary", "get_violations"):
        out = execute_read_tool(name, {}, sess)
        assert out["error"] == "no_assignment_yet", name


def test_query_roster_counts_and_stays_tokenized(client, session_headers):
    sess = store.get_or_create(session_headers["X-Session-Id"])
    sess.token_map.ensure_all(sess.mapped_df["student_id"].tolist())

    out = execute_read_tool("query_roster", {"category": "inclusion", "limit": 5}, sess)
    assert out["count"] <= out["total_roster"]
    assert len(out["tokens"]) <= 5
    assert all(t.startswith("STUDENT_") for t in out["tokens"])

    # Real names must never appear in anything a tool hands to the model.
    blob = repr(out)
    for name in sess.mapped_df["first_name"].dropna().unique()[:20]:
        assert str(name) not in blob


def test_bad_tool_arguments_come_back_as_data_not_an_exception(client, solved_headers):
    """A model that calls a tool wrong should get a message it can recover
    from, not abort the counselor's whole turn."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assert execute_read_tool("get_class_composition", {"class_number": 999}, sess)["error"] == "no_such_class"
    assert execute_read_tool("explain_student_placement", {"student": "STUDENT_nope"}, sess)["error"] == "unknown_student_token"
    assert execute_read_tool("get_class_composition", {}, sess)["error"] == "bad_arguments"
    assert execute_read_tool("no_such_tool", {}, sess)["error"] == "unknown_tool"


def test_active_rules_expose_numeric_bounds_not_just_labels(client, session_headers):
    """The old constraints context block only carried label_hebrew, so the
    model could not see that the size rule permits a range."""
    sess = store.get_or_create(session_headers["X-Session-Id"])
    out = execute_read_tool("get_active_rules", {}, sess)
    assert out["count"] > 0
    capacity = [r for r in out["rules"] if r["type"] == "capacity"]
    assert capacity, "expected the built-in capacity rules"
    assert any("min" in r or "max" in r for r in capacity)
