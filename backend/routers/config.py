from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header

from src.optimizer import SolverConfig

from ..schemas import RunConfigModel
from ..session_store import store
from ..solver_inputs import sync_class_size_bounds

router = APIRouter()


@router.get("/api/run-config")
def get_run_config(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return asdict(sess.run_config)


@router.post("/api/run-config")
def set_run_config(cfg: RunConfigModel, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    sess.run_config = SolverConfig(**cfg.model_dump())
    # num_classes may have just changed -- keep the class-size rule's bounds
    # in sync rather than leaving them stale until the next re-map.
    if sess.mapped_df is not None:
        sync_class_size_bounds(sess, sess.mapped_df)
    store.save(sess)
    return asdict(sess.run_config)
