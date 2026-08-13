"""FastAPI app wrapping the existing src/ class-assignment logic.

Run with: uvicorn backend.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .routers import chat, config, export, optimize, validation, workbook
from .session_store import store

app = FastAPI(title="שיבוץ תלמידות - API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/session")
async def create_session(x_session_id: str = Header(...)):
    store.reset(x_session_id)
    return {"session_id": x_session_id}


@app.get("/api/health")
async def health():
    return {"ok": True}


app.include_router(workbook.router)
app.include_router(validation.router)
app.include_router(config.router)
app.include_router(optimize.router)
app.include_router(export.router)
app.include_router(chat.router)
