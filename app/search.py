from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from app.models import FurnitureItem

from dotenv import load_dotenv
load_dotenv()


@dataclass(frozen=True)
class BrandSource:
    name: str
    aliases: tuple[str, ...]
    domains: tuple[str, ...]
    query_name: str
    product_path_markers: tuple[str, ...] = ()


BRAND_SOURCES = [
    BrandSource(
        name="宜家",
        aliases=("宜家", "ikea"),
        domains=("ikea.cn",),
        query_name="宜家 IKEA",
        product_path_markers=("/p/",),
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
    "bed": "MALM BRIMNES 床架 双人床",
    "nightstand": "床头柜",
    "lamp": "台灯 落地灯 照明",
    "rug": "地毯 客厅地毯 卧室地毯",
    "wardrobe": "衣柜 衣物收纳",
    "storage": "收纳柜 搁架 储物柜",
    "sofa": "沙发 三人沙发 单人沙发",
    "table": "茶几 餐桌 边桌 书桌",
    "chair": "椅子 扶手椅 餐椅",
}

CATEGORY_MATCH_TERMS = {
    "bed": ["bed", "bed frame", "床"],
    "nightstand": ["nightstand", "bedside", "bedside table", "床头柜"],
    "lamp": ["lamp", "light", "lighting", "灯", "台灯", "落地灯"],
    "rug": ["rug", "mat", "地毯"],
    "wardrobe": ["wardrobe", "closet", "衣柜"],
    "storage": ["storage", "shelf", "shelving", "cabinet", "收纳", "搁架", "柜"],
    "sofa": ["sofa", "couch", "loveseat", "沙发"],
    "table": ["coffee table", "side table", "table", "茶几", "桌"],
    "chair": ["chair", "armchair", "椅", "扶手椅"],
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
    "/news/",
    "/about/",
    "/brandindex",
    "/baike/",
    "/concept/",
]

NOISY_RESULT_TERMS = [
    "中文 | EN",
    "所有商品",
    "活动和特惠",
    "设计和服务",
    "家居灵感",
    "扫码下载",
    "随时随地都能宜家",
    "宜家APP",
    "召回",
    "批次",
    "隐私政策",
    "退换货",
    "购物袋",
]

OFFICIAL_FALLBACK_PRODUCT_URLS = {
    "bed": [
        "https://www.ikea.cn/cn/zh/p/malm-ma-er-mu-gao-chuang-jia-bai-se-lu-rui-s59009447",
        "https://www.ikea.cn/cn/zh/p/malm-ma-er-mu-gao-chuang-jia-bai-se-20265179/",
    ],
    "nightstand": [
        "https://www.ikea.cn/cn/zh/p/malm-ma-er-mu-liang-dou-chou-ti-gui-hei-he-se-50354621/",
    ],
    "lamp": [
        "https://www.ikea.cn/cn/zh/p/tagarp-te-jia-pu-luo-di-deng-hei-se-bai-se-20464046",
    ],
    "rug": [
        "https://www.ikea.cn/cn/zh/p/80596421",
    ],
    "wardrobe": [
        "https://www.ikea.cn/cn/zh/p/brimnes-bai-ling-yi-gui-dai-3-ge-men-bai-se-10407928/",
        "https://www.ikea.cn/cn/zh/p/brimnes-bai-ling-shuang-men-yi-gui-bai-se-20400479/",
    ],
    "storage": [
        "https://www.ikea.cn/cn/zh/p/eket-cabinet-with-4-compartments-brown-walnut-effect-90574584",
        "https://www.ikea.cn/cn/zh/p/ivar-yi-wa-ge-jia-dan-yuan-dai-gui-chou-ti-song-mu-hui-se-si-wang-s39395722",
    ],
    "sofa": [
        "https://www.ikea.cn/cn/zh/p/klippan-ke-li-pa-shuang-ren-sha-fa-qia-bu-sa-shen-hui-se-s89251778/",
        "https://www.ikea.cn/cn/zh/p/soederhamn-suo-de-han-si-ren-sha-fa-dai-gui-fei-yi-ta-mi-la-bai-se-hei-se-s19395006/",
    ],
    "table": [
        "https://www.ikea.cn/cn/zh/p/havsta-hai-si-ta-cha-ji-bai-se-90404266/",
        "https://www.ikea.cn/cn/zh/p/idanaes-yi-da-nai-cha-ji-shen-he-se-zhao-se-60487871/",
    ],
}


async def search_furniture(
    query: str, budget: float | None, preferences: dict[str, Any]
) -> list[FurnitureItem]:
    query_text = f"{query} {preferences}".lower()
    room = _infer_room(query_text)
    categories = ROOM_CATEGORY_PLAN.get(room) or _infer_categories(query)
    tavily_key = os.getenv("TAVILY_API_KEY")
    items: list[FurnitureItem] = []
    if tavily_key:
        try:
            timeout_seconds = float(os.getenv("SEARCH_TIMEOUT_SECONDS", "18"))
            items = await asyncio.wait_for(
                _search_with_tavily(tavily_key, query, room),
                timeout=timeout_seconds,
            )
        except (httpx.HTTPError, TimeoutError, ValueError):
            items = []

    if len(items) < min(3, len(categories)):
        fallback_items = await _search_official_fallback(categories)
        items = _merge_items(items, fallback_items)

    return _fit_budget(items, budget)


async def search_ikea_furniture(
    query: str, budget: float | None, preferences: dict[str, Any]
) -> list[FurnitureItem]:
    return await search_furniture(query=query, budget=budget, preferences=preferences)


async def _search_with_tavily(api_key: str, query: str, room: str) -> list[FurnitureItem]:
    categories = ROOM_CATEGORY_PLAN.get(room) or _infer_categories(query)
    brands = _selected_brands(query)
    found: list[FurnitureItem] = []
    seen_urls: set[str] = set()
    async with httpx.AsyncClient(timeout=20) as client:
        for category in categories:
            for brand in brands:
                category_items = await _search_category_with_tavily(
                    client=client,
                    api_key=api_key,
                    user_query=query,
                    category=category,
                    brand=brand,
                )
                chosen = next((item for item in category_items if item.url not in seen_urls), None)
                if chosen is None:
                    continue
                seen_urls.add(chosen.url)
                found.append(chosen)
                break
            if len(found) >= 6:
                break
    return found


async def _search_category_with_tavily(
    client: httpx.AsyncClient,
    api_key: str,
    user_query: str,
    category: str,
    brand: BrandSource,
) -> list[FurnitureItem]:
    term = CATEGORY_SEARCH_TERMS.get(category, category)
    items: list[FurnitureItem] = []
    for site_clause in _site_clauses(brand):
        payload = {
            "api_key": api_key,
            "query": (
                f"{site_clause} {brand.query_name} {term} 商品 价格 官网 报价 "
                f"{user_query}"
            ),
            "search_depth": "advanced",
            "include_images": False,
            "max_results": 6,
        }
        response = await client.post("https://api.tavily.com/search", json=payload)
        response.raise_for_status()
        data = response.json()
        for result in data.get("results", []):
            url = result.get("url") or ""
            if not _is_allowed_product_url(url, brand):
                continue
            title = result.get("title") or f"{brand.name} furniture"
            content = result.get("content") or ""
            if _is_noisy_result(title, url):
                continue
            if not _matches_category(category, title, content, url):
                continue
            price = await _fetch_product_price(client, url)
            if price <= 0:
                price = _extract_price(title + " " + content)
            if price <= 0:
                continue
            items.append(
                FurnitureItem(
                    name=_best_product_name(title, content, category, brand, url),
                    category=category,
                    price=price,
                    currency="CNY",
                    url=url,
                    brand=brand.name,
                    reason=_source_reason(brand),
                )
            )
    return items


async def _search_official_fallback(categories: list[str]) -> list[FurnitureItem]:
    brand = BRAND_SOURCES[0]
    items: list[FurnitureItem] = []
    seen_urls: set[str] = set()
    async with httpx.AsyncClient(timeout=12) as client:
        for category in categories:
            for url in OFFICIAL_FALLBACK_PRODUCT_URLS.get(category, []):
                if url in seen_urls:
                    continue
                item = await _product_page_item(client, url, category, brand)
                if item is None:
                    continue
                items.append(item)
                seen_urls.add(url)
                break
            if len(items) >= 6:
                break
    return items


async def _product_page_item(
    client: httpx.AsyncClient,
    url: str,
    category: str,
    brand: BrandSource,
) -> FurnitureItem | None:
    try:
        response = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    html = response.text
    price = _extract_price_from_html(html)
    if price <= 0:
        return None
    title = _extract_title_from_html(html) or urlparse(url).path.rsplit("/", 1)[-1]
    return FurnitureItem(
        name=_clean_product_title(title, brand),
        category=category,
        price=price,
        currency="CNY",
        url=str(response.url),
        brand=brand.name,
        reason=_source_reason(brand),
    )


def _merge_items(
    primary: list[FurnitureItem], fallback: list[FurnitureItem]
) -> list[FurnitureItem]:
    merged: list[FurnitureItem] = []
    seen_urls: set[str] = set()
    seen_categories: set[str] = set()
    for item in [*primary, *fallback]:
        if item.url in seen_urls:
            continue
        if item.category in seen_categories and len(merged) >= 3:
            continue
        merged.append(item)
        seen_urls.add(item.url)
        seen_categories.add(item.category)
        if len(merged) >= 6:
            break
    return merged


def _site_clauses(brand: BrandSource) -> list[str]:
    return ["site:ikea.cn/cn/zh/p/"]


async def _fetch_product_price(client: httpx.AsyncClient, url: str) -> float:
    try:
        response = await client.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return 0.0

    return _extract_price_from_html(response.text)


def _extract_price_from_html(html: str) -> float:
    for pattern in [
        r'i-price__sr-text">\s*¥\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)',
        r'<span class="i-price__currency">\s*¥\s*</span>\s*<span class="i-price__integer">([0-9]+(?:,[0-9]{3})*)</span>',
        r'"price"\s*:\s*"?(?:¥|￥)?\s*([0-9]{2,6}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)',
        r'"salesPrice"\s*:\s*\{[^}]*"numeral"\s*:\s*([0-9]{2,6}(?:\.[0-9]{1,2})?)',
        r'"currentPrice"\s*:\s*\{[^}]*"price"\s*:\s*([0-9]{2,6}(?:\.[0-9]{1,2})?)',
        r"(?:¥|￥|RMB|CNY)\s*([0-9]{2,6}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)",
    ]:
        match = re.search(pattern, html, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ""))
    return 0.0


def _extract_title_from_html(html: str) -> str:
    match = re.search(r"<title>\s*(.*?)\s*</title>", html, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    title = title.replace("&#x2F;", "/").replace("&amp;", "&")
    return title


def _extract_price(text: str) -> float:
    match = re.search(
        r"(?:¥|￥|RMB|CNY|价格[:：]?)\s*([0-9]{2,6}(?:,\d{3})*(?:\.\d{1,2})?)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return 0.0
    return float(match.group(1).replace(",", ""))


def _clean_product_title(title: str, brand: BrandSource) -> str:
    cleaned = title.strip()
    cleaned = re.sub(
        r"\s*(?:-|–|—|\|)\s*(?:IKEA|宜家(?:家居)?).*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"\s*[-|_]\s*(官方商城|官网|旗舰店|京东|淘宝|天猫).*$", "", cleaned)
    cleaned = re.sub(r"^(?:宜家|IKEA)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned[:120] or "家具商品"


def _best_product_name(
    title: str,
    content: str,
    category: str,
    brand: BrandSource,
    url: str,
) -> str:
    parsed = urlparse(url)
    if "jd.com" in parsed.netloc.lower() and "/jiage/" in parsed.path.lower():
        terms = CATEGORY_MATCH_TERMS.get(category, [category])
        for term in terms:
            pattern = rf"({re.escape(brand.name)}[^。；;\n]{{0,100}}{re.escape(term)}[^。；;\n]{{0,80}})"
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()[:120]
    return _clean_product_title(title, brand)


def _is_allowed_product_url(url: str, brand: BrandSource) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if not any(domain in host for domain in brand.domains):
        return False
    if any(part in path for part in NON_PRODUCT_URL_PARTS):
        return False
    if brand.product_path_markers and not any(marker in path for marker in brand.product_path_markers):
        return False
    return True


def _is_noisy_result(title: str, url: str) -> bool:
    normalized_title = re.sub(r"\s+", " ", title).strip()
    if not normalized_title:
        return True
    if any(term.lower() in normalized_title.lower() for term in NOISY_RESULT_TERMS):
        return True
    path = urlparse(url).path.lower()
    return any(part in path for part in ["/recall", "/news/", "/customer-service/"])


def _source_reason(brand: BrandSource) -> str:
    return (
        "来自官网商品页；已读取到商品价格。"
        "购买前请核验实时价格、库存、尺寸、配送和安装条件。"
    )


def _matches_category(category: str, title: str, content: str, url: str) -> bool:
    terms = CATEGORY_MATCH_TERMS.get(category, [category])
    parsed = urlparse(url)
    if "jd.com" in parsed.netloc.lower() and "/jiage/" in parsed.path.lower():
        haystack = f"{title} {content} {url}".lower()
    else:
        haystack = f"{title} {url}".lower()
    return any(term in haystack for term in terms)


def _selected_brands(query: str) -> list[BrandSource]:
    return BRAND_SOURCES


def _infer_categories(query_text: str) -> list[str]:
    lowered = query_text.lower()
    categories = [
        category
        for category, terms in CATEGORY_SEARCH_TERMS.items()
        if category in lowered
        or any(term.lower() in lowered for term in re.split(r"\s+", terms))
    ]
    if categories:
        return categories
    room = _infer_room(lowered)
    return ROOM_CATEGORY_PLAN.get(room, ["sofa", "table", "storage", "chair"])


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


def _fit_budget(items: list[FurnitureItem], budget: float | None) -> list[FurnitureItem]:
    if not budget:
        return items[:6]
    selected: list[FurnitureItem] = []
    total = 0.0
    for item in items:
        if item.price <= 0 or total + item.price <= budget:
            selected.append(item)
            total += item.price
        if len(selected) >= 6:
            break
    return selected or items[:3]
