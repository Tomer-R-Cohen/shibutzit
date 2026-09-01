"""What-if tools: run the real solver on a hypothetical, change nothing.

The property that matters most here is the negative one -- a simulation must
leave the session exactly as it found it. If that ever breaks, the agent
silently rewrites the counselor's assignment while "just checking", which is
worse than the guessing problem this whole feature set replaced.
"""

import copy
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.llm.provider import ChatCompletion, ToolCall
from backend.llm.simulation_tools import execute_simulation_tool
from backend.session_store import store


@pytest.fixture
def client():
    return TestClient(backend_main.app)


@pytest.fixture
def solved_headers(client):
    session_id = "chat-sim-test-session"
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
    cfg = client.get("/api/run-config", headers=headers).json()
    cfg["time_limit_seconds"] = 5
    client.post("/api/run-config", headers=headers, json=cfg)
    assert client.post("/api/optimize", headers=headers).json()["is_feasible"] is True
    yield headers
    store.reset(session_id)


def _size_rule(sess):
    return next(c for c in sess.constraints if c.type == "capacity" and c.args.get("group", {}).get("kind") == "all")


def test_simulation_does_not_touch_the_session(solved_headers):
    """The whole safety story for what-ifs in one assertion."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    rule = _size_rule(sess)

    before_assignment = dict(sess.adjustment_state.assignment)
    before_constraints = copy.deepcopy(sess.constraints)
    before_num_classes = sess.run_config.num_classes
    before_time_limit = sess.run_config.time_limit_seconds

    execute_simulation_tool("simulate_capacity_change", {"constraint_id": rule.id, "min": 35, "max": 36}, sess)
    execute_simulation_tool("simulate_class_count", {"num_classes": 7}, sess)

    assert sess.adjustment_state.assignment == before_assignment
    assert [c.args for c in sess.constraints] == [c.args for c in before_constraints]
    assert [(c.hard, c.active) for c in sess.constraints] == [(c.hard, c.active) for c in before_constraints]
    assert sess.run_config.num_classes == before_num_classes
    assert sess.run_config.time_limit_seconds == before_time_limit


def test_tightening_the_size_rule_reports_a_real_before_and_after(solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    rule = _size_rule(sess)

    out = execute_simulation_tool("simulate_capacity_change", {"constraint_id": rule.id, "min": 36, "max": 37}, sess)

    assert "error" not in out, out
    assert out["feasible"] is True
    assert "before" in out and "after" in out and "deltas" in out
    assert len(out["after"]["class_sizes"]) == sess.run_config.num_classes
    assert sum(out["after"]["class_sizes"]) == len(sess.mapped_df)
    # The point of the change: every class now sits inside the tighter band.
    assert all(36 <= s <= 37 for s in out["after"]["class_sizes"])
    assert out["after"]["size_spread"] <= out["before"]["size_spread"]
    assert "caveat" in out, "a short-budget trial must always say so"


def test_impossible_change_is_reported_as_an_answer_not_an_error(solved_headers):
    """An infeasible what-if is useful information, not a failure."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    rule = _size_rule(sess)
    # 217 students cannot fit into 6 classes of at most 10.
    out = execute_simulation_tool("simulate_capacity_change", {"constraint_id": rule.id, "min": 1, "max": 10}, sess)

    assert "error" not in out
    assert out["feasible"] is False
    assert out["solver_status"]
    assert "detail" in out


def test_arithmetically_impossible_change_names_the_actual_reason(solved_headers):
    """217 students in 6 classes capped at 36 is 216 seats. The answer must
    be that multiplication, not CP-SAT's "every capacity rule is implicated"
    assumption set -- which is technically true and tells the counselor
    nothing."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    rule = _size_rule(sess)
    out = execute_simulation_tool("simulate_capacity_change", {"constraint_id": rule.id, "min": 35, "max": 36}, sess)

    assert out["feasible"] is False
    assert out["solver_status"] == "INFEASIBLE_BY_COUNTING"
    assert "216" in out["detail"] and "217" in out["detail"], out["detail"]
    assert "conflicting_rules" not in out, "a counting failure must not blame unrelated rules"


def test_counting_check_catches_a_category_minimum(solved_headers):
    """21 Ethiopian-origin students, 3 required per class: 8 classes needs
    24. That should be reported as the specific shortfall."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    out = execute_simulation_tool("simulate_class_count", {"num_classes": 8}, sess)

    assert out["feasible"] is False
    assert out["solver_status"] == "INFEASIBLE_BY_COUNTING"
    assert "24" in out["detail"] and "21" in out["detail"], out["detail"]


def test_class_count_simulation_rescales_the_size_rule(solved_headers):
    """Changing class count without recomputing the size bounds would make
    the trial fail for a reason nobody asked about -- 7 classes of 35-38
    cannot hold 217 students."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    out = execute_simulation_tool("simulate_class_count", {"num_classes": 7}, sess)

    assert "error" not in out, out
    assert out["feasible"] is True, "7 classes should be solvable once the size rule is rescaled"
    assert len(out["after"]["class_sizes"]) == 7
    assert sum(out["after"]["class_sizes"]) == len(sess.mapped_df)
    assert all(29 <= s <= 32 for s in out["after"]["class_sizes"]), out["after"]["class_sizes"]


def test_category_minimums_are_not_quietly_relaxed(solved_headers):
    """With 21 Ethiopian-origin students and a 3-per-class minimum, 8 classes
    would need 24. That is genuinely impossible, and the trial must say so
    rather than loosening the rule to manufacture a success."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    out = execute_simulation_tool("simulate_class_count", {"num_classes": 8}, sess)

    assert "error" not in out
    assert out["feasible"] is False
    # Reported either by the counting check or by the solver, but reported.
    assert out.get("detail") or out.get("conflicting_rules")


def test_rescaled_rule_labels_match_the_bounds_actually_used(solved_headers):
    """A rule's Hebrew label is what surfaces in `conflicting_rules` and in
    the counting-check detail, i.e. what the model quotes to the counselor.
    Changing bounds without relabelling means confidently reporting numbers
    the trial never used."""
    from backend.llm.simulation_tools import _relabel

    sess = store.get_or_create(solved_headers["X-Session-Id"])
    rule = copy.deepcopy(_size_rule(sess))
    assert "35" in rule.label_hebrew and "38" in rule.label_hebrew

    rule.args["min"], rule.args["max"] = 26, 29
    _relabel(rule)

    assert "26" in rule.label_hebrew and "29" in rule.label_hebrew
    assert "35" not in rule.label_hebrew, f"stale label: {rule.label_hebrew}"


def test_bad_simulation_arguments_come_back_as_data(solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    rule = _size_rule(sess)
    assert execute_simulation_tool("simulate_capacity_change", {"constraint_id": "nope", "min": 1}, sess)["error"] == "unknown_constraint"
    assert execute_simulation_tool("simulate_capacity_change", {"constraint_id": rule.id}, sess)["error"] == "bad_arguments"
    assert execute_simulation_tool("simulate_capacity_change", {"constraint_id": rule.id, "min": 40, "max": 30}, sess)["error"] == "bad_arguments"
    assert execute_simulation_tool("simulate_class_count", {"num_classes": 99}, sess)["error"] == "bad_arguments"
    assert execute_simulation_tool("simulate_rule_toggle", {"constraint_id": rule.id}, sess)["error"] == "bad_arguments"


def test_friendship_priority_simulation_is_real_and_non_mutating(solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    objective = next(c for c in sess.constraints if c.type == "friendship_objective")
    before = copy.deepcopy(objective.args)
    out = execute_simulation_tool(
        "simulate_friendship_priority",
        {
            "constraint_id": objective.id,
            "weight_two_friends": int(objective.args.get("weight_two_friends", 0)) + 2,
        },
        sess,
    )
    assert "error" not in out, out
    assert out["feasible"] is True
    assert "before" in out and "after" in out and "deltas" in out
    assert objective.args == before, "a friendship trial must not change the active priorities"


def test_class_size_move_search_returns_only_measured_safe_moves_and_does_not_mutate(solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assignment_before = dict(sess.adjustment_state.assignment)

    out = execute_simulation_tool("find_class_size_balance_moves", {}, sess)

    assert "error" not in out, out
    assert sess.adjustment_state.assignment == assignment_before
    assert out["checked_direct_moves"] >= out["safe_direct_moves_found"]
    for candidate in out["candidates"]:
        assert candidate["after"]["violations"] == 0
        assert candidate["from_class"] in out["largest_classes"]
        assert candidate["to_class"] in out["smallest_classes"]
        assert candidate["deltas"]["size_spread"] < 0


def test_student_move_simulation_measures_direct_move_and_safe_swaps_without_mutating(solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    assignment_before = dict(sess.adjustment_state.assignment)
    student_id, source_class = next(iter(assignment_before.items()))
    token = sess.token_map.token_for(student_id)
    target_class = ((source_class + 1) % sess.run_config.num_classes) + 1

    out = execute_simulation_tool(
        "simulate_student_move",
        {"student": token, "class_number": target_class},
        sess,
    )

    assert "error" not in out, out
    assert sess.adjustment_state.assignment == assignment_before
    assert out["student"] == token
    assert out["requested_move"] == {"from_class": source_class + 1, "to_class": target_class}
    assert "mandatory_violations_after" in out["direct_move"]
    assert "student_outcome_deltas" in out["direct_move"]
    for candidate in out["compensating_swap_search"]["best_candidates"]:
        assert candidate["after"]["violations"] == 0
        assert "requested_student_deltas" in candidate
        assert "swap_partner_deltas" in candidate


def test_balance_priority_simulation_measures_the_target_and_is_non_mutating(solved_headers):
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    objective = next(c for c in sess.constraints if c.type == "balance")
    before = copy.deepcopy(objective.args)
    out = execute_simulation_tool(
        "simulate_balance_priority",
        {"constraint_id": objective.id, "weight": float(objective.args.get("weight", 1)) + 2},
        sess,
    )

    assert "error" not in out, out
    assert out["feasible"] is True
    assert out["targeted_balance"]["before"]["constraint_id"] == objective.id
    assert out["targeted_balance"]["after"]["constraint_id"] == objective.id
    assert "total_spread" in out["targeted_balance"]["before"]
    assert objective.args == before, "a balance trial must not change the active priority"


def test_simulation_budget_caps_solver_calls_per_turn(client, solved_headers):
    """Each simulation is a real solve the counselor waits through, so a
    model that wants five of them must be told no."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    rule_id = _size_rule(sess).id
    seen = []

    def always_simulate(system_prompt, messages, tools):
        seen.append(1)
        if not tools:
            return ChatCompletion(text="סיימתי לבדוק.", tool_calls=[], raw_message={"role": "assistant", "content": "x"})
        cid = f"c{len(seen)}"
        return ChatCompletion(
            text=None,
            tool_calls=[ToolCall(id=cid, name="simulate_capacity_change", arguments={"constraint_id": rule_id, "max": 37})],
            raw_message={
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": cid, "type": "function", "function": {"name": "simulate_capacity_change", "arguments": "{}"}}],
            },
        )

    started = time.time()
    with patch("backend.llm.agent.chat_completion", side_effect=always_simulate):
        resp = client.post("/api/chat/message", headers=solved_headers, json={"message": "תבדוק הכל"})
    elapsed = time.time() - started

    assert resp.status_code == 200
    steps = resp.json()["steps"]
    ran = [s for s in steps if s["ok"]]
    refused = [s for s in steps if not s["ok"]]
    assert len(ran) == 2, "exactly the per-turn simulation budget should have run"
    assert refused, "further attempts must be refused, not silently run"
    # Six unbudgeted 10s solves would be ~60s; two is the point of the cap.
    assert elapsed < 45, f"turn took {elapsed:.0f}s -- the budget is not capping solver time"


def test_simulation_tool_is_not_treated_as_a_write(client, solved_headers):
    """A simulate_* call must keep the loop running, not end the turn as a
    confirm card the way propose_* does."""
    sess = store.get_or_create(solved_headers["X-Session-Id"])
    rule_id = _size_rule(sess).id
    calls = []

    def sim_then_answer(system_prompt, messages, tools):
        calls.append(1)
        if len(calls) == 1:
            return ChatCompletion(
                text=None,
                tool_calls=[ToolCall(id="s1", name="simulate_capacity_change", arguments={"constraint_id": rule_id, "min": 36, "max": 37})],
                raw_message={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "s1", "type": "function", "function": {"name": "simulate_capacity_change", "arguments": "{}"}}],
                },
            )
        return ChatCompletion(text="בדקתי, הפער יורד.", tool_calls=[], raw_message={"role": "assistant", "content": "ok"})

    with patch("backend.llm.agent.chat_completion", side_effect=sim_then_answer):
        body = client.post("/api/chat/message", headers=solved_headers, json={"message": "מה אם נהדק?"}).json()

    assert body["pending_proposal"] is None
    assert body["reply"] == "בדקתי, הפער יורד."
    assert body["steps"] == [{"tool": "simulate_capacity_change", "ok": True}]

    assert len(calls) == 2, "the loop must continue after a simulation"
