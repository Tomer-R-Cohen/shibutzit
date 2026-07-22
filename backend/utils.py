"""Small helpers shared across routers."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def df_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe records (NaN/NaT -> None, numpy -> py)."""
    if df is None or df.empty:
        return []
    clean = df.copy()
    clean = clean.where(pd.notnull(clean), None)
    records = clean.to_dict(orient="records")
    return [_clean_record(r) for r in records]


def _clean_record(rec: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in rec.items():
        out[str(k)] = _clean_value(v)
    return out


def _clean_value(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if f != f else f  # NaN check
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, dict):
        return {str(kk): _clean_value(vv) for kk, vv in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean_value(x) for x in v]
    if isinstance(v, float) and v != v:
        return None
    return v


def require(session_attr: Any, message: str):
    from fastapi import HTTPException

    if session_attr is None:
        raise HTTPException(status_code=409, detail=message)
    return session_attr
