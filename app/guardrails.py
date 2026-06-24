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


def preflight_request(request: str, has_upload: bool = False) -> PreflightResult:
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

    if not text and has_upload:
        return PreflightResult(action="proceed")

    if not _has_furniture_intent(lowered, has_upload):
        return PreflightResult(
            action="refuse",
            message=(
                "我目前只处理家具选择、空间摆放、预算和带官网引用的商品组合相关请求。\n\n"
                "你可以这样问：给我一个 20 平卧室方案，预算 8000，喜欢温馨木色。"
            ),
        )

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
