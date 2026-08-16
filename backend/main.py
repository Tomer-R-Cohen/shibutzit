"""FastAPI app wrapping the existing src/ class-assignment logic.

Run with: uvicorn backend.main:app --reload
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()  # loads .env from the repo root (or CWD) into process env vars

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .logging_config import setup_logging
from .routers import chat, config, export, optimize, validation, workbook
from .session_store import store

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="שיבוץ תלמידות - API")

_default_origins = "http://localhost:3000"
_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "שגיאת שרת פנימית."})


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
