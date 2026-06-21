from __future__ import annotations

from app.models import FurnitureItem, FurniturePlacement


def plan_furniture_layout(
    items: list[FurnitureItem],
    request: str,
) -> list[FurniturePlacement]:
    room = infer_room(request, items)
    if room == "bedroom":
        return _bedroom_layout(items)
    if room == "living":
        return _living_layout(items)
    return _general_layout(items)


def infer_room(request: str, items: list[FurnitureItem] | None = None) -> str:
    text = request.lower()
    categories = {item.category for item in items or []}
    if any(token in text for token in ["卧室", "bedroom", "床"]) or "bed" in categories:
        return "bedroom"
    if any(token in text for token in ["客厅", "living", "沙发"]) or "sofa" in categories:
        return "living"
    return "general"


def _bedroom_layout(items: list[FurnitureItem]) -> list[FurniturePlacement]:
    templates = {
        "bed": (0.22, 0.34, 0.50, 0.34, "north wall", "床头靠主墙，左右保留走道。"),
        "nightstand": (0.74, 0.40, 0.12, 0.16, "right of bed", "床头柜放在靠近插座的一侧。"),
        "lamp": (0.76, 0.34, 0.08, 0.12, "on nightstand", "暖光灯放床头，避免直射眼睛。"),
        "rug": (0.18, 0.62, 0.60, 0.24, "under bed front", "地毯压在床前三分之一处，脚感更舒服。"),
        "wardrobe": (0.06, 0.18, 0.16, 0.42, "left wall", "衣柜靠侧墙，门前留出开门空间。"),
        "storage": (0.06, 0.18, 0.16, 0.42, "left wall", "收纳靠侧墙，减少视觉拥挤。"),
    }
    return _apply_templates(items, templates)


def _living_layout(items: list[FurnitureItem]) -> list[FurniturePlacement]:
    templates = {
        "sofa": (0.18, 0.42, 0.44, 0.22, "main wall", "沙发靠主墙，正对茶几和活动区。"),
        "table": (0.36, 0.66, 0.24, 0.14, "center", "茶几放在沙发前方，保留通行距离。"),
        "storage": (0.68, 0.26, 0.20, 0.36, "right wall", "收纳柜靠墙，展示和储物分区。"),
        "chair": (0.12, 0.66, 0.18, 0.18, "reading corner", "单椅放角落，形成阅读位。"),
        "lamp": (0.08, 0.48, 0.08, 0.20, "beside sofa", "落地灯放沙发侧边，补足氛围光。"),
        "rug": (0.24, 0.58, 0.48, 0.28, "center", "地毯覆盖沙发和茶几之间的活动区。"),
    }
    return _apply_templates(items, templates)


def _general_layout(items: list[FurnitureItem]) -> list[FurniturePlacement]:
    placements: list[FurniturePlacement] = []
    for index, item in enumerate(items):
        col = index % 3
        row = index // 3
        placements.append(
            FurniturePlacement(
                item_name=item.name,
                category=item.category,
                zone="flex zone",
                x=0.12 + col * 0.28,
                y=0.24 + row * 0.28,
                width=0.20,
                height=0.18,
                note="作为可移动家具，先放在不阻挡动线的位置。",
            )
        )
    return placements


def _apply_templates(
    items: list[FurnitureItem],
    templates: dict[str, tuple[float, float, float, float, str, str]],
) -> list[FurniturePlacement]:
    placements: list[FurniturePlacement] = []
    used_categories: set[str] = set()
    for item in items:
        template = templates.get(item.category)
        if template is None:
            continue
        x, y, width, height, zone, note = template
        if item.category in used_categories:
            x = min(x + 0.08, 0.88)
            y = min(y + 0.08, 0.88)
        used_categories.add(item.category)
        placements.append(
            FurniturePlacement(
                item_name=item.name,
                category=item.category,
                zone=zone,
                x=x,
                y=y,
                width=width,
                height=height,
                note=note,
            )
        )
    return placements or _general_layout(items)
