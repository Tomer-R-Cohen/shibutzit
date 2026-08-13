import re
from collections import Counter
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.llm.provider import ChatCompletion, ToolCall
from backend.session_store import store


@pytest.fixture
def client():
    return TestClient(backend_main.app)


@pytest.fixture
def session_headers(client):
    session_id = "chat-router-test-session"
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


def _fake_completion_from_last_message(messages, tool_name="propose_separate", extra=None):
    """Build a canned tool-call response that reuses whatever anonymized
    tokens actually appear in the redacted outgoing message -- this is what
    a real model would have to do too, since it never sees raw names."""
    redacted = messages[-1]["content"]
    # A Hebrew prefix conjunction (e.g. "ו") may be attached directly to a
    # token with no whitespace, so scan for the token pattern rather than
    # splitting on whitespace.
    tokens = re.findall(r"STUDENT_\w+", redacted)
    assert len(tokens) >= 2
    args = {"student_a": tokens[0], "student_b": tokens[1], "hard": True, "rationale_hebrew": "בקשה מפורשת להפריד"}
    if extra:
        args.update(extra)
    return ChatCompletion(text=None, tool_calls=[ToolCall(id="call_1", name=tool_name, arguments=args)])


def test_ambiguous_name_short_circuits_without_calling_llm(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    names = Counter((r["first_name"], r["last_name"]) for r in students)
    dup = next((n for n, count in names.items() if count >= 2), None)
    assert dup is not None, "expected the real dataset's known duplicate-name pair"
    first, last = dup
    message = f"{first} {last} צריכה כיתה נפרדת"

    with patch("backend.routers.chat.chat_completion") as mocked:
        resp = client.post("/api/chat/message", headers=session_headers, json={"message": message})
        mocked.assert_not_called()

    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_proposal"] is None
    assert "יותר מתלמידה אחת" in body["reply"]


def test_propose_then_confirm_adds_constraint_and_feeds_a_real_solve(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    a, b = students[0], students[1]
    message = f"{a['first_name']} {a['last_name']} ו{b['first_name']} {b['last_name']} לא יכולות להיות באותה כיתה"

    with patch("backend.routers.chat.chat_completion") as mocked:
        mocked.side_effect = lambda system_prompt, messages, tools: _fake_completion_from_last_message(messages)
        resp = client.post("/api/chat/message", headers=session_headers, json={"message": message})

    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_proposal"] is not None
    assert body["pending_proposal"]["kind"] == "propose"

    confirm = client.post("/api/chat/confirm", headers=session_headers)
    assert confirm.status_code == 200
    result = confirm.json()["result"]
    assert result["type"] == "separate"
    assert result["hard"] is True
    assert result["source"] == "chat"

    listed = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    assert any(c["id"] == result["id"] for c in listed)

    # Speed up the solve for the test; confirm it's wired into a real run,
    # not just displayed.
    cfg = client.get("/api/run-config", headers=session_headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=session_headers, json=cfg)
    opt = client.post("/api/optimize", headers=session_headers)
    assert opt.status_code == 200


def test_reject_discards_pending_proposal_without_applying(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    a, b = students[2], students[3]
    message = f"{a['first_name']} {a['last_name']} ו{b['first_name']} {b['last_name']} לא יכולות להיות באותה כיתה"

    before = client.get("/api/constraints", headers=session_headers).json()["constraints"]

    with patch("backend.routers.chat.chat_completion") as mocked:
        mocked.side_effect = lambda system_prompt, messages, tools: _fake_completion_from_last_message(messages)
        client.post("/api/chat/message", headers=session_headers, json={"message": message})

    reject = client.post("/api/chat/reject", headers=session_headers)
    assert reject.status_code == 200

    after = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    assert after == before


def test_modify_constraint_toggles_hard_soft(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    a, b = students[4], students[5]
    message = f"{a['first_name']} {a['last_name']} ו{b['first_name']} {b['last_name']} לא יכולות להיות באותה כיתה"

    with patch("backend.routers.chat.chat_completion") as mocked:
        mocked.side_effect = lambda system_prompt, messages, tools: _fake_completion_from_last_message(messages)
        client.post("/api/chat/message", headers=session_headers, json={"message": message})
    constraint_id = client.post("/api/chat/confirm", headers=session_headers).json()["result"]["id"]

    def fake_modify(system_prompt, messages, tools):
        return ChatCompletion(
            text=None,
            tool_calls=[
                ToolCall(
                    id="call_2",
                    name="modify_constraint",
                    arguments={"constraint_id": constraint_id, "hard": False, "rationale_hebrew": "בעצם זו רק העדפה"},
                )
            ],
        )

    with patch("backend.routers.chat.chat_completion", side_effect=fake_modify):
        resp = client.post("/api/chat/message", headers=session_headers, json={"message": "בעצם זו רק העדפה, לא חובה"})
    assert resp.json()["pending_proposal"]["kind"] == "modify"

    confirm = client.post("/api/chat/confirm", headers=session_headers)
    assert confirm.json()["result"]["hard"] is False


def test_direct_patch_and_delete_constraint_without_chat(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    a, b = students[6], students[7]
    message = f"{a['first_name']} {a['last_name']} ו{b['first_name']} {b['last_name']} לא יכולות להיות באותה כיתה"

    with patch("backend.routers.chat.chat_completion") as mocked:
        mocked.side_effect = lambda system_prompt, messages, tools: _fake_completion_from_last_message(messages)
        client.post("/api/chat/message", headers=session_headers, json={"message": message})
    constraint_id = client.post("/api/chat/confirm", headers=session_headers).json()["result"]["id"]

    patched = client.patch(f"/api/constraints/{constraint_id}", headers=session_headers, json={"active": False})
    assert patched.status_code == 200
    assert patched.json()["active"] is False

    deleted = client.delete(f"/api/constraints/{constraint_id}", headers=session_headers)
    assert deleted.status_code == 200
    assert deleted.json()["removed"] is True

    listed = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    assert all(c["id"] != constraint_id for c in listed)


def test_llm_not_configured_returns_503(client, session_headers, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    a, b = students[8], students[9]
    message = f"{a['first_name']} {a['last_name']} ו{b['first_name']} {b['last_name']} לא יכולות להיות באותה כיתה"
    resp = client.post("/api/chat/message", headers=session_headers, json={"message": message})
    assert resp.status_code == 503
