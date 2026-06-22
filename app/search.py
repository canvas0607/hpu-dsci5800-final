from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.models import FurnitureItem


DEMO_IKEA_ITEMS = [
    FurnitureItem(
        name="POANG Armchair",
        category="chair",
        price=129.0,
        url="https://www.ikea.com/us/en/search/?q=POANG%20armchair",
        reason="舒适阅读椅，线条简单，适合温和自然的角落。",
    ),
    FurnitureItem(
        name="KALLAX Shelf Unit",
        category="storage",
        price=89.99,
        url="https://www.ikea.com/us/en/search/?q=KALLAX%20shelf",
        reason="可放书、摆件和收纳篮，适合作为开放式储物。",
    ),
    FurnitureItem(
        name="LACK Coffee Table",
        category="table",
        price=39.99,
        url="https://www.ikea.com/us/en/search/?q=LACK%20coffee%20table",
        reason="价格低、体量轻，适合紧凑客厅或床边临时置物。",
    ),
    FurnitureItem(
        name="MALM Bed Frame",
        category="bed",
        price=299.0,
        url="https://www.ikea.com/us/en/search/?q=MALM%20bed%20frame",
        reason="卧室核心家具，造型干净，容易和白色、木色、织物搭配。",
    ),
    FurnitureItem(
        name="TARVA Bed Frame",
        category="bed",
        price=179.0,
        url="https://www.ikea.com/us/en/search/?q=TARVA%20bed%20frame",
        reason="松木材质比亮面白色更温暖，适合温馨卧室。",
    ),
    FurnitureItem(
        name="HEMNES Nightstand",
        category="nightstand",
        price=99.99,
        url="https://www.ikea.com/us/en/search/?q=HEMNES%20nightstand",
        reason="床头收纳实用，外形柔和，能增强卧室的温馨感。",
    ),
    FurnitureItem(
        name="RANARP Work Lamp",
        category="lamp",
        price=34.99,
        url="https://www.ikea.com/us/en/search/?q=RANARP%20lamp",
        reason="暖光床头灯，能让夜间氛围更柔和。",
    ),
    FurnitureItem(
        name="LOHALS Rug",
        category="rug",
        price=89.99,
        url="https://www.ikea.com/us/en/search/?q=LOHALS%20rug",
        reason="天然纤维质感能增加温度，也不会让 20 平卧室显得拥挤。",
    ),
    FurnitureItem(
        name="BRIMNES Wardrobe",
        category="wardrobe",
        price=249.0,
        url="https://www.ikea.com/us/en/search/?q=BRIMNES%20wardrobe",
        reason="封闭式衣物收纳，外观整洁，适合卧室保持清爽。",
    ),
    FurnitureItem(
        name="LINANAS Sofa",
        category="sofa",
        price=399.0,
        url="https://www.ikea.com/us/en/search/?q=LINANAS%20sofa",
        reason="紧凑型沙发，适合公寓和小户型客厅。",
    ),
]

QUERY_SYNONYMS = {
    "床": ["bed", "bedroom"],
    "床架": ["bed", "bedroom"],
    "卧室": ["bed", "bedroom"],
    "温馨": ["cozy", "warm", "wood", "lamp", "rug"],
    "暖": ["cozy", "warm", "wood", "lamp", "rug"],
    "20平": ["medium", "bedroom", "wardrobe"],
    "4x5": ["medium", "bedroom", "wardrobe"],
    "沙发": ["sofa", "living"],
    "客厅": ["sofa", "table", "storage", "living"],
    "椅子": ["chair", "armchair"],
    "扶手椅": ["chair", "armchair"],
    "茶几": ["coffee", "table"],
    "桌": ["table"],
    "储物": ["storage", "shelf"],
    "书架": ["storage", "shelf"],
    "收纳": ["storage", "shelf"],
}

ROOM_CATEGORY_PLAN = {
    "bedroom": ["bed", "nightstand", "lamp", "rug", "wardrobe", "storage"],
    "living": ["sofa", "table", "storage", "chair", "lamp", "rug"],
    "kitchen": ["storage", "table", "chair", "lamp"],
    "dining": ["table", "chair", "storage", "lamp"],
    "study": ["table", "chair", "storage", "lamp"],
}

CATEGORY_SEARCH_TERMS = {
    "bed": "MALM bed frame OR TARVA bed frame",
    "nightstand": "TARVA nightstand OR HEMNES nightstand",
    "lamp": "RANARP work lamp OR table lamp",
    "rug": "LOHALS rug OR VINDUM rug",
    "wardrobe": "BRIMNES wardrobe OR PAX wardrobe",
    "storage": "KALLAX shelf unit OR storage shelf",
    "sofa": "LINANAS sofa OR sofa",
    "table": "LACK coffee table OR coffee table",
    "chair": "POANG armchair OR armchair",
}

CATEGORY_MATCH_TERMS = {
    "bed": ["bed", "bed frame", "床"],
    "nightstand": ["nightstand", "bedside", "bedside table"],
    "lamp": ["lamp", "light", "lighting"],
    "rug": ["rug", "mat"],
    "wardrobe": ["wardrobe", "closet"],
    "storage": ["storage", "shelf", "shelving", "cabinet"],
    "sofa": ["sofa", "couch", "loveseat"],
    "table": ["coffee table", "side table", "table"],
    "chair": ["chair", "armchair"],
}

NON_PRODUCT_URL_PARTS = [
    "/cat/",
    "/categories/",
    "/rooms/",
    "/ideas/",
    "/inspiration/",
    "/search/",
    "/planner",
    "/customer-service/",
    "/campaigns/",
    "/new/",
    "/offers/",
]


async def search_ikea_furniture(
    query: str, budget: float | None, preferences: dict[str, Any]
) -> list[FurnitureItem]:
    query_text = f"{query} {preferences}".lower()
    room = _infer_room(query_text)
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        items = await _search_with_tavily(tavily_key, query, room)
        if items:
            return _fit_budget(items, budget)

    scored = sorted(
        DEMO_IKEA_ITEMS,
        key=lambda item: _score_item(item, query_text),
        reverse=True,
    )
    if room:
        planned = _select_for_room(scored, ROOM_CATEGORY_PLAN[room], budget)
        if planned:
            return planned
    return _fit_budget(scored, budget)


async def _search_with_tavily(api_key: str, query: str, room: str) -> list[FurnitureItem]:
    categories = ROOM_CATEGORY_PLAN.get(room) or _infer_categories(query)
    found: list[FurnitureItem] = []
    seen_urls: set[str] = set()
    async with httpx.AsyncClient(timeout=20) as client:
        for category in categories:
            category_items = await _search_category_with_tavily(
                client=client,
                api_key=api_key,
                user_query=query,
                category=category,
            )
            for item in category_items:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                found.append(item)
                break
            if len(found) >= 6:
                break
    return found


async def _search_category_with_tavily(
    client: httpx.AsyncClient,
    api_key: str,
    user_query: str,
    category: str,
) -> list[FurnitureItem]:
    term = CATEGORY_SEARCH_TERMS.get(category, category)
    payload = {
        "api_key": api_key,
        "query": (
            f"site:ikea.com/us/en/p/ IKEA \"{term}\" product page price"
        ),
        "search_depth": "advanced",
        "include_images": False,
        "max_results": 6,
    }
    response = await client.post("https://api.tavily.com/search", json=payload)
    response.raise_for_status()
    data = response.json()

    items: list[FurnitureItem] = []
    for result in data.get("results", []):
        url = result.get("url") or ""
        if not _is_ikea_product_url(url):
            continue
        title = result.get("title") or "IKEA furniture"
        content = result.get("content") or ""
        if not _matches_category(category, title, content, url):
            continue
        price = _extract_price(title + " " + content)
        if price <= 0:
            price = await _fetch_ikea_product_price(client, url)
        if price <= 0:
            continue
        items.append(
            FurnitureItem(
                name=_clean_product_title(title),
                category=category,
                price=price,
                url=url,
                reason=content[:220],
            )
        )
    return items


async def _fetch_ikea_product_price(client: httpx.AsyncClient, url: str) -> float:
    try:
        response = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return 0.0

    html = response.text
    for pattern in [
        r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)',
        r'"salesPrice"\s*:\s*\{[^}]*"numeral"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)',
        r'"currentPrice"\s*:\s*\{[^}]*"price"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)',
    ]:
        match = re.search(pattern, html)
        if match:
            return float(match.group(1))
    return 0.0


def _extract_price(text: str) -> float:
    match = re.search(r"\$\s*(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)", text)
    if not match:
        return 0.0
    return float(match.group(1).replace(",", ""))


def _clean_product_title(title: str) -> str:
    cleaned = re.sub(r"\s*-\s*IKEA.*$", "", title, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*\|\s*IKEA.*$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned[:120] or "IKEA product"


def _is_ikea_product_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "ikea.com" not in host:
        return False
    if any(part in path for part in NON_PRODUCT_URL_PARTS):
        return False
    return "/p/" in path


def _matches_category(category: str, title: str, content: str, url: str) -> bool:
    terms = CATEGORY_MATCH_TERMS.get(category, [category])
    haystack = f"{title} {content} {url}".lower()
    return any(term in haystack for term in terms)


def _infer_categories(query_text: str) -> list[str]:
    lowered = query_text.lower()
    categories = [
        category
        for category, terms in CATEGORY_SEARCH_TERMS.items()
        if category in lowered
        or any(term.lower() in lowered for term in re.split(r"\s+or\s+|\s+", terms, flags=re.IGNORECASE))
    ]
    if categories:
        return categories
    room = _infer_room(lowered)
    return ROOM_CATEGORY_PLAN.get(room, ["sofa", "table", "storage", "chair"])


def _score_item(item: FurnitureItem, query_text: str) -> int:
    haystack = f"{item.name} {item.category} {item.reason}".lower()
    expanded_terms = query_text.split()
    for key, terms in QUERY_SYNONYMS.items():
        if key in query_text:
            expanded_terms.extend(terms)
    score = sum(1 for word in expanded_terms if word in haystack)
    room = _infer_room(query_text)
    if room and item.category in ROOM_CATEGORY_PLAN[room]:
        score += 5
    if ("温馨" in query_text or "warm" in query_text or "cozy" in query_text) and item.category in {
        "lamp",
        "rug",
        "nightstand",
        "bed",
    }:
        score += 3
    return score


def _infer_room(query_text: str) -> str:
    if any(token in query_text for token in ["当前房间：厨房", "房间:厨房", "房间：厨房"]):
        return "kitchen"
    if any(token in query_text for token in ["当前房间：餐厅", "房间:餐厅", "房间：餐厅"]):
        return "dining"
    if any(token in query_text for token in ["当前房间：书房", "房间:书房", "房间：书房"]):
        return "study"
    if any(token in query_text for token in ["当前房间：客厅", "房间:客厅", "房间：客厅"]):
        return "living"
    if any(token in query_text for token in ["当前房间：卧室", "房间:卧室", "房间：卧室", "主卧"]):
        return "bedroom"
    if any(token in query_text for token in ["厨房", "kitchen"]):
        return "kitchen"
    if any(token in query_text for token in ["餐厅", "dining"]):
        return "dining"
    if any(token in query_text for token in ["书房", "study"]):
        return "study"
    if any(token in query_text for token in ["卧室", "bedroom", "床", "bed"]):
        return "bedroom"
    if any(token in query_text for token in ["客厅", "living", "sofa", "沙发"]):
        return "living"
    return ""


def _select_for_room(
    items: list[FurnitureItem], categories: list[str], budget: float | None
) -> list[FurnitureItem]:
    selected: list[FurnitureItem] = []
    total = 0.0
    for category in categories:
        candidates = [item for item in items if item.category == category and item not in selected]
        if not candidates:
            continue
        candidate = candidates[0]
        if budget and candidate.price > 0 and total + candidate.price > budget:
            continue
        selected.append(candidate)
        total += candidate.price
        if len(selected) >= 5:
            break
    return selected


def _fit_budget(items: list[FurnitureItem], budget: float | None) -> list[FurnitureItem]:
    if not budget:
        return items[:5]
    selected: list[FurnitureItem] = []
    total = 0.0
    for item in items:
        if item.price <= 0 or total + item.price <= budget:
            selected.append(item)
            total += item.price
        if len(selected) >= 5:
            break
    return selected or items[:3]
