"""
agents.py — agent registry, hot-reload, weight system, @mention queue
"""
from __future__ import annotations

import logging
import random
import re
import threading
from collections import deque
from dataclasses import dataclass, field

from config import (
    supabase, ROOM_ID, GROQ_TEXT_MODEL,
    WEIGHT_BASELINE, WEIGHT_DECAY, WEIGHT_THRESHOLD,
    WEIGHT_SAME_AGENT_PENALTY,
    WEIGHT_BOOST_KEYWORD, WEIGHT_BOOST_NAMED, WEIGHT_BOOST_NICKNAME,
    WEIGHT_BOOST_TRIGGER, WEIGHT_CAP_TRIGGER, WEIGHT_CAP_NAMED,
    AT_MENTION_COOLDOWN,
)

log = logging.getLogger("terrarium")

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class LiveAgent:
    id:              str
    name:            str
    tag:             str
    personality:     str
    model_id:        str
    vision_enabled:  bool
    interest_keywords: list[str] = field(default_factory=list)
    trigger_phrases:   list[str] = field(default_factory=list)
    nicknames:         list[str] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Registry (module-level, protected by lock)
# ---------------------------------------------------------------------------

AGENTS:        list[LiveAgent]        = []
AGENT_BY_NAME: dict[str, LiveAgent]  = {}
AGENT_BY_ID:   dict[str, LiveAgent]  = {}
AGENT_NAMES:   set[str]              = set()
NICKNAME_MAP:  dict[str, LiveAgent]  = {}

agents_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Load from Supabase
# ---------------------------------------------------------------------------

def fetch_agents_for_room() -> list[LiveAgent]:
    ra_rows = (
        supabase.table("room_agents")
        .select("agent_id")
        .eq("room_id", ROOM_ID)
        .execute()
        .data or []
    )
    agent_ids = [r["agent_id"] for r in ra_rows]
    if not agent_ids:
        return []

    agents_rows = (
        supabase.table("agents")
        .select("id, name, tag, personality, model_id, vision_enabled")
        .in_("id", agent_ids)
        .execute()
        .data or []
    )

    nicks = supabase.table("agent_nicknames").select("agent_id, nickname").in_("agent_id", agent_ids).execute().data or []
    kws   = supabase.table("agent_keywords").select("agent_id, keyword").in_("agent_id", agent_ids).execute().data or []
    trigs = supabase.table("agent_triggers").select("agent_id, phrase").in_("agent_id", agent_ids).execute().data or []

    nicks_map: dict[str, list[str]] = {}
    for n in nicks:
        nicks_map.setdefault(n["agent_id"], []).append(n["nickname"])

    kws_map: dict[str, list[str]] = {}
    for k in kws:
        kws_map.setdefault(k["agent_id"], []).append(k["keyword"])

    trigs_map: dict[str, list[str]] = {}
    for t in trigs:
        trigs_map.setdefault(t["agent_id"], []).append(t["phrase"])

    return [
        LiveAgent(
            id=row["id"],
            name=row["name"],
            tag=row.get("tag") or "",
            personality=row["personality"],
            model_id=row.get("model_id") or GROQ_TEXT_MODEL,
            vision_enabled=row.get("vision_enabled", False),
            interest_keywords=kws_map.get(row["id"], []),
            trigger_phrases=trigs_map.get(row["id"], []),
            nicknames=nicks_map.get(row["id"], []),
        )
        for row in agents_rows
    ]


def reload_agents() -> list[LiveAgent]:
    global AGENTS, AGENT_BY_NAME, AGENT_BY_ID, AGENT_NAMES, NICKNAME_MAP
    try:
        fresh = fetch_agents_for_room()
    except Exception as exc:
        log.error("reload_agents failed: %s", exc)
        return []

    new_by_name  = {a.name: a for a in fresh}
    new_by_id    = {a.id:   a for a in fresh}
    new_names    = set(new_by_name)
    new_nick_map = {}
    for a in fresh:
        for nick in a.nicknames:
            new_nick_map[nick.lower()] = a

    with agents_lock:
        AGENTS        = fresh
        AGENT_BY_NAME = new_by_name
        AGENT_BY_ID   = new_by_id
        AGENT_NAMES   = new_names
        NICKNAME_MAP  = new_nick_map

    _sync_weights(new_names)
    log.info("Agents reloaded for room %s: %s", ROOM_ID, ", ".join(new_names) or "(none)")
    return fresh  # ← ADD THIS


def resolve_agent_by_name(name: str) -> LiveAgent | None:
    with agents_lock:
        return AGENT_BY_NAME.get(name.strip().capitalize()) or AGENT_BY_NAME.get(name.strip())

# ---------------------------------------------------------------------------
# Weight system
# ---------------------------------------------------------------------------

_weights:      dict[str, float] = {}
_weights_lock  = threading.Lock()


def _sync_weights(names: set[str]) -> None:
    with _weights_lock:
        for name in names:
            if name not in _weights:
                _weights[name] = WEIGHT_BASELINE


def decay_weights() -> None:
    with _weights_lock:
        for name in list(_weights):
            excess = _weights[name] - WEIGHT_BASELINE
            _weights[name] = WEIGHT_BASELINE + excess * WEIGHT_DECAY if excess > 0.01 else WEIGHT_BASELINE


def boost_weights_for_message(text: str) -> None:
    text_lower = text.lower()
    with agents_lock:
        snap = list(AGENTS)
    with _weights_lock:
        for agent in snap:
            nl = agent.name.lower()
            if any(phrase in text_lower for phrase in agent.trigger_phrases):
                _weights[agent.name] = min(_weights.get(agent.name, WEIGHT_BASELINE) * WEIGHT_BOOST_TRIGGER, WEIGHT_CAP_TRIGGER)
            elif f"@{nl}" in text_lower or nl in text_lower:
                _weights[agent.name] = min(_weights.get(agent.name, WEIGHT_BASELINE) * WEIGHT_BOOST_NAMED, WEIGHT_CAP_NAMED)
            elif any(nick in text_lower for nick in agent.nicknames):
                _weights[agent.name] = min(_weights.get(agent.name, WEIGHT_BASELINE) * WEIGHT_BOOST_NICKNAME, WEIGHT_CAP_NAMED)
            elif any(kw in text_lower for kw in agent.interest_keywords):
                _weights[agent.name] = min(_weights.get(agent.name, WEIGHT_BASELINE) * WEIGHT_BOOST_KEYWORD, WEIGHT_CAP_NAMED)


def penalise_agent(name: str) -> None:
    with _weights_lock:
        _weights[name] = max(
            _weights.get(name, WEIGHT_BASELINE) * WEIGHT_SAME_AGENT_PENALTY,
            WEIGHT_BASELINE * 0.4,
        )


def pick_next_agent() -> LiveAgent:
    with agents_lock:
        snap = list(AGENTS)
    if not snap:
        raise RuntimeError("No agents in room")
    with _weights_lock:
        weights = [_weights.get(a.name, WEIGHT_BASELINE) for a in snap]
    if max(weights) < WEIGHT_THRESHOLD:
        return random.choice(snap)
    return random.choices(snap, weights=weights, k=1)[0]

# ---------------------------------------------------------------------------
# @mention queue
# ---------------------------------------------------------------------------

reply_queue:   deque[LiveAgent]              = deque()
queue_lock     = threading.Lock()
_at_cooldowns: dict[tuple[str, str], int]   = {}
_cooldown_lock = threading.Lock()


def enqueue_mentions(text: str, allow_agent_source: str | None = None) -> None:
    mentioned: list[LiveAgent] = []
    for match in re.finditer(r"@([A-Za-z]\w*)", text):
        agent = resolve_agent_by_name(match.group(1))
        if agent and agent not in mentioned:
            mentioned.append(agent)
    if not mentioned:
        return

    if allow_agent_source:
        with _cooldown_lock:
            allowed = []
            for agent in mentioned:
                key = (allow_agent_source, agent.name)
                if _at_cooldowns.get(key, 0) <= 0:
                    _at_cooldowns[key] = AT_MENTION_COOLDOWN
                    allowed.append(agent)
            mentioned = allowed

    if not mentioned:
        return

    with queue_lock:
        existing = {a.name for a in reply_queue}
        for agent in mentioned:
            if agent.name not in existing:
                reply_queue.append(agent)
                existing.add(agent.name)


def dequeue_next() -> LiveAgent | None:
    with queue_lock:
        return reply_queue.popleft() if reply_queue else None


def decay_at_cooldowns() -> None:
    with _cooldown_lock:
        for key in list(_at_cooldowns):
            if _at_cooldowns[key] > 0:
                _at_cooldowns[key] -= 1