"""Pydantic request/response models for the FastAPI backend."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class LoadWorkbookRequest(BaseModel):
    use_default: bool = True
    header_row: int = 4
    first_data_row: int = 5
    last_data_row: int = 221


class MappingSetRequest(BaseModel):
    mapping: dict[str, Optional[str]]
    manual_fields: list[str] = []


class ManualEntryUpdateRequest(BaseModel):
    rows: list[dict[str, Any]]


class ApplyManualRequest(BaseModel):
    pass


class RunConfigModel(BaseModel):
    """Run parameters only. Every actual rule (including the built-in
    defaults) lives in the constraint list (/api/constraints), not here --
    see src/constraints.py and backend/solver_inputs.py."""

    num_classes: int = 6
    denominator_all_students: bool = True
    mutual_target_pct: float = 80.0
    two_friends_target_pct: float = 70.0
    time_limit_seconds: float = 60.0
    # Accepted so an existing client can round-trip the object it was given,
    # but never surfaced in the UI -- see SolverConfig.random_seed.
    random_seed: int = 42


class LockingRequest(BaseModel):
    locks: dict[str, int]  # student_id (as string key from JSON) -> class (1-based), 0 = unlocked


class MoveStudentRequest(BaseModel):
    student_id: int
    new_class: int  # 1-based
    locked: Optional[bool] = None


class SelectDecisionOptionRequest(BaseModel):
    option_id: str
    reason: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str
