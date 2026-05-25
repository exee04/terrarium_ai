"""
groq_client.py — Groq API wrapper for the Pi AI worker.
"""

import httpx
import threading
from datetime import date
from config import GROQ_API_KEY, GROQ_TEXT_MODEL, GROQ_VISION_MODEL, supabase, log

GROQ_BASE = "https://api.groq.com/openai/v1"

_HEADERS = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type": "application/json",
}

# ── Token tracking ───────────────────────────────────────────────────────────
def init_token_counter() -> None:
    """Load today's token count from DB on startup so restarts don't reset it."""
    global _tokens_today, _token_date
    try:
        result = supabase.rpc("get_pi_status").execute()
        if result.data:
            row = result.data[0]
            db_date = row.get("tokens_reset_at")
            db_tokens = row.get("tokens_used_today") or 0
            today = date.today()
            if db_date and str(db_date) == str(today):
                with _token_lock:
                    _tokens_today = db_tokens
                    _token_date = today
                log.info("Token counter seeded from DB: %d", db_tokens)
    except Exception as e:
        log.warning("Could not seed token counter: %s", e)
_token_lock = threading.Lock()
_tokens_today = 0
_token_date = date.today()

def _record_tokens(usage: dict) -> None:
    """Add tokens from a response usage block and push to Supabase."""
    global _tokens_today, _token_date
    total = usage.get("total_tokens", 0)
    if total == 0:
        return
    with _token_lock:
        today = date.today()
        if today != _token_date:
            _tokens_today = 0
            _token_date = today
        _tokens_today += total
        snapshot = _tokens_today
    try:
        supabase.rpc("update_pi_status", {
            "p_tokens_used_today": snapshot,
        }).execute()
        log.debug("Tokens today: %d (+%d)", snapshot, total)
    except Exception as e:
        log.warning("Failed to report tokens: %s", e)


# ── Chat ─────────────────────────────────────────────────────────────────────

async def chat(
    personality: str,
    messages: list[dict],
) -> tuple[str, str]:
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
        if "usage" in data:
            _record_tokens(data["usage"])
        return data["choices"][0]["message"]["content"].strip(), GROQ_TEXT_MODEL


# ── Vision ───────────────────────────────────────────────────────────────────

async def vision(
    personality: str,
    messages: list[dict],
    image_url: str,
) -> tuple[str, str]:
    system_msg = {"role": "system", "content": personality}
    history = [system_msg] + messages[:-1] if len(messages) > 1 else [system_msg]
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
        if "usage" in data:
            _record_tokens(data["usage"])
        return data["choices"][0]["message"]["content"].strip(), GROQ_VISION_MODEL


# ── Health ───────────────────────────────────────────────────────────────────
def get_tokens_today() -> int:
    with _token_lock:
        return _tokens_today
async def is_reachable() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{GROQ_BASE}/models", headers=_HEADERS)
            return resp.status_code == 200
    except Exception:
        return False