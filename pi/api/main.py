from fastapi import FastAPI, HTTPException
import groq_client
from api_models import ChatRequest, ChatResponse, HealthResponse

app = FastAPI(title="Digital Terrarium — Pi Worker API", version="2.0.0")


@app.get("/health", response_model=HealthResponse)
async def health():
    reachable = await groq_client.is_reachable()
    return HealthResponse(
        status="ok" if reachable else "groq_unreachable",
        groq_reachable=reachable,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    Unified chat endpoint. Routes to vision model automatically if image_url is set.
    """
    try:
        if req.image_url:
            content, model_used = await groq_client.vision(
                personality=req.personality,
                messages=req.messages,
                image_url=req.image_url,
            )
        else:
            content, model_used = await groq_client.chat(
                personality=req.personality,
                messages=req.messages,
            )
        return ChatResponse(
            content=content,
            model=model_used,
            agent_name=req.agent_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))