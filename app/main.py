from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.agent import close_furniture_graph, run_furniture_assistant, stream_furniture_assistant
from app.guardrails import PreflightResult, preflight_request
from app.models import HistoryRecord, RecommendationResponse, UserCreateResponse
from app.pdf_export import build_plan_pdf
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
    preflight = preflight_request(request, has_upload=image is not None)
    if preflight.should_stop:
        return _guardrail_response(uid=uid, budget=budget, preflight=preflight)
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
    preflight = preflight_request(request, has_upload=image is not None)

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            if preflight.should_stop:
                yield _sse(
                    {
                        "type": preflight.action,
                        "message": preflight.message,
                        "data": _guardrail_response(
                            uid=uid,
                            budget=budget,
                            preflight=preflight,
                        ).model_dump(),
                    }
                )
                return
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


@app.post("/api/plan/pdf")
async def plan_pdf(plan: RecommendationResponse) -> Response:
    pdf_bytes = build_plan_pdf(plan)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="furniture-plan.pdf"'},
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _guardrail_response(
    uid: str,
    budget: float | None,
    preflight: PreflightResult,
) -> RecommendationResponse:
    return RecommendationResponse(
        uid=uid,
        text=preflight.message,
        items=[],
        placements=[],
        room_image_url="",
        room_plans=[],
        total=0.0,
        currency="CNY",
        budget=budget,
        preferences={},
        image_notes="",
    )
