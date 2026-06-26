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
from app.storage import (
    add_message,
    create_user,
    ensure_user,
    get_history,
    get_recent_messages,
    init_db,
)

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
    thread_id: str = Form(""),
) -> RecommendationResponse:
    uid = uid.strip() or create_user()
    thread_id = thread_id.strip() or uid
    if not request.strip() and image is None:
        raise HTTPException(status_code=400, detail="request or image is required")

    ensure_user(uid)
    image_bytes = await image.read() if image else None
    image_mime = image.content_type if image else ""
    history = get_recent_messages(thread_id)
    preflight = preflight_request(
        request, has_upload=image is not None, budget=budget, history=history
    )
    if preflight.action == "refuse":
        return _guardrail_response(uid=uid, budget=budget, preflight=preflight)

    user_message = _user_message(request, image is not None, budget)
    if preflight.action == "clarify":
        add_message(thread_id, uid, "user", user_message)
        add_message(thread_id, uid, "assistant", preflight.message)
        return _guardrail_response(uid=uid, budget=budget, preflight=preflight)

    add_message(thread_id, uid, "user", user_message)
    response = await run_furniture_assistant(
        uid=uid,
        request=request,
        budget=budget,
        image_bytes=image_bytes,
        image_mime=image_mime,
        thread_id=thread_id,
        history=history,
    )
    add_message(thread_id, uid, "assistant", response.text)
    return response


@app.post("/api/recommend/stream")
async def recommend_stream(
    uid: str = Form(""),
    request: str = Form(""),
    budget: float | None = Form(None),
    image: UploadFile | None = File(None),
    thread_id: str = Form(""),
) -> StreamingResponse:
    uid = uid.strip() or create_user()
    thread_id = thread_id.strip() or uid
    if not request.strip() and image is None:
        raise HTTPException(status_code=400, detail="request or image is required")

    ensure_user(uid)
    image_bytes = await image.read() if image else None
    image_mime = image.content_type if image else ""
    history = get_recent_messages(thread_id)
    preflight = preflight_request(
        request, has_upload=image is not None, budget=budget, history=history
    )
    user_message = _user_message(request, image is not None, budget)

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            if preflight.action == "refuse":
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
            if preflight.action == "clarify":
                add_message(thread_id, uid, "user", user_message)
                add_message(thread_id, uid, "assistant", preflight.message)
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
            add_message(thread_id, uid, "user", user_message)
            assistant_text = ""
            async for event in stream_furniture_assistant(
                uid=uid,
                request=request,
                budget=budget,
                image_bytes=image_bytes,
                image_mime=image_mime,
                thread_id=thread_id,
                history=history,
            ):
                if event.get("type") == "summary":
                    assistant_text = event.get("text", "") or assistant_text
                elif event.get("type") == "final":
                    assistant_text = (event.get("data") or {}).get("text", "") or assistant_text
                yield _sse(event)
            if assistant_text:
                add_message(thread_id, uid, "assistant", assistant_text)
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


def _user_message(request: str, has_image: bool, budget: float | None = None) -> str:
    text = request.strip()
    if text and has_image:
        base = f"{text}\n[附带图片/户型图]"
    elif text:
        base = text
    elif has_image:
        base = "[用户上传了图片/户型图]"
    else:
        base = ""
    if budget is not None:
        base = f"{base} [预算:{budget:g}]".strip()
    return base


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
