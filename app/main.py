from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent import close_furniture_graph, run_furniture_assistant, stream_furniture_assistant
from app.models import HistoryRecord, RecommendationResponse, UserCreateResponse
from app.storage import create_user, ensure_user, get_history, init_db

app = FastAPI(title="Furniture Choice Assistant", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.on_event("shutdown")
async def shutdown() -> None:
    await close_furniture_graph()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.post("/api/register", response_model=UserCreateResponse)
async def register() -> UserCreateResponse:
    return UserCreateResponse(uid=create_user())


@app.post("/api/recommend", response_model=RecommendationResponse)
async def recommend(
    uid: str = Form(""),
    request: str = Form(""),
    budget: float | None = Form(None),
    image: UploadFile | None = File(None),
) -> RecommendationResponse:
    uid = uid.strip() or create_user()
    if not request.strip() and image is None:
        raise HTTPException(status_code=400, detail="request or image is required")

    ensure_user(uid)
    image_bytes = await image.read() if image else None
    image_mime = image.content_type if image else ""
    return await run_furniture_assistant(
        uid=uid,
        request=request,
        budget=budget,
        image_bytes=image_bytes,
        image_mime=image_mime,
    )


@app.post("/api/recommend/stream")
async def recommend_stream(
    uid: str = Form(""),
    request: str = Form(""),
    budget: float | None = Form(None),
    image: UploadFile | None = File(None),
) -> StreamingResponse:
    uid = uid.strip() or create_user()
    if not request.strip() and image is None:
        raise HTTPException(status_code=400, detail="request or image is required")

    ensure_user(uid)
    image_bytes = await image.read() if image else None
    image_mime = image.content_type if image else ""

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            async for event in stream_furniture_assistant(
                uid=uid,
                request=request,
                budget=budget,
                image_bytes=image_bytes,
                image_mime=image_mime,
            ):
                yield _sse(event)
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/history/{uid}", response_model=list[HistoryRecord])
async def history(uid: str) -> list[HistoryRecord]:
    return [HistoryRecord(**row) for row in get_history(uid)]


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
