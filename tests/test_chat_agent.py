"""The agent loop: read tools execute and their results reach the model.

The bug these cover: a counselor asked "why does ז3 have two more students"
and got a paragraph of "ייתכן ש..." because the model had never been told
the class sizes and had no way to ask. So the assertions here are mostly
about *what the model was actually shown* on its second call, not just
about the final string.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.llm.provider import ChatCompletion, ToolCall
from backend.llm.read_tools import execute_read_tool
from backend.routers.chat import (
    _build_proposal,
    _display_student_names,
    _grounded_solver_comparison,
    _grounded_student_explanation,
    _grounded_student_version_explanation,
    _proposal_from_friendship_simulation,
    _suggested_actions,
)
from backend.llm.tools import ToolArgumentError
from backend.session_store import store
from src.constraints import Constraint
from src.friendship_graph import NameResolutionResult


@pytest.fixture
def client():
    return TestClient(backend_main.app)


@pytest.fixture
def session_headers(client):
    session_id = "chat-agent-test-session"
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
        resp = client.post("/api/chat/message", headers=solved_headers, json={"message": "בדוק את גדלי הכיתות"})

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


def test_streaming_chat_emits_deltas_tool_activity_and_authoritative_result(client, solved_headers):
    calls = 0

    def fake_stream(system_prompt, messages, tools, on_text_delta):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ChatCompletion(
                text=None,
                tool_calls=[ToolCall(id="stream_tool", name="get_class_sizes", arguments={})],
                raw_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "stream_tool",
                            "type": "function",
                            "function": {"name": "get_class_sizes", "arguments": "{}"},
                        }
                    ],
                },
            )
        on_text_delta("בדקתי ")
        on_text_delta("את הגדלים.")
        answer = "בדקתי את הגדלים."
        return ChatCompletion(text=answer, tool_calls=[], raw_message={"role": "assistant", "content": answer})

    with patch("backend.llm.agent.chat_completion_stream", side_effect=fake_stream):
        response = client.post(
            "/api/chat/message/stream",
            headers=solved_headers,
            json={"message": "מה גודל הכיתות?"},
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[0] == {"type": "status", "status": "thinking"}
    assert [event["text"] for event in events if event["type"] == "delta"] == ["בדקתי ", "את הגדלים."]
    assert any(event["type"] == "tool" and event["tool"] == "get_class_sizes" for event in events)
    result = next(event["data"] for event in events if event["type"] == "result")
    assert result["reply"] == "בדקתי את הגדלים."
    assert result["steps"] == [{"tool": "get_class_sizes", "ok": True}]
    assert store.get_or_create(solved_headers["X-Session-Id"]).chat_history[-1]["content"] == result["reply"]


def test_post_solver_analysis_streams_and_remains_read_only(client, solved_headers):
    calls = 0

    def fake_stream(system_prompt, messages, tools, on_text_delta):
        nonlocal calls
        calls += 1
        offered = {tool["function"]["name"] for tool in tools}
        assert "request_solver_run" not in offered
        assert not any(name.startswith("propose_") for name in offered)
        if calls == 1:
            return ChatCompletion(
                text=None,
                tool_calls=[ToolCall(id="versions", name="get_assignment_versions", arguments={})],
                raw_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "versions",
                            "type": "function",
                            "function": {"name": "get_assignment_versions", "arguments": "{}"},
                        }
                    ],
                },
            )
        on_text_delta("מצאתי גרסה תקינה.")
        answer = "מצאתי גרסה תקינה."
        return ChatCompletion(text=answer, tool_calls=[], raw_message={"role": "assistant", "content": answer})

    sess = store.get_or_create(solved_headers["X-Session-Id"])
    with patch("backend.llm.agent.chat_completion_stream", side_effect=fake_stream):
        response = client.post(
            "/api/chat/solver-result/stream",
            headers=solved_headers,
            json={"version_ids": [sess.current_version_id]},
        )

    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert any(event["type"] == "delta" and event["text"] == "מצאתי גרסה תקינה." for event in events)
    assert any(event["type"] == "tool" and event["tool"] == "get_assignment_versions" for event in events)
    assert next(event["data"] for event in events if event["type"] == "result")["reply"] == "מצאתי גרסה תקינה."


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

    confirmed = client.post("/api/chat/confirm", headers=session_headers)
    assert confirmed.status_code == 200
    decisions = client.get("/api/project-memory", headers=session_headers).json()["decisions"]
    assert decisions[-1]["decision"] == "approved"
    assert decisions[-1]["summary"] == "בקשה מפורשת"


def test_explicit_chat_run_request_is_forwarded_to_frontend(client, session_headers):
    """The model selects a typed handoff; chat itself does not bypass the
    normal optimize route or invent a result."""
    fake, _seen = _tool_then_text(
        "request_solver_run",
        {},
        "אני מעבירה עכשיו את הנתונים והכללים המאושרים למנוע השיבוץ.",
    )

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        resp = client.post("/api/chat/message", headers=session_headers, json={"message": "תריצי את השיבוץ"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["solver_run_requested"] is True
    assert body["solver_run_count"] == 1
    assert body["steps"] == [{"tool": "request_solver_run", "ok": True}]
    assert store.get_or_create(session_headers["X-Session-Id"]).opt_result is None


def test_chat_can_request_three_real_alternatives(client, session_headers):
    fake, _seen = _tool_then_text(
        "request_solver_run",
        {"alternatives": 3, "explain_results": True},
        "אכין שלוש חלופות ואציג את ההבדלים ביניהן.",
    )
    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        body = client.post(
            "/api/chat/message",
            headers=session_headers,
            json={"message": "תחלק ותציג לי כמה אפשרויות ותפרט על השיבוצים"},
        ).json()

    assert body["solver_run_requested"] is True
    assert body["solver_run_count"] == 3


def test_explicit_three_option_request_cannot_be_satisfied_by_prose_alone(client, session_headers):
    with patch(
        "backend.llm.agent.chat_completion",
        return_value=ChatCompletion(
            text="הפעלתי את השיבוץ עם שלוש אפשרויות.",
            tool_calls=[],
        ),
    ):
        body = client.post(
            "/api/chat/message",
            headers=session_headers,
            json={"message": "תחלק ותציג לי כמה אפשרויות ותפרט על השיבוצים"},
        ).json()

    assert body["solver_run_requested"] is True
    assert body["solver_run_count"] == 3
    assert body["steps"] == [{"tool": "request_solver_run", "ok": True}]
    assert "אפיק שלוש חלופות" in body["reply"]


def test_explicit_multi_option_request_overrides_an_undercounted_tool_call(client, session_headers):
    fake, _seen = _tool_then_text(
        "request_solver_run",
        {"alternatives": 1, "explain_results": True},
        "אכין שיבוץ אחד.",
    )
    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        body = client.post(
            "/api/chat/message",
            headers=session_headers,
            json={"message": "תחלק ותציג לי כמה אפשרויות ותפרט על השיבוצים"},
        ).json()

    assert body["solver_run_requested"] is True
    assert body["solver_run_count"] == 3
    assert "שלוש חלופות אמיתיות" in body["reply"]


def test_solver_result_continuation_reads_versions_and_cannot_write(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    version_id = sess.current_version_id
    fake, seen = _tool_then_text(
        "get_assignment_versions",
        {},
        "יצרתי גרסה תקינה אחת על סמך כל הכללים הפעילים.",
    )

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        resp = client.post(
            "/api/chat/solver-result",
            headers=solved_headers,
            json={"version_ids": [version_id]},
        )

    assert resp.status_code == 200
    assert resp.json()["steps"] == [{"tool": "get_assignment_versions", "ok": True}]
    offered = {tool["function"]["name"] for tool in seen[0]["tools"]}
    assert "get_assignment_versions" in offered
    assert "request_solver_run" not in offered
    assert not any(name.startswith("propose_") for name in offered)
    assert store.get_or_create(solved_headers["X-Session-Id"]).chat_history[-1]["role"] == "assistant"


def test_conversational_move_and_lock_waits_for_confirmation(client, solved_headers):
    import re

    students = client.get("/api/students", headers=solved_headers).json()["rows"]
    student = students[0]
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    student_id = student["student_id"]
    original_class = sess.adjustment_state.assignment[student_id] + 1
    new_class = 1 if original_class != 1 else 2
    versions_before = len(sess.assignment_versions)

    def fake(system_prompt, messages, tools):
        token = re.findall(r"STUDENT_\w+", messages[-1]["content"])[0]
        return ChatCompletion(
            text=None,
            tool_calls=[
                ToolCall(
                    id="move_1",
                    name="propose_student_placement",
                    arguments={
                        "student": token,
                        "class_number": new_class,
                        "lock_after_move": True,
                        # The model may omit this despite the user's explicit
                        # "try again"; the application must preserve intent.
                        "rerun_after": False,
                        "rationale_hebrew": "להעביר ולקבע את התלמידה לפני ניסיון נוסף",
                    },
                )
            ],
        )

    message = f"תעבירי את {student['first_name']} {student['last_name']} לכיתה {new_class}, תשאירי אותה שם ותנסי שוב"
    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        proposed = client.post("/api/chat/message", headers=solved_headers, json={"message": message}).json()

    assert proposed["pending_proposal"]["kind"] == "assignment_action"
    assert proposed["pending_proposal"]["action_args"]["rerun_after"] is True
    assert sess.adjustment_state.assignment[student_id] + 1 == original_class

    confirmed = client.post("/api/chat/confirm", headers=solved_headers).json()
    assert confirmed["action_kind"] == "move_student"
    assert confirmed["solver_run_requested"] is True
    assert sess.adjustment_state.assignment[student_id] + 1 == new_class
    assert sess.locked_assignment[student_id] == new_class - 1
    assert len(sess.assignment_versions) == versions_before + 1
    violations = confirmed["result"]["metrics"]["violations_count"]
    if violations > 0:
        assert str(violations) in confirmed["confirmation_message"]
        assert "טיוטה" in confirmed["confirmation_message"]
        assert "לא ניתן לאשר" in confirmed["confirmation_message"]
    else:
        assert "כל כללי החובה עדיין מתקיימים" in confirmed["confirmation_message"]


def test_conversational_move_cannot_silently_unlock_a_student(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    student_id, current_zero = next(iter(sess.adjustment_state.assignment.items()))
    current_class = current_zero + 1
    target_class = 1 if current_class != 1 else 2
    locked = client.post(
        "/api/adjustment/move",
        headers=solved_headers,
        json={"student_id": student_id, "new_class": current_class, "locked": True},
    )
    assert locked.status_code == 200

    with pytest.raises(ToolArgumentError, match="explicitly approve unlocking"):
        _build_proposal(
            "propose_student_placement",
            {
                "student": sess.token_map.token_for(student_id),
                "class_number": target_class,
                "lock_after_move": False,
                "rerun_after": False,
                "rationale_hebrew": "העברה לכיתה אחרת",
            },
            sess,
        )

    assert sess.adjustment_state.assignment[student_id] + 1 == current_class
    assert sess.locked_assignment[student_id] == current_zero


def test_conversational_version_restore_waits_for_confirmation(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    original_id = sess.current_version_id
    student_id, current = next(iter(sess.adjustment_state.assignment.items()))
    new_class = 1 if current + 1 != 1 else 2
    client.post(
        "/api/adjustment/move",
        headers=solved_headers,
        json={"student_id": student_id, "new_class": new_class},
    )
    assert sess.current_version_id != original_id

    def fake(system_prompt, messages, tools):
        return ChatCompletion(
            text=None,
            tool_calls=[
                ToolCall(
                    id="restore_1",
                    name="propose_restore_version",
                    arguments={
                        "version_id": original_id,
                        "rationale_hebrew": "לחזור לגרסה שלפני ההעברה הידנית",
                    },
                )
            ],
        )

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        proposed = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": "תחזרי לגרסה שלפני ההעברה הידנית"},
        ).json()

    assert proposed["pending_proposal"]["action"] == "restore_version"
    assert sess.current_version_id != original_id
    confirmed = client.post("/api/chat/confirm", headers=solved_headers).json()
    assert confirmed["action_kind"] == "restore_version"
    assert sess.current_version_id == original_id


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


def test_whole_assignment_analysis_exposes_evidence_without_claiming_causality(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    out = execute_read_tool("analyze_assignment_quality", {}, sess)

    assert out["measured_current_state"]["total_students"] == len(sess.mapped_df)
    assert len(out["class_profiles"]) == sess.run_config.num_classes
    assert out["hard_rule_compliance"]["all_satisfied"] is True
    assert out["class_size_rule"]["id"]
    assert out["active_optimization_priorities"]
    assert out["diagnostic_findings"]
    assert all("kind" in finding and "evidence" in finding for finding in out["diagnostic_findings"])
    assert all("interpretation_limit" in finding for finding in out["diagnostic_findings"])
    assert "counterfactual" in out["reasoning_boundary"]


def test_assignment_analysis_calculates_friendship_data_ceilings_and_attention_students(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    by_class = {}
    for student_id, class_index in sess.adjustment_state.assignment.items():
        by_class.setdefault(class_index, []).append(student_id)
    classes = sorted(by_class)
    first, second = by_class[classes[0]][0], by_class[classes[1]][0]
    third = by_class[classes[2]][0]
    fourth = by_class[classes[3]][0]
    sess.friendship_result = NameResolutionResult(
        matched={
            first: [second],
            second: [first],
            third: [fourth, first],
        }
    )

    out = execute_read_tool("analyze_assignment_quality", {}, sess)
    finding = next(item for item in out["diagnostic_findings"] if item["kind"] == "friendship_outcomes")
    evidence = finding["evidence"]

    assert evidence["students_with_requests"] == 3
    assert evidence["students_with_no_requested_friend"] == 3
    assert evidence["mutual_data_ceiling_pct"] == round(200 / len(sess.mapped_df), 1)
    assert evidence["two_friends_data_ceiling_pct"] == round(100 / len(sess.mapped_df), 1)
    assert {item["student"] for item in evidence["attention_students"]} == {
        sess.token_map.token_for(first),
        sess.token_map.token_for(second),
        sess.token_map.token_for(third),
    }
    assert "jointly feasible" in finding["interpretation_limit"]


def test_broad_analysis_runs_the_highest_ranked_grounded_counterfactual(client, solved_headers):
    seen = {}
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    objective = next(constraint for constraint in sess.constraints if constraint.active and constraint.type == "balance")
    analysis = {
        "hard_rule_compliance": {"all_satisfied": True, "violation_count": 0, "violations": []},
        "diagnostic_findings": [
            {
                "kind": "academic_distribution",
                "priority": "high",
                "evidence": {"worst_distributions": [{"value": "high", "counts_by_class": [5, 2, 3, 3, 3, 2], "spread": 3}]},
                "interpretation_limit": "measured, not causal",
                "suggested_test": {"tool": "simulate_balance_priority", "constraint_id": objective.id, "weight": 4},
            }
        ],
    }
    trial = {
        "feasible": True,
        "change": "academic balance priority 2->4",
        "before": {"academic_spread": 8, "class_sizes": [36, 36, 36, 36, 36, 37], "violations": 0},
        "after": {"academic_spread": 5, "class_sizes": [36, 36, 36, 36, 36, 37], "violations": 0},
        "deltas": {"academic_spread": -3, "mutual_pct": -1.0, "two_friends_pct": 0.0},
    }

    def fake_model(system_prompt, messages, tools):
        seen["payload"] = messages[0]["content"]
        return ChatCompletion(
            text="מצאתי ריכוז לימודי בכיתה אחת. בניסוי ממוקד הפער ירד מ-8 ל-5, במחיר ירידה של נקודת אחוז בחברות.",
            tool_calls=[],
            raw_message={"role": "assistant", "content": "analysis"},
        )

    with (
        patch("backend.routers.chat.execute_read_tool", return_value=analysis),
        patch("backend.routers.chat.execute_simulation_tool", return_value=trial) as simulation,
        patch("backend.llm.agent.chat_completion", side_effect=fake_model),
    ):
        resp = client.post("/api/chat/message", headers=solved_headers, json={"message": "תנתח את השיבוץ ותמצא מה כדאי לשפר"})
        followup = client.post("/api/chat/message", headers=solved_headers, json={"message": "כן, תשתמש בשינוי שבדקת"})

    assert resp.status_code == 200
    assert [step["tool"] for step in resp.json()["steps"]] == ["analyze_assignment_quality", "simulate_balance_priority"]
    simulation.assert_called_once_with(
        "simulate_balance_priority",
        {"constraint_id": objective.id, "weight": 4},
        store.get_or_create(solved_headers["X-Session-Id"]),
    )
    assert '"completed_targeted_trial"' in seen["payload"]
    assert '"academic_spread": 5' in seen["payload"]
    assert followup.status_code == 200
    proposal = followup.json()["pending_proposal"]
    assert proposal["kind"] == "modify"
    assert proposal["target_constraint_id"] == objective.id
    assert proposal["changes"]["args"]["weight"] == 4
    assert proposal["evidence"]["basis"] == "measured_trial"

    # Chat and the approval card are synchronized controls. A typed approval
    # must apply the already-visible proposal instead of returning to the LLM.
    confirmed = client.post("/api/chat/message", headers=solved_headers, json={"message": "כן"})
    assert confirmed.status_code == 200
    assert confirmed.json()["pending_proposal"] is None
    assert confirmed.json()["solver_run_requested"] is True
    assert next(c for c in sess.constraints if c.id == objective.id).args["weight"] == 4


def test_model_led_capacity_trial_is_remembered_and_yes_starts_full_solve(client, solved_headers):
    """Regression for: trial -> 'apply officially?' -> yes -> same trial again."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    size_rule = next(
        constraint
        for constraint in sess.constraints
        if constraint.active
        and constraint.type == "capacity"
        and constraint.args.get("group", {}).get("kind") == "all"
    )
    student_count = len(sess.mapped_df)
    class_count = sess.run_config.num_classes
    floor_size, remainder = divmod(student_count, class_count)
    ceil_size = floor_size + (1 if remainder else 0)
    # Keep the proposed range arithmetically capable of holding the whole
    # roster. An exact floor-sized class range is impossible whenever there
    # is a remainder, and the confirmation safety gate correctly refuses to
    # launch a solve for such a proposal.
    candidates = [
        (floor_size, ceil_size),
        (max(0, floor_size - 1), ceil_size),
        (floor_size, ceil_size + 1),
    ]
    new_min, new_max = next(
        pair for pair in candidates if pair != (size_rule.args.get("min"), size_rule.args.get("max"))
    )
    simulation_args = {"constraint_id": size_rule.id, "min": new_min, "max": new_max}
    trial = {
        "feasible": True,
        "change": "tested exact class size",
        "before": {"class_sizes": [4, 5, 5, 5, 4, 5], "violations": 0},
        "after": {"class_sizes": [floor_size] * (class_count - remainder) + [ceil_size] * remainder, "violations": 0},
        "deltas": {"size_spread": -1, "mutual_pct": 2.0, "academic_spread": 0},
        "caveat": "short trial",
    }
    fake, seen = _tool_then_text(
        "simulate_capacity_change",
        simulation_args,
        "הניסוי הצליח. האם תרצי להחיל את השינוי באופן קבוע ולהריץ שיבוץ מלא?",
    )

    with (
        patch("backend.llm.agent.chat_completion", side_effect=fake),
        patch("backend.llm.agent.execute_simulation_tool", return_value=trial),
    ):
        experimental = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": "כן, תראי לי"},
        )
        applied = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": "כן"},
        )

    assert experimental.status_code == 200
    assert experimental.json()["steps"] == [{"tool": "simulate_capacity_change", "ok": True}]
    assert len(seen) == 2, "the approval follow-up must not call the model or repeat the trial"
    assert applied.status_code == 200
    assert applied.json()["pending_proposal"] is None
    assert applied.json()["solver_run_requested"] is True
    assert "מריץ עכשיו את השיבוץ מחדש" in applied.json()["reply"]
    updated = next(c for c in sess.constraints if c.id == size_rule.id)
    assert updated.args["min"] == new_min
    assert updated.args["max"] == new_max


def test_specific_class_analysis_compares_against_every_other_class(client, solved_headers):
    seen = {}

    def fake(system_prompt, messages, tools):
        seen["payload"] = messages[0]["content"]
        seen["tools"] = tools
        answer = "כיתה 2 אינה חריגה בגודל, אבל יש בה ריכוז גבוה יותר של קטגוריה אחת ביחס לשאר הכיתות."
        return ChatCompletion(text=answer, tool_calls=[], raw_message={"role": "assistant", "content": answer})

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        resp = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": "תנתח את כיתה 2 ותסביר מה חריג בה לעומת השאר"},
        )

    assert resp.status_code == 200
    assert resp.json()["steps"] == [
        {"tool": "get_class_composition", "ok": True},
        {"tool": "analyze_assignment_quality", "ok": True},
    ]
    assert seen["tools"] == []
    assert '"requested_class": 2' in seen["payload"]
    assert '"all_class_profiles"' in seen["payload"]
    assert '"ranked_assignment_findings"' in seen["payload"]


def test_independent_rule_feasibility_question_is_grounded_in_roster_arithmetic(client, session_headers):
    seen = {}
    sess = store.get_or_create(session_headers["X-Session-Id"])
    sess.mapped_df.loc[:, "differential"] = False
    sess.mapped_df.loc[sess.mapped_df.index[:7], "differential"] = True

    def fake(system_prompt, messages, tools):
        seen["system_prompt"] = system_prompt
        seen["payload"] = messages[0]["content"]
        seen["tools"] = tools
        answer = "מצאתי כללי חובה בלתי אפשריים בחשבון ישיר; לא שיניתי אף כלל."
        return ChatCompletion(text=answer, tool_calls=[], raw_message={"role": "assistant", "content": answer})

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        response = client.post(
            "/api/chat/message",
            headers=session_headers,
            json={
                "message": "תנתחי אילו כללים בלתי אפשריים בפני עצמם ותציעי את קבוצת השינויים הקטנה ביותר. אל תשני שום כלל בלי אישור שלי."
            },
        )

    assert response.status_code == 200
    assert response.json()["steps"] == [
        {"tool": "analyze_rule_feasibility", "ok": True},
        {"tool": "get_active_rules", "ok": True},
    ]
    assert '"independent_rule_feasibility"' in seen["payload"]
    assert '"students_in_group"' in seen["payload"]
    assert '"minimal_independent_relaxation"' in seen["payload"]
    assert '"authoritative_active_rules"' in seen["payload"]
    assert seen["tools"] == []
    assert "אין להשתמש ב'אולי'" in seen["system_prompt"]


def test_size_imbalance_prefetches_evidence_but_llm_writes_the_answer(client, solved_headers):
    seen = {}
    model_answer = "הפער מותר לפי הכלל הנוכחי. בדקתי גם חלוקה הדוקה יותר, והיא אפשרית; השאלה היא אם שוויון בגודל חשוב לך יותר מהפשרה שנמדדה במדדים האחרים."

    def fake_model(system_prompt, messages, tools):
        seen["system_prompt"] = system_prompt
        seen["messages"] = messages
        seen["tools"] = tools
        return ChatCompletion(text=model_answer, tool_calls=[], raw_message={"role": "assistant", "content": model_answer})

    trial = {
        "feasible": True,
        "before": {"class_sizes": [13, 12, 12, 12, 12, 11], "size_spread": 2, "academic_spread": 8},
        "after": {"class_sizes": [12, 12, 12, 12, 12, 12], "size_spread": 0, "academic_spread": 9},
        "deltas": {"size_spread": -2, "academic_spread": 1},
        "caveat": "trial",
    }
    move_options = {
        "before": trial["before"],
        "checked_direct_moves": 12,
        "safe_direct_moves_found": 1,
        "candidates": [
            {
                "student": "STUDENT_001",
                "from_class": 1,
                "to_class": 6,
                "after": trial["after"],
                "deltas": {"size_spread": -2, "academic_spread": 0, "mutual_pct": 0.0, "two_friends_pct": 0.0},
            }
        ],
    }

    def fake_simulation(name, _args, _sess):
        return move_options if name == "find_class_size_balance_moves" else trial

    with (
        patch("backend.routers.chat.execute_simulation_tool", side_effect=fake_simulation),
        patch("backend.llm.agent.chat_completion", side_effect=fake_model),
    ):
        resp = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": "Why does one class have 13 students and another 11 students?"},
        )
        followup = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": "Yes, propose the exact size rule you tested and rerun after I approve."},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == model_answer
    assert [step["tool"] for step in body["steps"][:3]] == [
        "analyze_assignment_quality",
        "find_class_size_balance_moves",
        "simulate_capacity_change",
    ]
    payload = seen["messages"][0]["content"]
    assert '"class_sizes": [13, 12, 12, 12, 12, 11]' in payload
    assert '"verified_direct_move_options"' in payload
    assert '"student": "STUDENT_001"' in payload
    assert seen["tools"] == []
    assert "אל תשתמש/י בשפה שיווקית" in seen["system_prompt"]
    assert "דרישות תוכן מחייבות" in seen["system_prompt"]
    assert followup.status_code == 200
    proposal = followup.json()["pending_proposal"]
    assert proposal["kind"] == "modify"
    assert proposal["changes"]["args"]["min"] == len(store.get_or_create(solved_headers["X-Session-Id"]).mapped_df) // 6
    assert proposal["changes"]["args"]["max"] == -(-len(store.get_or_create(solved_headers["X-Session-Id"]).mapped_df) // 6)
    assert proposal["evidence"]["basis"] == "measured_trial"
    confirmed = client.post("/api/chat/confirm", headers=solved_headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["solver_run_requested"] is True


def test_assignment_versions_tool_reports_measured_history(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    out = execute_read_tool("get_assignment_versions", {}, sess)
    assert out["count"] == 1
    assert out["versions"][0]["is_current"] is True
    assert out["versions"][0]["metrics"]["total_students"] == len(sess.mapped_df)
    assert out["versions"][0]["friendship_measurement"]["available"] is False
    assert "not failures" in out["versions"][0]["friendship_measurement"]["note"]


def test_result_suggestions_do_not_offer_friendship_analysis_without_requests(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    labels = [item["label"] for item in _suggested_actions(sess, [])]
    assert "בדיקת בקשות חברות" not in labels


def test_student_explanation_reports_verified_direct_move_blockers(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assignment = sess.adjustment_state.assignment
    student_id, current_class = next(iter(assignment.items()))
    other_id, target_class = next((sid, cls) for sid, cls in assignment.items() if cls != current_class)
    rule = Constraint(
        type="separate",
        hard=True,
        args={"student_a": student_id, "student_b": other_id},
        label_hebrew="שתי התלמידות חייבות להיות בכיתות נפרדות",
        source="chat",
    )
    sess.constraints.append(rule)
    sess.token_map.ensure_all(sess.mapped_df["student_id"].tolist())

    out = execute_read_tool(
        "explain_student_placement",
        {"student": sess.token_map.token_for(student_id)},
        sess,
    )

    target = next(item for item in out["direct_move_checks"] if item["class"] == target_class + 1)
    assert target["direct_move_preserves_hard_rules"] is False
    assert any(blocker["id"] == rule.id for blocker in target["new_blocking_rules"])
    assert all(str(student_id) not in blocker["label_hebrew"] for blocker in target["new_blocking_rules"])
    assert all(str(other_id) not in blocker["label_hebrew"] for blocker in target["new_blocking_rules"])
    assert "only this student moved" in out["explanation_limit"]


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


def test_dataset_columns_distinguishes_source_fields_from_manual_gaps(client, session_headers):
    sess = store.get_or_create(session_headers["X-Session-Id"])
    out = execute_read_tool("get_dataset_columns", {}, sess)
    source_keys = {field["key"] for field in out["source_fields"]}
    manual_keys = {field["key"] for field in out["manual_or_missing_from_source"]}
    assert "first_name" in source_keys
    assert "friend_requests_raw" in manual_keys
    missing_friendships = next(
        item for item in out["manual_or_missing_from_source"] if item["key"] == "friend_requests_raw"
    )
    assert "does not prove that zero students" in missing_friendships["meaning"]
    assert "Never convert an empty generated placeholder" in out["file_summary_rule"]
    assert out["friendship_request_rows"] == 0
    assert out["friendship_data"]["parsed_request_names"] == 0
    assert out["friendship_data"]["ready_for_optimization"] is False
    assert out["validation"]["blocking_errors"] == 0


def test_dataset_columns_reports_resolved_friendship_readiness(client, session_headers):
    sess = store.get_or_create(session_headers["X-Session-Id"])
    first = sess.mapped_df.iloc[0]
    second = sess.mapped_df.iloc[1]
    first_name = f"{second['first_name']} {second['last_name']}"
    second_name = f"{first['first_name']} {first['last_name']}"
    sess.mapped_df.loc[sess.mapped_df.index[0], "friend_requests_raw"] = first_name
    sess.mapped_df.loc[sess.mapped_df.index[1], "friend_requests_raw"] = second_name
    out = execute_read_tool("get_dataset_columns", {}, sess)
    assert out["friendship_data"]["students_with_entries"] == 2
    assert out["friendship_data"]["parsed_request_names"] == 2
    assert out["friendship_data"]["matched_request_edges"] == 2
    assert out["friendship_data"]["mutual_pairs"] == 1
    assert out["friendship_data"]["ready_for_optimization"] is True


def test_student_tokens_are_restored_only_for_the_counselor_display(client, session_headers):
    sess = store.get_or_create(session_headers["X-Session-Id"])
    row = sess.mapped_df.iloc[0]
    token = sess.token_map.token_for(row["student_id"])
    displayed = _display_student_names(f"בדקתי את {token}.", sess)
    assert token not in displayed
    assert str(row["first_name"]) in displayed


def test_why_student_moved_is_grounded_in_two_real_versions(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    row = sess.mapped_df.iloc[0]
    student_id = int(row["student_id"])
    token = sess.token_map.token_for(student_id)
    old_class = sess.adjustment_state.assignment[student_id] + 1
    new_class = 1 if old_class != 1 else 2
    moved = client.post(
        "/api/adjustment/move",
        headers=solved_headers,
        json={"student_id": student_id, "new_class": new_class},
    )
    assert moved.status_code == 200

    evidence = execute_read_tool("compare_student_versions", {"student": token}, sess)
    assert evidence["moved"] is True
    assert evidence["before"]["class"] == old_class
    assert evidence["after"]["class"] == new_class
    assert evidence["before"]["version_number"] + 1 == evidence["after"]["version_number"]
    assert evidence["return_to_previous_class_check"]["available"] is True
    assert "do not record which objective term caused" in evidence["causality_limit"]
    evidence_blob = repr(evidence)
    assert str(row["first_name"]) not in evidence_blob
    assert str(row["last_name"]) not in evidence_blob

    deterministic = _grounded_student_version_explanation(
        [{"tool": "compare_student_versions", "ok": True, "result": evidence}]
    )
    assert f"מכיתה {old_class}" in deterministic
    assert f"לכיתה {new_class}" in deterministic
    assert "הגרסאות אינן מתעדות גורם יחיד" in deterministic

    seen = {}
    grounded_answer = (
        f"{token} עברה מכיתה {old_class} לגרסה החדשה בכיתה {new_class}. "
        "זו תצפית על השינוי; הגרסאות אינן מתעדות גורם יחיד לבחירת המנוע."
    )

    def fake(system_prompt, messages, tools):
        seen["messages"] = messages
        seen["tools"] = tools
        return ChatCompletion(
            text=grounded_answer,
            tool_calls=[],
            raw_message={"role": "assistant", "content": grounded_answer},
        )
    full_name = f"{row['first_name']} {row['last_name']}"
    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        response = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": f"למה {full_name} עברה כיתה בגרסה החדשה?"},
        )
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert full_name in reply
    assert "הגרסאות אינן מתעדות גורם יחיד" in reply
    assert response.json()["steps"] == [{"tool": "compare_student_versions", "ok": True}]
    assert seen["tools"] == []
    assert '"causality_limit"' in seen["messages"][0]["content"]


def test_current_placement_question_uses_focused_evidence_and_measured_alternative(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    row = sess.mapped_df.iloc[0]
    student_id = int(row["student_id"])
    token = sess.token_map.token_for(student_id)
    full_name = f"{row['first_name']} {row['last_name']}"
    assigned_class = sess.adjustment_state.assignment[student_id] + 1
    seen = {}

    def fake(system_prompt, messages, tools):
        seen["messages"] = messages
        seen["tools"] = tools
        answer = (
            f"{token} נמצאת בכיתה {assigned_class}. בדקתי גם חלופה מדודה; אין בתוצאה תיעוד של סיבה יחידה "
            "שבגללה המנוע בחר בכיתה הנוכחית."
        )
        return ChatCompletion(text=answer, tool_calls=[], raw_message={"role": "assistant", "content": answer})

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        response = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": f"למה {full_name} שובצה בכיתה {assigned_class}?"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["steps"][0] == {"tool": "explain_student_placement", "ok": True}
    assert body["steps"][1] == {"tool": "simulate_student_move", "ok": True}
    assert full_name in body["reply"]
    assert f"בכיתה {assigned_class}" in body["reply"]
    assert "אין בתוצאה תיעוד של סיבה יחידה" in body["reply"]
    assert seen["tools"] == []
    assert '"measured_best_alternative_trial"' in seen["messages"][0]["content"]


def test_locked_student_explanation_does_not_invent_other_blockers():
    reply = _grounded_student_explanation(
        [
            {
                "tool": "explain_student_placement",
                "ok": True,
                "result": {
                    "student": "STUDENT_safe",
                    "assigned_class": 2,
                    "locked": True,
                    "friend_requests": {"requested": 0, "placed_together": 0},
                    "direct_move_checks": [
                        {
                            "class": 1,
                            "direct_move_preserves_hard_rules": False,
                            "new_blocking_rules": [{"type": "locked", "label_hebrew": "קיבוע ידני פעיל"}],
                        }
                    ],
                },
            }
        ]
    )
    assert "הקיבוע הוא הסיבה המאומתת" in reply
    assert "לא נמצא כלל חובה אחר" in reply
    assert "לא הוזנו עבורה בקשות חברות" in reply


def test_multi_option_summary_recommends_the_measured_best_version(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assignment = dict(sess.adjustment_state.assignment)
    common = {
        "class_sizes": [5, 5, 5, 5, 4, 4],
        "violations_count": 0,
        "mutual_satisfied_pct": 70.0,
        "students_with_requests": 28,
    }
    first = SimpleNamespace(
        id="first",
        number=1,
        assignment=assignment,
        run_config={"num_classes": 6},
        metrics={**common, "two_friends_satisfied_pct": 46.0, "objective_value": 261.0},
        constraints=[{"type": "friendship_objective", "active": True, "args": {"weight_two_friends": 3}}],
    )
    second = SimpleNamespace(
        id="second",
        number=2,
        assignment=assignment,
        run_config={"num_classes": 6},
        metrics={**common, "mutual_satisfied_pct": 71.0, "two_friends_satisfied_pct": 36.0, "objective_value": 258.0},
        constraints=[{"type": "friendship_objective", "active": True, "args": {"weight_two_friends": 3}}],
    )
    sess.assignment_versions = [first, second]
    reply = _grounded_solver_comparison(sess, ["first", "second"])
    assert "אני ממליץ על גרסה 1" in reply
    assert "46% עם לפחות שתי חברות" in reply
    assert "אין יתרון איכותי" not in reply


def test_comparison_uses_changed_two_friend_priority_not_raw_objective(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assignment = dict(sess.adjustment_state.assignment)
    common = {"class_sizes": [5, 5, 5, 5, 4, 4], "violations_count": 0, "mutual_satisfied_pct": 70.0, "students_with_requests": 28}
    old = SimpleNamespace(
        id="old",
        number=3,
        assignment=assignment,
        run_config={"num_classes": 6},
        metrics={**common, "two_friends_satisfied_pct": 32.0, "objective_value": 500.0},
        constraints=[{"type": "friendship_objective", "active": True, "args": {"weight_two_friends": 3}}],
    )
    new = SimpleNamespace(
        id="new",
        number=4,
        assignment=assignment,
        run_config={"num_classes": 6},
        metrics={**common, "two_friends_satisfied_pct": 40.0, "objective_value": 100.0},
        constraints=[{"type": "friendship_objective", "active": True, "args": {"weight_two_friends": 5}}],
    )
    sess.assignment_versions = [old, new]
    reply = _grounded_solver_comparison(sess, ["old", "new"], baseline_id="old")
    assert "אני ממליץ על גרסה 4" in reply
    assert "יעד של שתי חברות" in reply
    assert "מ-32% ל-40%" in reply


def test_comparison_does_not_present_missing_friendship_data_as_zero_success(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assignment = dict(sess.adjustment_state.assignment)
    constraints = [{"type": "friendship_objective", "active": True, "args": {"weight_two_friends": 3}}]
    common = {
        "class_sizes": [5, 5, 5, 5, 4, 4],
        "violations_count": 0,
        "mutual_satisfied_pct": 0.0,
        "two_friends_satisfied_pct": 0.0,
        "students_with_requests": 0,
    }
    first = SimpleNamespace(id="first", number=1, assignment=assignment, run_config={"num_classes": 6}, metrics={**common, "objective_value": 10.0}, constraints=constraints)
    second = SimpleNamespace(id="second", number=2, assignment=assignment, run_config={"num_classes": 6}, metrics={**common, "objective_value": 11.0}, constraints=constraints)
    sess.assignment_versions = [first, second]

    reply = _grounded_solver_comparison(sess, ["first", "second"])

    assert "אין נתוני בקשות חברות למדידה" in reply
    assert "0% עם בקשה הדדית" not in reply
    assert "אני ממליץ על גרסה 2" in reply
    assert "הציון הכולל הגבוה ביותר" in reply
    assert "היעד של שתי חברות" not in reply


def test_comparison_never_recommends_a_version_with_mandatory_violations(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assignment = dict(sess.adjustment_state.assignment)
    constraints = [{"type": "friendship_objective", "active": True, "args": {"weight_two_friends": 3}}]
    common = {"class_sizes": [5, 5, 5, 5, 4, 4], "students_with_requests": 28, "mutual_satisfied_pct": 70.0, "two_friends_satisfied_pct": 40.0}
    valid = SimpleNamespace(id="valid", number=1, assignment=assignment, run_config={"num_classes": 6}, metrics={**common, "violations_count": 0, "objective_value": 10.0}, constraints=constraints)
    invalid = SimpleNamespace(id="invalid", number=2, assignment=assignment, run_config={"num_classes": 6}, metrics={**common, "violations_count": 2, "objective_value": 100.0}, constraints=constraints)
    sess.assignment_versions = [valid, invalid]

    reply = _grounded_solver_comparison(sess, ["valid", "invalid"])

    assert "2 חריגות מכללי חובה" in reply
    assert "אני ממליץ על גרסה 1" in reply
    assert "אני ממליץ על גרסה 2" not in reply


def test_comparison_does_not_rank_objective_scores_from_different_configurations(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assignment = dict(sess.adjustment_state.assignment)
    constraints = [{"type": "friendship_objective", "active": True, "args": {"weight_two_friends": 3}}]
    common = {"class_sizes": [5, 5, 5, 5, 4, 4], "students_with_requests": 28, "violations_count": 0, "mutual_satisfied_pct": 70.0, "two_friends_satisfied_pct": 40.0}
    six_classes = SimpleNamespace(id="six", number=1, assignment=assignment, run_config={"num_classes": 6}, metrics={**common, "objective_value": 10.0}, constraints=constraints)
    five_classes = SimpleNamespace(id="five", number=2, assignment=assignment, run_config={"num_classes": 5}, metrics={**common, "objective_value": 100.0}, constraints=constraints)
    sess.assignment_versions = [six_classes, five_classes]

    reply = _grounded_solver_comparison(sess, ["six", "five"])

    assert "הציון הכולל שלהן אינו בר-השוואה" in reply
    assert "אני ממליץ על גרסה" not in reply


def test_comparison_treats_alternative_seeds_as_the_same_user_configuration(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assignment = dict(sess.adjustment_state.assignment)
    constraints = [{"type": "friendship_objective", "active": True, "args": {"weight_two_friends": 3}}]
    common = {"class_sizes": [5, 5, 5, 5, 4, 4], "students_with_requests": 28, "violations_count": 0, "mutual_satisfied_pct": 70.0, "two_friends_satisfied_pct": 40.0}
    first = SimpleNamespace(id="first", number=1, assignment=assignment, run_config={"num_classes": 6, "random_seed": 42, "time_limit_seconds": 30}, metrics={**common, "objective_value": 10.0}, constraints=constraints)
    second = SimpleNamespace(id="second", number=2, assignment=assignment, run_config={"num_classes": 6, "random_seed": 43, "time_limit_seconds": 60}, metrics={**common, "objective_value": 11.0}, constraints=constraints)
    sess.assignment_versions = [first, second]

    reply = _grounded_solver_comparison(sess, ["first", "second"])

    assert "אני ממליץ על גרסה 2" in reply
    assert "הציון הכולל שלהן אינו בר-השוואה" not in reply


def test_measured_friendship_change_becomes_a_real_confirmation_card(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    objective = next(c for c in sess.constraints if c.type == "friendship_objective")
    result = _proposal_from_friendship_simulation(
        "כן, תציעי את השינוי שבדקת",
        [
            {
                "tool": "simulate_friendship_priority",
                "ok": True,
                "args": {"constraint_id": objective.id, "weight_two_friends": 5},
                "result": {
                    "feasible": True,
                    "before": {"two_friends_pct": 31.9, "mutual_pct": 70.8},
                    "after": {"two_friends_pct": 43.1, "mutual_pct": 66.7},
                },
            }
        ],
        sess,
    )
    proposal, summary = result
    assert proposal.kind == "modify"
    assert proposal.changes["args"]["weight_two_friends"] == 5
    assert proposal.evidence["after"]["two_friends_pct"] == 43.1
    assert "אף כלל חובה לא ישתנה" in summary


def test_higher_two_friend_request_rejects_a_lower_tested_weight(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    objective = next(c for c in sess.constraints if c.type == "friendship_objective")
    current = float(objective.args["weight_two_friends"])
    result = _proposal_from_friendship_simulation(
        "תציעי יותר חשיבות ליעד של לפחות שתי חברות",
        [
            {
                "tool": "simulate_friendship_priority",
                "ok": True,
                "args": {"constraint_id": objective.id, "weight_two_friends": max(0, current - 1)},
                "result": {
                    "feasible": True,
                    "before": {"two_friends_pct": 31.9, "mutual_pct": 70.8},
                    "after": {"two_friends_pct": 6.9, "mutual_pct": 33.3},
                },
            }
        ],
        sess,
    )
    assert result is None


def test_bad_tool_arguments_come_back_as_data_not_an_exception(client, solved_headers):
    """A model that calls a tool wrong should get a message it can recover
    from, not abort the counselor's whole turn."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assert execute_read_tool("get_class_composition", {"class_number": 999}, sess)["error"] == "no_such_class"
    assert execute_read_tool("explain_student_placement", {"student": "STUDENT_nope"}, sess)["error"] == "unknown_student_token"
    assert execute_read_tool("get_class_composition", {}, sess)["error"] == "bad_arguments"
    assert execute_read_tool("no_such_tool", {}, sess)["error"] == "unknown_tool"


def test_approved_student_data_edit_updates_project_copy_and_preserves_source_workbook(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    row = sess.mapped_df.iloc[0]
    student_id = int(row["student_id"])
    token = sess.token_map.token_for(student_id)
    old_level = str(row["academic_level"])
    new_level = next(level for level in ("מצטיינת", "בינונית", "חלשה") if level != old_level)
    raw_column = sess.col_mapping.mapping["academic_level"]
    raw_before = sess.loaded_wb.raw_df.loc[sess.mapped_df.index[0], raw_column]

    proposal, _summary = _build_proposal(
        "propose_student_data_edit",
        {
            "student": token,
            "field": "academic_level",
            "value": new_level,
            "rerun_after": False,
            "rationale_hebrew": "לתקן את רמת ההישגים לפי המידע המעודכן",
        },
        sess,
        user_message=f"רמת ההישגים שלה צריכה להיות {new_level}",
    )
    assert proposal.kind == "data_action"
    assert proposal.action == "edit_student_data"
    sess.pending_proposal = proposal

    confirmed = client.post("/api/chat/confirm", headers=solved_headers)

    assert confirmed.status_code == 200
    assert sess.mapped_df.loc[sess.mapped_df["student_id"] == student_id, "academic_level"].iloc[0] == new_level
    assert sess.student_data_edits[student_id]["academic_level"] == new_level
    assert sess.loaded_wb.raw_df.loc[sess.mapped_df.index[0], raw_column] == raw_before
    assert sess.opt_result is None and sess.adjustment_state is None
    record = execute_read_tool("get_student_record", {"student": token}, sess)
    assert record["editable_values"]["academic_level"]["value"] == new_level
    assert record["editable_values"]["academic_level"]["edited_in_project"] is True
    api_row = next(
        item
        for item in client.get("/api/students", headers=solved_headers).json()["rows"]
        if int(item["student_id"]) == student_id
    )
    assert api_row["_project_edited_fields"] == ["academic_level"]


def test_sensitive_student_data_edit_requires_explicit_category_in_user_message(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    student_id = int(sess.mapped_df.iloc[0]["student_id"])
    token = sess.token_map.token_for(student_id)

    with pytest.raises(ToolArgumentError, match="sensitive category"):
        _build_proposal(
            "propose_student_data_edit",
            {
                "student": token,
                "field": "inclusion",
                "value": True,
                "rationale_hebrew": "לעדכן נתון חסר",
            },
            sess,
            user_message="תתקן את הנתון שלה לפי מה שנראה לך",
        )

    proposal, _summary = _build_proposal(
        "propose_student_data_edit",
        {
            "student": token,
            "field": "inclusion",
            "value": True,
            "rationale_hebrew": "היועצת אישרה שהתלמידה בשילוב",
        },
        sess,
        user_message="התלמידה הזאת בשילוב, תעדכן בבקשה",
    )
    assert proposal.kind == "data_action"


def test_conversation_inspects_record_before_proposing_data_correction(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    row = sess.mapped_df.iloc[0]
    student_id = int(row["student_id"])
    token = sess.token_map.token_for(student_id)
    full_name = f"{row['first_name']} {row['last_name']}"
    old_level = str(row["academic_level"])
    new_level = next(level for level in ("מצטיינת", "בינונית", "חלשה") if level != old_level)
    calls = 0

    def fake(system_prompt, messages, tools):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ChatCompletion(
                text=None,
                tool_calls=[ToolCall(id="read", name="get_student_record", arguments={"student": token})],
                raw_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "read", "type": "function", "function": {"name": "get_student_record", "arguments": "{}"}}],
                },
            )
        return ChatCompletion(
            text=None,
            tool_calls=[
                ToolCall(
                    id="edit",
                    name="propose_student_data_edit",
                    arguments={
                        "student": token,
                        "field": "academic_level",
                        "value": new_level,
                        "rerun_after": True,
                        "rationale_hebrew": "לעדכן את רמת ההישגים לפי תיקון היועצת",
                    },
                )
            ],
            raw_message={
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "edit", "type": "function", "function": {"name": "propose_student_data_edit", "arguments": "{}"}}],
            },
        )

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        response = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": f"תעדכן את רמת ההישגים של {full_name} ל{new_level} ואז תריץ שוב"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["steps"] == [{"tool": "get_student_record", "ok": True}]
    assert body["pending_proposal"]["kind"] == "data_action"
    assert body["pending_proposal"]["action"] == "edit_student_data"
    assert body["pending_proposal"]["action_args"]["rerun_after"] is True
    assert sess.mapped_df.loc[sess.mapped_df["student_id"] == student_id, "academic_level"].iloc[0] == old_level


def test_data_quality_analysis_returns_tokens_not_student_names(client, solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    first = sess.mapped_df.iloc[0]
    sess.mapped_df.loc[sess.mapped_df.index[0], "academic_level"] = "ערך לא מוכר"

    out = execute_read_tool("analyze_data_quality", {}, sess)

    assert out["warnings"] >= 1
    issue = next(item for item in out["issues"] if item["category"] == "ערכים לא תקינים")
    assert sess.token_map.token_for(int(first["student_id"])) in issue["affected_students"]
    serialized = json.dumps(out, ensure_ascii=False)
    assert str(first["first_name"]) not in serialized
    assert "never invent" in out["safety"]


def test_file_analysis_prefetches_structure_and_quality_before_llm_reasoning(client, solved_headers):
    seen = {}

    def fake(system_prompt, messages, tools):
        seen["payload"] = messages[0]["content"]
        seen["tools"] = tools
        answer = "בדקתי את הקובץ עצמו. אין שגיאות חוסמות; יש אזהרות נתונים שדורשות בדיקה ממוקדת."
        return ChatCompletion(text=answer, tool_calls=[], raw_message={"role": "assistant", "content": answer})

    with patch("backend.llm.agent.chat_completion", side_effect=fake):
        response = client.post(
            "/api/chat/message",
            headers=solved_headers,
            json={"message": "תנתח את קובץ האקסל ותגיד לי מה חסר או צריך לתקן"},
        )

    assert response.status_code == 200
    assert response.json()["steps"] == [
        {"tool": "analyze_data_quality", "ok": True},
        {"tool": "get_dataset_columns", "ok": True},
    ]
    assert seen["tools"] == []
    assert '"data_quality"' in seen["payload"]
    assert '"dataset_structure"' in seen["payload"]


def test_active_rules_expose_numeric_bounds_not_just_labels(client, session_headers):
    """The old constraints context block only carried label_hebrew, so the
    model could not see that the size rule permits a range."""
    sess = store.get_or_create(session_headers["X-Session-Id"])
    out = execute_read_tool("get_active_rules", {}, sess)
    assert out["count"] > 0
    capacity = [r for r in out["rules"] if r["type"] == "capacity"]
    assert capacity, "expected the built-in capacity rules"
    assert any("min" in r or "max" in r for r in capacity)


def test_active_rules_hide_student_ids_embedded_in_relationship_labels(client, session_headers):
    sess = store.get_or_create(session_headers["X-Session-Id"])
    first_id, second_id = [int(value) for value in sess.mapped_df["student_id"].iloc[:2]]
    sess.constraints.append(
        Constraint(
            type="together",
            hard=True,
            args={"student_a": first_id, "student_b": second_id},
            label_hebrew=f"Keep students {first_id} and {second_id} together",
            source="chat",
        )
    )

    out = execute_read_tool("get_active_rules", {}, sess)
    relationship = next(rule for rule in out["rules"] if rule["type"] == "together")
    assert relationship["label_hebrew"] == "כלל צירוף בין תלמידות"
    assert str(first_id) not in relationship["label_hebrew"]
    assert str(second_id) not in relationship["label_hebrew"]
