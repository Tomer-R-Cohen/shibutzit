from unittest.mock import patch

from backend.llm.narration import narrate_infeasibility
from backend.llm.provider import LLMNotConfiguredError
from src.constraints import Constraint


def make_conflicting():
    return [
        Constraint(type="together", hard=True, args={"student_a": 1, "student_b": 2}, label_hebrew="ביחד"),
        Constraint(type="separate", hard=True, args={"student_a": 1, "student_b": 2}, label_hebrew="בנפרד"),
    ]


def test_no_conflicting_constraints_returns_timeout_message():
    text = narrate_infeasibility([])
    assert "הזמן" in text


def test_falls_back_when_llm_not_configured():
    with patch("backend.llm.narration.text_completion", side_effect=LLMNotConfiguredError("no key")):
        text = narrate_infeasibility(make_conflicting())
    assert "ביחד" in text
    assert "בנפרד" in text


def test_falls_back_on_unexpected_error():
    with patch("backend.llm.narration.text_completion", side_effect=RuntimeError("boom")):
        text = narrate_infeasibility(make_conflicting())
    assert "ביחד" in text
    assert "בנפרד" in text


def test_uses_llm_text_when_available():
    with patch("backend.llm.narration.text_completion", return_value="הסבר יפה בעברית.") as mocked:
        text = narrate_infeasibility(make_conflicting())
    mocked.assert_called_once()
    assert text == "הסבר יפה בעברית."


def test_falls_back_when_llm_returns_empty_text():
    with patch("backend.llm.narration.text_completion", return_value="   "):
        text = narrate_infeasibility(make_conflicting())
    assert "ביחד" in text
