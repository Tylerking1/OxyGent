"""SSE message in base model."""

from typing import Any

from pydantic import BaseModel, Field

from ..utils.common_utils import generate_uuid, to_json


class SSEMessage(BaseModel):
    id: str = Field(default_factory=generate_uuid)
    event: str = Field("message")
    data: Any = Field("")
    retry: int = Field(3000) 

    def to_sse(self):
        return {"id": self.id, "event": self.event, "data": to_json(self.data), "retry": self.retry}