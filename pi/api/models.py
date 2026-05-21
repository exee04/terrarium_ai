from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    model: str = "gemma3:4b"
    personality: str          # agent system prompt
    messages: list[dict]      # [{"role": "user"/"assistant", "content": "..."}]
    agent_name: str


class ChatResponse(BaseModel):
    content: str
    model: str
    agent_name: str


class VisionRequest(BaseModel):
    model: str = "moondream:1.8b"
    personality: str
    prompt: str               # what to say about the image
    image_url: str            # public Cloudflare R2 URL
    agent_name: str


class VisionResponse(BaseModel):
    content: str
    model: str
    agent_name: str


class HealthResponse(BaseModel):
    status: str
    ollama: bool
    models_available: list[str]
