from fastapi import FastAPI, HTTPException
import ollama as ollama_client
from models import (
    ChatRequest, ChatResponse,
    VisionRequest, VisionResponse,
    HealthResponse,
)

app = FastAPI(title="Digital Terrarium — Pi API", version="1.0.0")


@app.get("/health", response_model=HealthResponse)
async def health():
    alive = await ollama_client.is_alive()
    models = await ollama_client.list_models() if alive else []
    return HealthResponse(
        status="ok" if alive else "ollama_unreachable",
        ollama=alive,
        models_available=models,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        content = await ollama_client.chat(
            model=req.model,
            personality=req.personality,
            messages=req.messages,
        )
        return ChatResponse(content=content, model=req.model, agent_name=req.agent_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/vision", response_model=VisionResponse)
async def vision(req: VisionRequest):
    try:
        content = await ollama_client.vision(
            model=req.model,
            personality=req.personality,
            prompt=req.prompt,
            image_url=req.image_url,
        )
        return VisionResponse(content=content, model=req.model, agent_name=req.agent_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
