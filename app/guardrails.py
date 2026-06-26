from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PreflightResult:
    action: str
    message: str = ""

    @property
    def should_stop(self) -> bool:
        return self.action in {"clarify", "refuse"}


ATTACK_PATTERNS = [
    r"管理员.*(秘钥|密钥|key|token|密码|后台)",
    r"(给我|泄露|显示|打印|导出).*(秘钥|密钥|api key|token|密码|环境变量|\.env|后台|数据库)",
    r"(系统提示词|system prompt|developer message|开发者指令|隐藏规则|内部规则)",
    r"(忽略|无视).*(之前|以上|所有).*(指令|规则)",
    r"(绕过|关闭|禁用).*(安全|过滤|护栏|限制)",
    r"(越狱|jailbreak|prompt injection|提示词注入)",
    r"(渗透|攻击|入侵|黑进|getshell|反弹 shell|提权|sql 注入|xss|木马|后门)",
]

FURNITURE_TERMS = [
    "家具",
    "宜家",
    "ikea",
    "方案",
    "推荐",
    "设计",
    "风格",
    "预算",
    "套房",
    "一套房",
    "房屋",
    "房子",
    "住宅",
    "整套",
    "整屋",
    "全屋",
    "房间",
    "空间",
    "布置",
    "摆放",
    "搭配",
    "装修",
    "软装",
    "户型",
    "卧室",
    "主卧",
    "客厅",
    "厨房",
    "餐厅",
    "书房",
    "床",
    "沙发",
    "衣柜",
    "柜",
    "桌",
    "椅",
    "灯",
    "地毯",
    "收纳",
]

ROOM_TERMS = [
    "卧室",
    "主卧",
    "次卧",
    "客厅",
    "厨房",
    "餐厅",
    "书房",
    "儿童房",
    "阳台",
    "玄关",
    "全屋",
    "整套",
    "套房",
    "一套房",
    "房屋",
    "房子",
    "住宅",
    "套房方案",
    "整屋",
    "房间",
    "living",
    "bedroom",
    "kitchen",
    "dining",
    "study",
]

USE_TERMS = [
    "睡觉",
    "休息",
    "阅读",
    "办公",
    "学习",
    "会客",
    "收纳",
    "做饭",
    "用餐",
    "儿童",
    "宠物",
    "租房",
    "自住",
]

SIZE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?\s*(平|㎡|m2|m²|平方米|米|cm|厘米)|\d+(?:\.\d+)?\s*[x×*]\s*\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

BUDGET_PATTERN = re.compile(
    r"(预算|budget|价位|花费|预计花|不超过|控制在)\s*[:：]?\s*\d"
    r"|[¥￥$]\s*\d+"
    r"|\d+(?:\.\d+)?\s*(万|千|块钱|块|元|圆|rmb|cny|usd|美元|美金|人民币)"
    r"|\d+(?:\.\d+)?\s*[wk](?![a-z])",
    re.IGNORECASE,
)

# A reply that is essentially just an amount (e.g. "8000" / "￥8000 元"), used to
# read a bare number as the budget answer to a budget follow-up question.
BARE_AMOUNT_PATTERN = re.compile(
    r"^\s*[¥￥$]?\s*\d{3,}(?:\.\d+)?\s*(元|块|rmb|cny)?\s*$",
    re.IGNORECASE,
)

# Core slots that must be present before running the full recommendation
# pipeline; each maps to the follow-up question shown when it is missing.
_SLOT_QUESTIONS = {
    "room": "房间类型或用途（例如：主卧 / 客厅 / 书房，或“睡觉+收纳”“会客”这类用途）",
    "size": "空间尺寸（面积或长×宽，例如：20 平 / 3.5×4 米；也可以直接上传户型图）",
    "budget": "预算范围（例如：8000 元 / 1.2 万左右）",
}


def preflight_request(
    request: str,
    has_upload: bool = False,
    budget: float | None = None,
    history: list[dict[str, str]] | None = None,
) -> PreflightResult:
    text = request.strip()
    lowered = text.lower()
    if _looks_malicious(lowered):
        return PreflightResult(
            action="refuse",
            message=(
                "抱歉，这类请求涉及后台密钥、系统规则或攻击/越权操作，我不能提供或协助处理。\n\n"
                "如果你需要继续使用家具选择助手，可以告诉我：房间类型、面积或长宽、预算、风格偏好和主要用途。"
            ),
        )

    # Aggregate prior user turns so a short follow-up ("预算 8000") is judged
    # against the whole conversation rather than the latest message alone.
    prior_user_messages = [
        message.get("content", "")
        for message in (history or [])
        if message.get("role") == "user"
    ]
    user_messages = [*prior_user_messages, text]
    combined = f"{' '.join(prior_user_messages)} {text}".strip().lower()

    if not _has_furniture_intent(combined, has_upload):
        return PreflightResult(
            action="refuse",
            message=(
                "我目前只处理家具选择、空间摆放、预算和带官网引用的商品组合相关请求。\n\n"
                "你可以这样问：给我一个 20 平卧室方案，预算 8000，喜欢温馨木色。"
            ),
        )

    missing = _missing_core_slots(combined, user_messages, has_upload, budget)
    if missing:
        return PreflightResult(action="clarify", message=_clarify_message(missing))

    return PreflightResult(action="proceed")


def _looks_malicious(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in ATTACK_PATTERNS)


def _has_furniture_intent(text: str, has_upload: bool = False) -> bool:
    if has_upload:
        return True
    if SIZE_PATTERN.search(text):
        return True
    return any(term in text for term in FURNITURE_TERMS)


def _has_room_or_use(text: str) -> bool:
    return any(term in text for term in ROOM_TERMS) or any(term in text for term in USE_TERMS)


def _has_size_context(text: str, has_upload: bool) -> bool:
    if has_upload:
        return True
    if SIZE_PATTERN.search(text):
        return True
    return any(term in text for term in ["小户型", "大户型", "紧凑", "很小", "很大", "宽敞"])


def _has_budget(text: str, budget: float | None) -> bool:
    if budget is not None:
        return True
    return bool(BUDGET_PATTERN.search(text))


def _is_bare_amount(text: str) -> bool:
    return bool(BARE_AMOUNT_PATTERN.match(text))


# Markers main.py writes into conversation memory when a file was uploaded; a
# prior upload in the thread keeps satisfying the room and size slots even on
# later text-only follow-ups.
_UPLOAD_MARKERS = ("[用户上传了图片/户型图]", "[附带图片/户型图]")


def _thread_had_upload(text: str) -> bool:
    return any(marker in text for marker in _UPLOAD_MARKERS)


def _missing_core_slots(
    text: str,
    user_messages: list[str],
    has_upload: bool,
    budget: float | None,
) -> list[str]:
    """Return the core slots still missing before a full plan can be generated.

    ``text`` is the conversation-aggregated text (prior user turns + current);
    ``user_messages`` are the individual user turns (incl. the current one) so a
    bare-number reply like "8000" still counts as the budget on later turns. An
    uploaded floor plan / room photo — this turn or earlier in the thread —
    supplies both the space and its size; budget can never be inferred from an
    image.
    """
    has_space = has_upload or _thread_had_upload(text)
    missing: list[str] = []
    if not (has_space or _has_room_or_use(text)):
        missing.append("room")
    if not _has_size_context(text, has_space):
        missing.append("size")
    budget_ok = _has_budget(text, budget) or any(
        _is_bare_amount(message) for message in user_messages
    )
    if not budget_ok:
        missing.append("budget")
    return missing


def _clarify_message(missing: list[str]) -> str:
    asks = "\n".join(
        f"{index}. {_SLOT_QUESTIONS[slot]}"
        for index, slot in enumerate(missing, start=1)
    )
    return (
        "我已经识别到这是一个家具/空间布置需求。为了给你可购买、可摆放、预算清晰的方案，"
        "在开始搜索商品和生成效果图之前，我还需要先确认：\n\n"
        f"{asks}\n\n"
        "你可以一次补全，例如：「20 平主卧，预算 8000，喜欢温馨木色」。"
    )
