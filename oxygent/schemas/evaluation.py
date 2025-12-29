"""Conversation evaluation data model definitions.

Defines data structures related to conversation quality evaluation,
including likes/dislikes, rating statistics, etc.
"""

from enum import Enum
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class RatingType(str, Enum):
    """Rating type enumeration"""
    LIKE = "like"
    DISLIKE = "dislike"


class ConversationRating(BaseModel):
    """Conversation rating model.

    Stores rating records for individual conversations.
    Each conversation (trace_id) can have multiple rating records.
    """
    rating_id: str = Field(..., description="Unique rating record ID")
    trace_id: str = Field(..., description="Conversation trace ID, links to specific conversation")
    rating_type: RatingType = Field(..., description="Rating type: like or dislike")
    user_id: Optional[str] = Field(None, description="User ID (if user system exists)")
    user_ip: Optional[str] = Field(None, description="User IP address")
    comment: Optional[str] = Field(None, description="Rating comment or feedback", max_length=500)
    erp: Optional[str] = Field(None, description="ERP system identifier")
    create_time: str = Field(..., description="Rating creation time")
    update_time: Optional[str] = Field(None, description="Rating update time")

    class Config:
        """Pydantic configuration"""
        use_enum_values = True


class RatingRequest(BaseModel):
    """Rating request model"""
    trace_id: str = Field(..., description="Conversation trace ID")
    rating_type: RatingType = Field(..., description="Rating type")
    comment: Optional[str] = Field(None, description="Rating comment", max_length=500)
    erp: Optional[str] = Field(None, description="ERP system identifier")

    class Config:
        use_enum_values = True


class RatingStats(BaseModel):
    """Conversation rating statistics model"""
    trace_id: str = Field(..., description="Conversation trace ID")
    like_count: int = Field(0, description="Number of likes")
    dislike_count: int = Field(0, description="Number of dislikes")
    total_ratings: int = Field(0, description="Total number of ratings")
    satisfaction_rate: float = Field(0.0, description="Satisfaction rate (like percentage)")
    last_updated: str = Field(..., description="Last update time")


class ConversationWithRating(BaseModel):
    """Conversation model with rating information.

    Extends original conversation information by adding rating statistics
    and complete rating history records.
    """
    trace_id: str = Field(..., description="Conversation trace ID")
    input: str = Field(..., description="User input")
    callee: str = Field(..., description="Called Agent")
    output: str = Field(..., description="Output result")
    create_time: str = Field(..., description="Creation time")
    from_trace_id: Optional[str] = Field(None, description="Source conversation ID")

    # Rating statistics information
    rating_stats: Optional[RatingStats] = Field(None, description="Rating statistics")
    # Rating history records list
    rating_history: Optional[List['ConversationRating']] = Field(None, description="Complete rating history records list")


class RatingResponse(BaseModel):
    """Rating operation response model"""
    success: bool = Field(..., description="Whether operation succeeded")
    rating_id: Optional[str] = Field(None, description="Rating record ID")
    current_stats: Optional[RatingStats] = Field(None, description="Current rating statistics")
    message: str = Field("", description="Response message")