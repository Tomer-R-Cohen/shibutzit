import re
from collections import Counter
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.llm.provider import ChatCompletion, ToolCall
from backend.routers.chat import _StudentNameStream
from backend.session_store import PendingProposal, store


@pytest.fixture
def client():
    return TestClient(backend_main.app)


@pytest.fixture
def session_headers(client):
    session_id = "chat-router-test-session"
    store.reset(session_id)
    headers = {"X-Session-Id": session_id}
    client.post("/api/session", headers=headers)
    with patch("backend.routers.workbook.DEFAULT_WORKBOOK_PATH", "רשימה כללית לאיזונית.xlsx"):
        client.post(
            "/api/workbook/load",
            headers=headers,
            params={"header_row": 4, "first_data_row": 5, "last_data_row": 221},
        )
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


def test_history_and_split_stream_never_expose_internal_student_tokens(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    student = students[0]
    display_name = f"{student['first_name']} {student['last_name']}"
    sess = store.get_or_create("chat-router-test-session")
    sess.token_map.ensure_all(sess.mapped_df["student_id"].tolist())
    token = sess.token_map.token_for(student["student_id"])
    sess.chat_history.extend(
        [
            {"role": "user", "content": f"למה {token} כאן?"},
            {"role": "assistant", "content": f"בדקתי את {token}."},
        ]
    )
    sess.pending_proposal = PendingProposal(
        kind="remove",
        summary_hebrew=f"שינוי עבור {token}",
        target_constraint_id="test-rule",
    )

    history = client.get("/api/chat/history", headers=session_headers).json()
    rendered = str(history)
    assert token not in rendered
    assert display_name in rendered
    assert token in str(sess.chat_history), "authoritative memory must remain redacted"

    emitted = []
    stream = _StudentNameStream(sess, emitted.append)
    split = len(token) // 2
    stream.feed(f"לפני {token[:split]}")
    stream.feed(f"{token[split:]} אחרי")
    stream.flush()
    streamed = "".join(emitted)
    assert token not in streamed
    assert streamed == f"לפני {display_name} אחרי"


def test_ambiguous_name_short_circuits_without_calling_llm(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    names = Counter((r["first_name"], r["last_name"]) for r in students)
    dup = next((n for n, count in names.items() if count >= 2), None)
    assert dup is not None, "expected the real dataset's known duplicate-name pair"
    first, last = dup
    message = f"{first} {last} צריכה כיתה נפרדת"

    with patch("backend.llm.agent.chat_completion") as mocked:
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

    with patch("backend.llm.agent.chat_completion") as mocked:
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

    with patch("backend.llm.agent.chat_completion") as mocked:
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

    with patch("backend.llm.agent.chat_completion") as mocked:
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

    with patch("backend.llm.agent.chat_completion", side_effect=fake_modify):
        resp = client.post("/api/chat/message", headers=session_headers, json={"message": "בעצם זו רק העדפה, לא חובה"})
    assert resp.json()["pending_proposal"]["kind"] == "modify"

    confirm = client.post("/api/chat/confirm", headers=session_headers)
    assert confirm.json()["result"]["hard"] is False


def test_modify_constraint_updates_numeric_range(client, session_headers):
    constraints = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    target = next(c for c in constraints if c["type"] == "capacity" and c["args"].get("min") is not None)

    def fake_modify(system_prompt, messages, tools):
        return ChatCompletion(
            text=None,
            tool_calls=[
                ToolCall(
                    id="call_range",
                    name="modify_constraint",
                    arguments={
                        "constraint_id": target["id"],
                        "min_per_class": 1,
                        "max_per_class": 2,
                        "rationale_hebrew": "בכל כיתה יהיו 1–2 תלמידות מהקבוצה",
                    },
                )
            ],
        )

    with patch("backend.llm.agent.chat_completion", side_effect=fake_modify):
        proposal = client.post(
            "/api/chat/message",
            headers=session_headers,
            json={"message": "תשני את הטווח לאחת עד שתיים"},
        ).json()

    assert proposal["pending_proposal"]["changes"]["args"]["min"] == 1
    assert proposal["pending_proposal"]["changes"]["args"]["max"] == 2
    result = client.post("/api/chat/confirm", headers=session_headers).json()["result"]
    assert result["args"]["min"] == 1
    assert result["args"]["max"] == 2


def test_optimization_objective_cannot_be_made_mandatory(client, session_headers):
    constraints = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    target = next(c for c in constraints if c["type"] == "friendship_objective")
    calls = 0

    def fake(system_prompt, messages, tools):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ChatCompletion(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="unsafe_hard_objective",
                        name="modify_constraint",
                        arguments={
                            "constraint_id": target["id"],
                            "hard": True,
                            "rationale_hebrew": "להפוך חברות לחובה",
                        },
                    )
                ],
                raw_message={"role": "assistant", "content": None, "tool_calls": []},
            )
        return ChatCompletion(text="חברות נשארת יעד מועדף ולא כלל חובה.", tool_calls=[])

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        response = client.post(
            "/api/chat/message",
            headers=session_headers,
            json={"message": "שמרי את כללי התמיכה כחובה"},
        )
    assert response.status_code == 200
    assert response.json()["pending_proposal"] is None
    assert calls == 2
    unchanged = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    assert next(c for c in unchanged if c["id"] == target["id"])["hard"] is False


def test_noop_rule_change_is_skipped_so_requested_solver_run_can_continue(client, session_headers):
    constraints = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    target = next(c for c in constraints if c["type"] == "friendship_objective")
    calls = 0

    def fake(system_prompt, messages, tools):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ChatCompletion(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="noop_soft_objective",
                        name="modify_constraint",
                        arguments={
                            "constraint_id": target["id"],
                            "hard": False,
                            "rationale_hebrew": "להשאיר חברות כהעדפה",
                        },
                    )
                ],
                raw_message={"role": "assistant", "content": None, "tool_calls": []},
            )
        return ChatCompletion(
            text="הכללים כבר תואמים לבקשה, ולכן אפשר להריץ שלוש חלופות.",
            tool_calls=[
                ToolCall(
                    id="run_after_noop",
                    name="request_solver_run",
                    arguments={"alternatives": 3, "explain_results": True},
                )
            ],
            raw_message={"role": "assistant", "content": None, "tool_calls": []},
        )

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        response = client.post(
            "/api/chat/message",
            headers=session_headers,
            json={"message": "חברות היא יעד; הציגי שלוש חלופות"},
        )
    body = response.json()
    assert body["pending_proposal"] is None
    assert body["solver_run_requested"] is True
    assert body["solver_run_count"] == 3


def test_direct_friendship_priority_proposal_is_trial_solved_before_approval(client, session_headers):
    constraints = client.get("/api/constraints", headers=session_headers).json()["constraints"]
    target = next(c for c in constraints if c["type"] == "friendship_objective")

    def fake_model(system_prompt, messages, tools):
        return ChatCompletion(
            text=None,
            tool_calls=[
                ToolCall(
                    id="priority_write",
                    name="modify_constraint",
                    arguments={
                        "constraint_id": target["id"],
                        "weight_two_friends": 5,
                        "rationale_hebrew": "להעלות את עדיפות שתי החברות",
                    },
                )
            ],
        )

    evidence = {
        "feasible": True,
        "before": {"two_friends_pct": 31.9, "mutual_pct": 70.8},
        "after": {"two_friends_pct": 43.1, "mutual_pct": 66.7},
    }
    with (
        patch("backend.llm.agent.chat_completion", side_effect=fake_model),
        patch("backend.routers.chat.execute_simulation_tool", return_value=evidence) as simulated,
    ):
        body = client.post(
            "/api/chat/message",
            headers=session_headers,
            json={"message": "תציעי את שינוי עדיפות החברות"},
        ).json()

    simulated.assert_called_once()
    assert body["pending_proposal"]["kind"] == "modify"
    assert body["pending_proposal"]["evidence"] == evidence
    assert body["pending_proposal"]["changes"]["args"]["weight_two_friends"] == 5
    assert "אף כלל חובה לא ישתנה" in body["reply"]


def test_friendship_priority_prose_falls_back_to_measured_proposal(client, session_headers):
    evidence = {
        "feasible": True,
        "before": {"two_friends_pct": 31.9, "mutual_pct": 70.8},
        "after": {"two_friends_pct": 43.1, "mutual_pct": 66.7},
    }
    with (
        patch(
            "backend.llm.agent.chat_completion",
            return_value=ChatCompletion(text="אי אפשר לשנות את העדיפות.", tool_calls=[]),
        ),
        patch("backend.routers.chat.execute_simulation_tool", return_value=evidence) as simulated,
    ):
        body = client.post(
            "/api/chat/message",
            headers=session_headers,
            json={"message": "תציעי יותר חשיבות לחברות"},
        ).json()

    simulated.assert_called_once()
    assert body["pending_proposal"]["kind"] == "modify"
    assert body["pending_proposal"]["evidence"] == evidence
    assert "אף כלל חובה לא ישתנה" in body["reply"]


def test_direct_patch_and_delete_constraint_without_chat(client, session_headers):
    students = client.get("/api/students", headers=session_headers).json()["rows"]
    a, b = students[6], students[7]
    message = f"{a['first_name']} {a['last_name']} ו{b['first_name']} {b['last_name']} לא יכולות להיות באותה כיתה"

    with patch("backend.llm.agent.chat_completion") as mocked:
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
