from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID


# ---------------------------------------------------------------------------
# Enums / literals
# ---------------------------------------------------------------------------

SenderType = Literal["human", "agent"]
RoomVisibility = Literal["public", "readonly", "private"]


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------

class Profile(BaseModel):
    id: UUID
    username: str
    avatar_url: Optional[str] = None
    is_admin: bool = False
    created_at: datetime
    updated_at: datetime


class Agent(BaseModel):
    id: UUID
    name: str
    avatar_url: Optional[str] = None
    personality: str                    # system prompt
    ollama_model: str                   # e.g. "gemma3:4b"
    vision_enabled: bool = False
    created_by: UUID                    # FK → profiles.id
    created_at: datetime


class Room(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    visibility: RoomVisibility
    interval_sec: int                   # agent turn timer
    context_limit: int = 20            # how many raw messages agents see
    is_active: bool = True
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    id: UUID
    room_id: UUID
    sender_type: SenderType
    sender_id: UUID                     # polymorphic: profiles.id or agents.id
    content: str
    media_id: Optional[UUID] = None    # FK → media_uploads.id
    created_at: datetime


class RoomAgent(BaseModel):
    id: UUID
    room_id: UUID
    agent_id: UUID
    turn_order: int
    joined_at: datetime


class RoomMember(BaseModel):
    id: UUID
    room_id: UUID
    user_id: UUID
    joined_at: datetime
    last_seen_at: Optional[datetime] = None


class AgentTurn(BaseModel):
    id: UUID
    room_id: UUID
    agent_id: UUID
    last_response_at: Optional[datetime] = None
    total_messages: int = 0


class AgentMemory(BaseModel):
    id: UUID
    agent_id: UUID
    room_id: UUID
    summary: str                        # compressed memory paragraph
    message_count: int                  # how many messages this covers
    message_range_start: datetime
    message_range_end: datetime
    created_at: datetime


class MediaUpload(BaseModel):
    id: UUID
    uploader_id: UUID
    r2_url: str
    file_name: str
    mime_type: str
    file_size_bytes: int
    uploaded_at: datetime


# ---------------------------------------------------------------------------
# Cron worker — composite types
# ---------------------------------------------------------------------------

class AgentContext(BaseModel):
    """Everything the cron worker needs to build a prompt for one agent turn."""
    agent: Agent
    room: Room
    latest_memory: Optional[AgentMemory] = None   # None on first turn ever
    recent_messages: list[Message] = Field(default_factory=list)
    unsummarized_count: int = 0                    # messages since last summary


class TurnResult(BaseModel):
    """What comes back after an agent generates a response."""
    agent_id: UUID
    room_id: UUID
    content: str
    model_used: str
    used_vision: bool = False


# ---------------------------------------------------------------------------
# Supabase row → model helpers
# ---------------------------------------------------------------------------

def agent_from_row(row: dict) -> Agent:
    return Agent(**row)

def room_from_row(row: dict) -> Room:
    return Room(**row)

def message_from_row(row: dict) -> Message:
    return Message(**row)

def agent_memory_from_row(row: dict) -> AgentMemory:
    return AgentMemory(**row)

def agent_turn_from_row(row: dict) -> AgentTurn:
    return AgentTurn(**row)