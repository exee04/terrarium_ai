"""
conversation.py — in-memory log, prompt builder, LLM call, response parser
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from config import (
    ROOM_ID, FASTAPI_BASE, FASTAPI_TIMEOUT,
    SHARED_RULES, SYSTEM_SUFFIX,
)
from state import get_state, state_to_english, get_facts

log = logging.getLogger("terrarium")

# ---------------------------------------------------------------------------
# Log buffer
# ---------------------------------------------------------------------------

@dataclass
class LogMessage:
    sender_name: str
    sender_type: str          # "agent" | "human"
    sender_id:   str
    content:     str
    state_patch: dict | None = None
    timestamp:   datetime    = field(default_factory=lambda: datetime.now(timezone.utc))


conversation:      list[LogMessage] = []
conversation_lock  = threading.Lock()


def add_to_log(
    sender_name: str,
    sender_type: str,
    sender_id:   str,
    content:     str,
    state_patch: dict | None = None,
) -> LogMessage:
    msg = LogMessage(
        sender_name=sender_name,
        sender_type=sender_type,
        sender_id=sender_id,
        content=content,
        state_patch=state_patch,
    )
    with conversation_lock:
        conversation.append(msg)
        if len(conversation) > 400:
            conversation.pop(0)
    return msg


def get_recent_log(limit: int) -> list[LogMessage]:
    with conversation_lock:
        return list(conversation[-limit:])

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _collapse_roles(raw: list[dict]) -> list[dict]:
    if not raw:
        return []
    collapsed = [dict(raw[0])]
    for msg in raw[1:]:
        if msg["role"] == collapsed[-1]["role"]:
            collapsed[-1]["content"] += "\n" + msg["content"]
        else:
            collapsed.append(dict(msg))
    if collapsed[0]["role"] == "assistant":
        collapsed.insert(0, {"role": "user", "content": "[start]"})
    return collapsed


def build_messages(agent, agent_names: set[str], context_limit: int) -> list[dict]:
    state       = get_state(agent.name)
    state_block = state_to_english(agent.name, state)
    recent      = get_recent_log(context_limit)

    if not recent:
        return [{"role": "user", "content": f"[State]\n{state_block}\n\nGroup chat just started. Say something."}]

    last_was_self = recent[-1].sender_name == agent.name
    if last_was_self:
        last_self = next((m for m in reversed(recent) if m.sender_name == agent.name), None)
        if last_self:
            state_block += f'\nYou just said: "{last_self.content}"'

    human_senders = list(dict.fromkeys(
        m.sender_name for m in recent if m.sender_type == "human"
    ))
    mentionable = [n for n in agent_names if n != agent.name] + human_senders
    state_block += f"\nParticipants you can @mention: {', '.join(mentionable)}"

    nudge = (
        "\n[You spoke last. You can follow up, react to the silence, or address someone with @Name.]"
        if last_was_self else ""
    )

    raw: list[dict] = []
    state_injected  = False

    for msg in recent:
        if msg.sender_name == agent.name:
            raw.append({"role": "assistant", "content": msg.content})
        else:
            content = f"{msg.sender_name}: {msg.content}"
            if not state_injected:
                content = f"[State]\n{state_block}{nudge}\n\n{content}"
                state_injected = True
            raw.append({"role": "user", "content": content})

    if not state_injected:
        raw.insert(0, {"role": "user", "content": f"[State]\n{state_block}{nudge}"})

    return _collapse_roles(raw)

# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_response(raw: str) -> tuple[str | None, dict]:
    reply = None
    patch: dict = {}
    for line in raw.splitlines():
        upper = line.upper()
        if upper.startswith("REPLY:"):
            reply = line[len("REPLY:"):].strip()
        elif upper.startswith("STATE:"):
            json_str = line[len("STATE:"):].strip()
            try:
                patch = json.loads(json_str)
            except json.JSONDecodeError:
                try:
                    patch = json.loads(json_str.replace("```json", "").replace("```", "").strip())
                except json.JSONDecodeError:
                    patch = {}

    if not reply:
        lines = [
            l for l in raw.splitlines()
            if l.strip()
            and not l.upper().startswith("STATE:")
            and not l.upper().startswith("REPLY:")
        ]
        reply = lines[0].strip() if lines else None

    if not reply or len(reply) < 3 or reply in ("...", "[...]"):
        reply = None

    return reply, patch

# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def call_fastapi(agent, agent_names: set[str], context_limit: int) -> tuple[str | None, dict, float]:
    payload = {
        "personality": agent.personality + "\n" + SHARED_RULES + SYSTEM_SUFFIX,
        "messages":    build_messages(agent, agent_names, context_limit),
        "agent_name":  agent.name,
    }
    start = time.monotonic()
    with httpx.Client(timeout=FASTAPI_TIMEOUT) as client:
        resp = client.post(f"{FASTAPI_BASE}/chat", json=payload)
        resp.raise_for_status()
    elapsed = time.monotonic() - start
    raw = resp.json()["content"].strip()
    reply, patch = parse_response(raw)
    return reply, patch, elapsed