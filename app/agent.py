from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph

from app.images import generate_room_image
from app.layout import plan_furniture_layout
from app.models import FurnitureItem, FurniturePlacement, RecommendationResponse
from app.prompts import PREFERENCE_PROMPT, RECOMMENDATION_PROMPT, SYSTEM_PROMPT
from app.search import search_ikea_furniture
from app.storage import add_history, get_preferences, update_preferences


class FurnitureState(TypedDict, total=False):
    uid: str
    request: str
    budget: float | None
    image_bytes: bytes | None
    image_mime: str
    image_notes: str
    preferences: dict[str, Any]
    items: list[FurnitureItem]
    placements: list[FurniturePlacement]
    room_image_url: str
    response_text: str
    total: float


def _get_llm():
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0.4)


async def load_user_context(state: FurnitureState) -> FurnitureState:
    state["preferences"] = get_preferences(state["uid"])
    return state


async def understand_image(state: FurnitureState) -> FurnitureState:
    image_bytes = state.get("image_bytes")
    if not image_bytes:
        state["image_notes"] = ""
        return state

    llm = _get_llm()
    if llm is None:
        state["image_notes"] = "用户上传了图片；未配置 OPENAI_API_KEY，暂未进行视觉理解。"
        return state

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    mime = state.get("image_mime") or "image/jpeg"
    message = HumanMessage(
        content=[
            {
                "type": "text",
                "text": "请用中文提取图片中的房间风格、颜色、空间约束、已有家具和可能的搭配需求。",
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_b64}"},
            },
        ]
    )
    result = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT), message])
    state["image_notes"] = str(result.content)
    return state


async def search_candidates(state: FurnitureState) -> FurnitureState:
    query = " ".join(
        part
        for part in [
            state.get("request", ""),
            state.get("image_notes", ""),
            json.dumps(state.get("preferences", {}), ensure_ascii=False),
        ]
        if part
    )
    state["items"] = await search_ikea_furniture(
        query=query,
        budget=state.get("budget"),
        preferences=state.get("preferences", {}),
    )
    return state


async def plan_layout_and_generate_room(state: FurnitureState) -> FurnitureState:
    placements = plan_furniture_layout(
        state.get("items", []),
        state.get("request", ""),
    )
    state["placements"] = placements
    state["room_image_url"] = await generate_room_image(
        items=state.get("items", []),
        placements=placements,
        request=state.get("request", ""),
        image_notes=state.get("image_notes", ""),
    )
    return state


async def generate_recommendation(state: FurnitureState) -> FurnitureState:
    items = state.get("items", [])
    total = round(sum(item.price for item in items), 2)
    state["total"] = total

    llm = _get_llm()
    if llm is None:
        lines = [
            "已根据你的需求生成宜家家具组合建议：",
            "",
            f"空间判断：{_describe_room(state.get('request', ''))}",
            f"搭配方向：{_describe_style(state.get('request', ''), state.get('preferences', {}))}",
            "",
            "摆放方案：",
            *[
                f"- {placement.item_name}: {placement.note}"
                for placement in state.get("placements", [])
            ],
            "",
            "建议购买：",
            *[f"- {item.name}: ${item.price:.2f}，{item.reason}" for item in items],
            "",
            f"预计总金额：${total:.2f}",
        ]
        if state.get("budget") and total > float(state["budget"]):
            lines.append(f"当前组合超出预算 ${total - float(state['budget']):.2f}，建议先保留核心家具。")
        state["response_text"] = "\n".join(lines)
        return state

    prompt = RECOMMENDATION_PROMPT.format(
        uid=state["uid"],
        request=state.get("request", ""),
        budget=state.get("budget"),
        preferences=json.dumps(state.get("preferences", {}), ensure_ascii=False),
        image_notes=state.get("image_notes", ""),
        items=json.dumps([item.model_dump() for item in items], ensure_ascii=False),
        placements=json.dumps(
            [
                placement.model_dump() if hasattr(placement, "model_dump") else placement
                for placement in state.get("placements", [])
            ],
            ensure_ascii=False,
        ),
    )
    result = await llm.ainvoke(
        [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    )
    state["response_text"] = str(result.content)
    return state


async def persist_memory(state: FurnitureState) -> FurnitureState:
    preferences = await _extract_preferences(state)
    update_preferences(state["uid"], preferences)
    add_history(
        uid=state["uid"],
        user_request=state.get("request", ""),
        summary=state.get("response_text", ""),
        total=state.get("total", 0.0),
    )
    state["preferences"] = preferences
    return state


async def _extract_preferences(state: FurnitureState) -> dict[str, Any]:
    existing = state.get("preferences", {})
    llm = _get_llm()
    if llm is None:
        return _simple_preference_update(existing, state.get("request", ""))

    prompt = PREFERENCE_PROMPT.format(
        preferences=json.dumps(existing, ensure_ascii=False),
        request=state.get("request", ""),
        image_notes=state.get("image_notes", ""),
    )
    result = await llm.ainvoke([HumanMessage(content=prompt)])
    try:
        parsed = json.loads(str(result.content))
        return parsed if isinstance(parsed, dict) else existing
    except json.JSONDecodeError:
        return existing


def _simple_preference_update(existing: dict[str, Any], request: str) -> dict[str, Any]:
    updated = dict(existing)
    text = request.lower()
    for style in ["modern", "minimal", "cozy", "北欧", "现代", "极简", "温馨"]:
        if style in text:
            updated["style"] = style
    for color in ["white", "black", "wood", "beige", "灰", "白", "黑", "木", "米色"]:
        if color in text:
            updated["color"] = color
    if "small" in text or "小户型" in text:
        updated["space"] = "small"
    if "pet" in text or "宠物" in text:
        updated["pet_friendly"] = True
    return updated


def _describe_room(request: str) -> str:
    text = request.lower()
    if "卧室" in text or "bedroom" in text or "床" in text:
        return "卧室场景，优先保证床、床头收纳、暖光照明和脚感材质。"
    if "客厅" in text or "living" in text or "沙发" in text:
        return "客厅场景，优先保证坐具、茶几和可视化收纳。"
    return "综合居住场景，先满足核心功能家具，再补充氛围单品。"


def _describe_style(request: str, preferences: dict[str, Any]) -> str:
    text = f"{request} {preferences}".lower()
    if "温馨" in text or "warm" in text or "cozy" in text:
        return "温馨自然，选择木质、暖白、织物和柔和灯光。"
    if "极简" in text or "minimal" in text:
        return "现代极简，控制颜色和线条，避免过多装饰。"
    return "简洁耐看，尽量选择后续容易替换和扩展的基础款。"


workflow = StateGraph(FurnitureState)
workflow.add_node("load_user_context", load_user_context)
workflow.add_node("understand_image", understand_image)
workflow.add_node("search_candidates", search_candidates)
workflow.add_node("plan_layout_and_generate_room", plan_layout_and_generate_room)
workflow.add_node("generate_recommendation", generate_recommendation)
workflow.add_node("persist_memory", persist_memory)
workflow.set_entry_point("load_user_context")
workflow.add_edge("load_user_context", "understand_image")
workflow.add_edge("understand_image", "search_candidates")
workflow.add_edge("search_candidates", "plan_layout_and_generate_room")
workflow.add_edge("plan_layout_and_generate_room", "generate_recommendation")
workflow.add_edge("generate_recommendation", "persist_memory")
workflow.add_edge("persist_memory", END)

CHECKPOINT_PATH = Path("data/furniture_checkpoints.sqlite3")
CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
_checkpoint_context: AsyncIterator[AsyncSqliteSaver] | None = None
_furniture_graph = None


async def get_furniture_graph():
    global _checkpoint_context, _furniture_graph
    if _furniture_graph is None:
        _checkpoint_context = AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_PATH))
        checkpointer = await _checkpoint_context.__aenter__()
        _furniture_graph = workflow.compile(checkpointer=checkpointer)
    return _furniture_graph


async def close_furniture_graph() -> None:
    global _checkpoint_context, _furniture_graph
    if _checkpoint_context is not None:
        await _checkpoint_context.__aexit__(None, None, None)
        _checkpoint_context = None
        _furniture_graph = None


async def run_furniture_assistant(
    uid: str,
    request: str,
    budget: float | None,
    image_bytes: bytes | None = None,
    image_mime: str = "",
) -> RecommendationResponse:
    graph = await get_furniture_graph()
    final_state = await graph.ainvoke(
        {
            "uid": uid,
            "request": request,
            "budget": budget,
            "image_bytes": image_bytes,
            "image_mime": image_mime,
        },
        config={"configurable": {"thread_id": uid}},
    )
    items = final_state.get("items", [])
    return RecommendationResponse(
        uid=uid,
        text=final_state.get("response_text", ""),
        items=items,
        placements=final_state.get("placements", []),
        room_image_url=final_state.get("room_image_url", ""),
        total=final_state.get("total", sum(item.price for item in items)),
        budget=budget,
        preferences=final_state.get("preferences", {}),
        image_notes=final_state.get("image_notes", ""),
    )


async def stream_furniture_assistant(
    uid: str,
    request: str,
    budget: float | None,
    image_bytes: bytes | None = None,
    image_mime: str = "",
) -> AsyncGenerator[dict[str, Any], None]:
    graph = await get_furniture_graph()
    input_state = {
        "uid": uid,
        "request": request,
        "budget": budget,
        "image_bytes": image_bytes,
        "image_mime": image_mime,
    }
    status_by_node = {
        "load_user_context": "正在读取你的历史偏好...",
        "understand_image": "正在理解图片和空间线索...",
        "search_candidates": "正在搜索并筛选宜家家具...",
        "plan_layout_and_generate_room": "正在规划家具摆放并生成整体效果图...",
        "generate_recommendation": "正在生成组合建议和预算说明...",
        "persist_memory": "正在保存本次总结和偏好...",
    }
    final_state: dict[str, Any] = {}
    yield {"type": "status", "message": "开始处理请求..."}
    async for chunk in graph.astream(
        input_state,
        config={"configurable": {"thread_id": uid}},
        stream_mode="updates",
    ):
        for node_name, node_state in chunk.items():
            yield {
                "type": "status",
                "node": node_name,
                "message": status_by_node.get(node_name, "处理中..."),
            }
            final_state.update(node_state)
            if node_name == "search_candidates":
                yield {
                    "type": "items",
                    "items": [
                        item.model_dump() if hasattr(item, "model_dump") else item
                        for item in final_state.get("items", [])
                    ],
                }
            if node_name == "plan_layout_and_generate_room":
                yield {
                    "type": "room",
                    "room_image_url": final_state.get("room_image_url", ""),
                    "render_status": "ready"
                    if final_state.get("room_image_url")
                    else "missing_image_api",
                    "placements": [
                        placement.model_dump() if hasattr(placement, "model_dump") else placement
                        for placement in final_state.get("placements", [])
                    ],
                }
            if node_name == "generate_recommendation":
                yield {
                    "type": "summary",
                    "text": final_state.get("response_text", ""),
                    "total": final_state.get("total", 0.0),
                }

    items = final_state.get("items", [])
    yield {
        "type": "final",
        "data": RecommendationResponse(
            uid=uid,
            text=final_state.get("response_text", ""),
            items=items,
            placements=final_state.get("placements", []),
            room_image_url=final_state.get("room_image_url", ""),
            total=final_state.get("total", sum(item.price for item in items)),
            budget=budget,
            preferences=final_state.get("preferences", {}),
            image_notes=final_state.get("image_notes", ""),
        ).model_dump(),
    }
