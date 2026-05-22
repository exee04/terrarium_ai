from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    """
    Unified request for both text and vision turns.
    Pass image_url to trigger vision routing (Groq Scout).
    Omit image_url for standard text routing (Groq 8B).
    """
    personality: str                # agent system prompt
    messages: list[dict]            # [{"role": "user"/"assistant", "content": "..."}]
    agent_name: str
    image_url: Optional[str] = None # public Cloudflare R2 URL — triggers vision model if set


class ChatResponse(BaseModel):
    content: str
    model: str                      # echoes which Groq model was actually used
    agent_name: str


class HealthResponse(BaseModel):
    status: str
    groq_reachable: bool