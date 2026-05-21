import httpx
import base64
from config import OLLAMA_HOST


async def chat(model: str, personality: str, messages: list[dict]) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": personality}] + messages,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]

async def vision(model: str, personality: str, prompt: str, image_url: str) -> str:
    """Download an image and send it to the vision model."""
    # Download image from R2 and base64 encode it
    async with httpx.AsyncClient(timeout=30.0) as client:
        image_response = await client.get(image_url)
        image_response.raise_for_status()
        image_b64 = base64.b64encode(image_response.content).decode("utf-8")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": personality},  # ✅
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]


async def list_models() -> list[str]:
    """Return list of locally available Ollama models."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{OLLAMA_HOST}/api/tags")
        response.raise_for_status()
        data = response.json()
        return [m["name"] for m in data.get("models", [])]


async def is_alive() -> bool:
    """Check if Ollama is running."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_HOST}/api/tags")
            return response.status_code == 200
    except Exception:
        return False
