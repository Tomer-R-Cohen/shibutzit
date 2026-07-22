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


class SolverConfigModel(BaseModel):
    num_classes: int = 6
    class_size_hard: bool = True
    differential_hard: bool = True
    ethiopian_hard: bool = True
    inclusion_hard: bool = True
    hamar_hard: bool = True
    locked_hard: bool = True
    max_class_size_diff: int = 1
    max_differential_per_class: int = 1
    min_ethiopian_per_class: int = 3
    max_ethiopian_per_class: int = 4
    min_inclusion_per_class: int = 2
    max_inclusion_per_class: int = 2
    min_hamar_per_class: int = 1
    max_hamar_per_class: int = 2
    mutual_target_pct: float = 80.0
    two_friends_target_pct: float = 70.0
    denominator_all_students: bool = True
    weight_mutual: float = 5.0
    weight_two_friends: float = 3.0
    weight_academic_balance: float = 2.0
    weight_school_balance: float = 2.0
    weight_current_class_balance: float = 1.5
    weight_category_balance: float = 1.0
    weight_target_distribution: float = 1.0
    time_limit_seconds: float = 30.0
    random_seed: int = 42


class LockingRequest(BaseModel):
    locks: dict[str, int]  # student_id (as string key from JSON) -> class (1-based), 0 = unlocked


class MoveStudentRequest(BaseModel):
    student_id: int
    new_class: int  # 1-based
    locked: Optional[bool] = None


class ErrorResponse(BaseModel):
    detail: str
