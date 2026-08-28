from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header

from src.data_requirements import summarize
from src.optimizer import SolverConfig

from ..schemas import RunConfigModel
from ..session_store import store
from ..solver_inputs import sync_class_size_bounds

router = APIRouter()


@router.get("/api/run-config")
def get_run_config(x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    return asdict(sess.run_config)


@router.get("/api/result-state")
def get_result_state(x_session_id: str = Header(...)):
    """Authoritative freshness metadata for the current assignment."""
    return store.get_or_create(x_session_id).result_state()


@router.get("/api/data-requirements")
def get_data_requirements(x_session_id: str = Header(...)):
    """The columns agreed during planning, checked against whatever workbook
    has since been loaded. This is the counselor's Excel checklist."""
    sess = store.get_or_create(x_session_id)
    out = summarize(sess.data_requirements, sess.dataset_schema)
    out["has_dataset"] = sess.mapped_df is not None
    return out


@router.delete("/api/data-requirements/{requirement_id}")
def delete_data_requirement(requirement_id: str, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    before = len(sess.data_requirements)
    sess.data_requirements = [r for r in sess.data_requirements if r.id != requirement_id]
    store.save(sess)
    return {"removed": before - len(sess.data_requirements) > 0}


@router.post("/api/run-config")
def set_run_config(cfg: RunConfigModel, x_session_id: str = Header(...)):
    sess = store.get_or_create(x_session_id)
    next_config = SolverConfig(**cfg.model_dump())
    changed = asdict(sess.run_config) != asdict(next_config)
    sess.run_config = next_config
    # num_classes may have just changed -- keep the class-size rule's bounds
    # in sync rather than leaving them stale until the next re-map.
    if sess.mapped_df is not None:
        sync_class_size_bounds(sess, sess.mapped_df)
    if changed:
        sess.mark_inputs_changed()
    store.save(sess)
    return {**asdict(sess.run_config), "result_state": sess.result_state()}
