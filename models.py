from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class EmailIn(BaseModel):
    message_id: str
    subject: str
    body: str
    sender: Optional[str] = None
    received_at: Optional[datetime] = None
    has_attachments: bool = False

    @field_validator("subject")
    @classmethod
    def subject_length(cls, v: str) -> str:
        if len(v) > 500:
            raise ValueError("subject exceeds 500 characters")
        return v

    @field_validator("body")
    @classmethod
    def body_size(cls, v: str) -> str:
        if len(v.encode()) > 32_000:
            raise ValueError("body exceeds 32 KB")
        return v


class ClassificationOut(BaseModel):
    message_id: str
    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    sub_intent: Optional[str] = None
    priority: Optional[str] = None
    summary: Optional[str] = None
    email_response: Optional[str] = None
    latency_ms: int
    status: str = "success"


class BatchIn(BaseModel):
    emails: List[EmailIn]


class BatchOut(BaseModel):
    results: List[ClassificationOut]
    processed: int
    failed: int
