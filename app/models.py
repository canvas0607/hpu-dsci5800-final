from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UserCreateResponse(BaseModel):
    uid: str


class FurnitureItem(BaseModel):
    name: str
    category: str = "furniture"
    price: float = 0.0
    currency: str = "USD"
    url: str = ""
    image_url: str = ""
    reason: str = ""


class FurniturePlacement(BaseModel):
    item_name: str
    category: str
    zone: str
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(ge=0.05, le=1.0)
    height: float = Field(ge=0.05, le=1.0)
    orientation: str = "front"
    note: str = ""


class RoomPlan(BaseModel):
    room_name: str
    room_type: str = "room"
    text: str = ""
    items: list[FurnitureItem] = Field(default_factory=list)
    placements: list[FurniturePlacement] = Field(default_factory=list)
    room_image_url: str = ""
    total: float = 0.0
    currency: str = "USD"


class RecommendationResponse(BaseModel):
    uid: str
    text: str
    items: list[FurnitureItem] = Field(default_factory=list)
    placements: list[FurniturePlacement] = Field(default_factory=list)
    room_image_url: str = ""
    room_plans: list[RoomPlan] = Field(default_factory=list)
    total: float
    currency: str = "USD"
    budget: float | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    image_notes: str = ""


class HistoryRecord(BaseModel):
    id: int
    uid: str
    user_request: str
    summary: str
    total: float
    created_at: str
