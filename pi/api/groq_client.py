"""
groq_client.py — Groq API wrapper for the Pi AI worker.

Handles both text and vision calls through the same chat completions endpoint.
Model selection is the only thing that changes between the two.

Text  → llama-3.1-8b-instant        (14,400 RPD)
Vision → llama-4-scout-17b-16e-instruct  (1,000 RPD)
"""

import httpx
from config import GROQ_API_KEY, GROQ_TEXT_MODEL, GROQ_VISION_MODEL

GROQ_BASE = "https://api.groq.com/openai/v1"

_HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json",
}


async def chat(
    personality: str,
    messages: list[dict],
) -> tuple[str, str]:
    """
    Standard text completion.
    Returns (content, model_used).
    messages: [{"role": "user"/"assistant", "content": "..."}]
    """
    payload = {
        "model": GROQ_TEXT_MODEL,
        "messages": [{"role": "system", "content": personality}] + messages,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{GROQ_BASE}/chat/completions",
            headers=_HEADERS,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip(), GROQ_TEXT_MODEL


async def vision(
    personality: str,
    messages: list[dict],
    image_url: str,
) -> tuple[str, str]:
    """
    Vision completion — injects the image into the last user message as an
    image_url content block, then sends to Groq Scout.
    Returns (content, model_used).

    image_url should be a public Cloudflare R2 URL.
    Scout supports direct URL references — no base64 encoding needed.
    """
    # Build the standard message history, then append a vision turn
    # that pairs the most recent user text with the image.
    system_msg = {"role": "system", "content": personality}

    # Carry over prior conversation context as plain text
    history = [system_msg] + messages[:-1] if len(messages) > 1 else [system_msg]

    # Final user turn: text prompt + image side-by-side
    last_text = messages[-1]["content"] if messages else "React to this image."
    vision_turn = {
        "role": "user",
        "content": [
            {"type": "text", "text": last_text},
            {"type": "image_url", "image_url": {"url": image_url}},
        ],
    }

    payload = {
        "model": GROQ_VISION_MODEL,
        "messages": history + [vision_turn],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{GROQ_BASE}/chat/completions",
            headers=_HEADERS,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip(), GROQ_VISION_MODEL


async def is_reachable() -> bool:
    """Lightweight check — hits the models list endpoint."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{GROQ_BASE}/models",
                headers=_HEADERS,
            )
            return resp.status_code == 200
    except Exception:
        return False