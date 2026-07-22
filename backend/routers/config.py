from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header

from src.optimizer import SolverConfig

from ..schemas import SolverConfigModel
from ..session_store import store

router = APIRouter()


@router.get("/api/config")
async def get_config(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return asdict(sess.solver_config)


@router.post("/api/config")
async def set_config(cfg: SolverConfigModel, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    sess.solver_config = SolverConfig(**cfg.model_dump())
    return asdict(sess.solver_config)
