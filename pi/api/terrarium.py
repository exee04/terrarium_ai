"""
terrarium.py — Digital Terrarium v4.1
Pi-side simulation loop.

Architecture:
  - Agents loaded from Supabase (nicknames, keywords, triggers hydrated)
  - Supabase realtime channel "agents-watch" → hot-reload on any agent change
  - Human messages arrive via Supabase realtime channel "habitat:inbox"
      * Web frontend INSERTs a row into `human_messages` table; Pi receives it
        via realtime and injects it into the turn queue
  - Agent messages pushed to:
      * Redis pub/sub    (PUBLISH "habitat:feed" <json>)  — live frontend display
      * Supabase insert  (messages table)                 — persistence
  - LLM calls go to local FastAPI on the Pi  (POST http://127.0.0.1:8000/chat)
    exactly as in local_sim.py

Environment variables required (.env):
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY   (service role — read agents, receive realtime, insert messages)
  FASTAPI_BASE                (default: http://127.0.0.1:8000)
  REDIS_URL                   (e.g. redis://localhost:6379 or Upstash URL)
  HABITAT_ID                  (UUID of the habitat/room these agents belong to)

Supabase tables expected:
  agents            (id, name, tag, personality, model_id, vision_enabled, ...)
  agent_nicknames   (agent_id, nickname)
  agent_keywords    (agent_id, keyword)
  agent_triggers    (agent_id, phrase)
  human_messages    (id, habitat_id, sender_name, content, created_at)
      → Web frontend INSERTs here; Pi listens via realtime INSERT events
  messages          (id, habitat_id, sender_name, sender_type, content,
                     state_patch, created_at)
      → Pi INSERTs agent (and echoes human) messages here

Redis keys:
  habitat:feed      CHANNEL — Pi publishes every message, web subscribes

Controls (stdin, same as v3.x):
  @Name       → guaranteed reply next turn (exact canonical name)
  /states     → print all emotional states
  /state NAME → print one agent's state
  /facts NAME → print one agent's known facts
  /nicknames  → list all nicknames
  /reload     → force agent reload from Supabase
  Ctrl+C      → graceful shutdown
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import sys
import threading
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from dotenv import load_dotenv
from supabase import create_client, Client
import redis as redis_lib

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("terrarium")

# ---------------------------------------------------------------------------
# Environment  (mirrors config.py)
# ---------------------------------------------------------------------------

GROQ_API_KEY         = os.getenv("GROQ_API_KEY")
SUPABASE_URL         = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY    = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
REDIS_URL            = os.getenv("REDIS_URL", "redis://localhost:6379")
HABITAT_ID           = os.environ["HABITAT_ID"]

FASTAPI_BASE         = os.getenv("FASTAPI_BASE", "http://127.0.0.1:8000")
FASTAPI_TIMEOUT      = 120.0

if not GROQ_API_KEY:
    raise RuntimeError("Missing GROQ_API_KEY in .env")
if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_ANON_KEY in .env")
if not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_SERVICE_KEY in .env")

# ---------------------------------------------------------------------------
# Model routing  (mirrors config.py)
# Text:   14,400 RPD  — llama-3.1-8b-instant
# Vision:  1,000 RPD  — llama-4-scout (image_url content block)
# ---------------------------------------------------------------------------

GROQ_TEXT_MODEL   = "llama-3.1-8b-instant"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# ---------------------------------------------------------------------------
# Simulation config  (mirror local_sim.py, tune freely)
# ---------------------------------------------------------------------------

CONTEXT_LIMIT           = 10

TYPING_GRACE            = 5
ACTIVE_DELAY            = 15
ACTIVE_SLOW_DELAY       = 30
IDLE_DELAY              = 300
ACTIVE_TIMEOUT_SLOW     = 30
ACTIVE_TIMEOUT_IDLE     = 120

SLEEP_START_HOUR        = 3
SLEEP_END_HOUR          = 6

WEIGHT_BASELINE             = 1.0
WEIGHT_DECAY                = 0.88
WEIGHT_THRESHOLD            = 1.15
WEIGHT_SAME_AGENT_PENALTY   = 0.4
WEIGHT_BOOST_KEYWORD        = 2.5
WEIGHT_BOOST_NAMED          = 6.0
WEIGHT_BOOST_NICKNAME       = 3.5
WEIGHT_BOOST_TRIGGER        = 8.0
WEIGHT_CAP_TRIGGER          = 12.0
WEIGHT_CAP_NAMED            = 8.0

AT_MENTION_COOLDOWN     = 4
MOOD_DECAY_TURNS        = 4

MOOD_VOCAB = [
    "neutral", "curious", "irritated", "excited", "anxious",
    "amused", "bored", "suspicious", "content", "overwhelmed",
]
RELATIONAL_VOCAB = [
    "trusts", "distrusts", "fond of", "wary of", "obsessed with",
    "jealous of", "indifferent to", "charmed by",
]
OPINION_VOCAB = [
    "likes", "dislikes", "obsessed with", "wary of", "neutral on",
]

SHARED_RULES = (
    "Group chat only. No actions, asterisks, narration. 1-2 sentences max. Never blank. "
    "You MAY @mention any participant by name to address them — other agents or human senders. "
    "Only do this when it genuinely adds to the conversation. Do not @mention every reply."
)

_STATE_SCHEMA = (
    'STATE:{"mood":"<mood|null>","mood_turns":<1-5|null>,'
    '"relations":{"<name>":"<stance>"},'
    '"opinions":{"<topic>":"<stance>"},'
    '"memory":"<one sentence|null>",'
    '"reason":"<REQUIRED>","learned_facts":["<fact>"]}'
)

SYSTEM_SUFFIX = (
    f"\n\nMood options: {', '.join(MOOD_VOCAB)}"
    f"\nRelation stances: {', '.join(RELATIONAL_VOCAB)}"
    f"\nOpinion stances: {', '.join(OPINION_VOCAB)}"
    "\n\nRespond in EXACTLY this format (2 lines):\n"
    "REPLY: <your message>\n"
    + _STATE_SCHEMA
    + "\n\nSTATE rules: reason required. Only include keys that changed. "
    "learned_facts = things others explicitly revealed. Empty patch = {}"
)

# ---------------------------------------------------------------------------
# Agent dataclass  (populated from Supabase)
# ---------------------------------------------------------------------------

@dataclass
class LiveAgent:
    id: str
    name: str
    tag: str
    personality: str
    model_id: str
    interest_keywords: list[str] = field(default_factory=list)
    trigger_phrases: list[str]   = field(default_factory=list)
    nicknames: list[str]         = field(default_factory=list)

# ---------------------------------------------------------------------------
# Global mutable agent registry
# Hot-reloaded when Supabase fires a change event.
# Protected by agents_lock — always acquire before reading AGENTS / AGENT_BY_NAME.
# ---------------------------------------------------------------------------

AGENTS:        list[LiveAgent]         = []
AGENT_BY_NAME: dict[str, LiveAgent]   = {}
AGENT_NAMES:   set[str]               = set()
NICKNAME_MAP:  dict[str, LiveAgent]   = {}   # lowercase nickname → agent
agents_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Supabase + Redis clients  (module-level singletons)
# ---------------------------------------------------------------------------

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

_redis = redis_lib.from_url(REDIS_URL, decode_responses=True)

FEED_CHANNEL = "habitat:feed"

# ---------------------------------------------------------------------------
# Load / reload agents from Supabase
# ---------------------------------------------------------------------------

def fetch_agents_from_supabase() -> list[LiveAgent]:
    """Pull agents + related data in 4 parallel queries, return LiveAgent list."""
    agents_resp    = supabase.rpc("get_agents").execute()
    nicknames_resp = supabase.table("agent_nicknames").select("*").execute()
    keywords_resp  = supabase.table("agent_keywords").select("*").execute()
    triggers_resp  = supabase.table("agent_triggers").select("*").execute()

    rows      = agents_resp.data or []
    nicks_all = nicknames_resp.data or []
    kws_all   = keywords_resp.data or []
    trigs_all = triggers_resp.data or []

    # Index related data by agent_id for O(1) lookup
    nicks_by_agent: dict[str, list[str]] = {}
    for n in nicks_all:
        nicks_by_agent.setdefault(n["agent_id"], []).append(n["nickname"])

    kws_by_agent: dict[str, list[str]] = {}
    for k in kws_all:
        kws_by_agent.setdefault(k["agent_id"], []).append(k["keyword"])

    trigs_by_agent: dict[str, list[str]] = {}
    for t in trigs_all:
        trigs_by_agent.setdefault(t["agent_id"], []).append(t["phrase"])

    result = []
    for row in rows:
        agent = LiveAgent(
            id=row["id"],
            name=row["name"],
            tag=row.get("tag") or "",
            personality=row["personality"],
            model_id=row.get("model_id") or DEFAULT_MODEL,
            interest_keywords=kws_by_agent.get(row["id"], []),
            trigger_phrases=trigs_by_agent.get(row["id"], []),
            nicknames=nicks_by_agent.get(row["id"], []),
        )
        result.append(agent)

    return result


def reload_agents() -> None:
    """Fetch fresh agents from Supabase and update all global registries."""
    global AGENTS, AGENT_BY_NAME, AGENT_NAMES, NICKNAME_MAP

    try:
        fresh = fetch_agents_from_supabase()
    except Exception as exc:
        log.error("reload_agents failed: %s", exc)
        return

    new_by_name:  dict[str, LiveAgent] = {a.name: a for a in fresh}
    new_names:    set[str]             = set(new_by_name)
    new_nick_map: dict[str, LiveAgent] = {}
    for a in fresh:
        for nick in a.nicknames:
            new_nick_map[nick.lower()] = a

    with agents_lock:
        AGENTS        = fresh
        AGENT_BY_NAME = new_by_name
        AGENT_NAMES   = new_names
        NICKNAME_MAP  = new_nick_map

    # Re-initialise weight + state registries for any truly new agent names
    _sync_weights_and_states(new_names)
    log.info("Agents reloaded: %s", ", ".join(new_names))


def _sync_weights_and_states(current_names: set[str]) -> None:
    """Add weight/state entries for new agents; leave existing ones intact."""
    with _weights_lock:
        for name in current_names:
            if name not in _weights:
                _weights[name] = WEIGHT_BASELINE
    with states_lock:
        for name in current_names:
            if name not in emotional_states:
                emotional_states[name] = _make_default_state()


# ---------------------------------------------------------------------------
# Supabase realtime  — watch agents table for changes, trigger hot-reload
# ---------------------------------------------------------------------------

_reload_flag = threading.Event()   # set by realtime callback, consumed by main loop


def _start_supabase_realtime() -> None:
    """
    Subscribe to Supabase realtime on the agents table.
    On any INSERT / UPDATE / DELETE we set _reload_flag.
    Runs in a daemon thread so it doesn't block the main loop.

    NOTE: supabase-py's realtime support is async-first.  We run it in its
    own thread with asyncio.run() so the rest of the codebase stays sync.
    """
    import asyncio
    from supabase._async.client import AsyncClient
    from supabase import acreate_client

    async def _listen() -> None:
        async_sb: AsyncClient = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

        def _on_change(payload: dict) -> None:
            log.info("Supabase realtime: agent change detected — scheduling reload")
            _reload_flag.set()

        channel = async_sb.channel("agents-watch")
        channel.on_postgres_changes(
            event="*",
            schema="public",
            table="agents",
            callback=_on_change,
        )
        await channel.subscribe()

        # Also watch related tables so nickname/keyword/trigger edits hot-reload too
        for tbl in ("agent_nicknames", "agent_keywords", "agent_triggers"):
            ch = async_sb.channel(f"{tbl}-watch")
            ch.on_postgres_changes(
                event="*",
                schema="public",
                table=tbl,
                callback=_on_change,
            )
            await ch.subscribe()

        # Keep the event loop alive indefinitely
        while True:
            await asyncio.sleep(60)

    def _run() -> None:
        asyncio.run(_listen())

    t = threading.Thread(target=_run, daemon=True, name="supabase-realtime")
    t.start()
    log.info("Supabase realtime listener started")

# ---------------------------------------------------------------------------
# Emotional state
# ---------------------------------------------------------------------------

emotional_states: dict[str, dict] = {}
states_lock = threading.Lock()
known_facts: dict[str, list[str]] = {}
facts_lock  = threading.Lock()


def _make_default_state() -> dict:
    return {
        "mood": "neutral",
        "mood_turns_remaining": 0,
        "relations": {},
        "opinions": {},
        "memory": None,
    }


def get_state(name: str) -> dict:
    with states_lock:
        if name not in emotional_states:
            emotional_states[name] = _make_default_state()
        return deepcopy(emotional_states[name])


def set_state(name: str, state: dict) -> None:
    with states_lock:
        emotional_states[name] = deepcopy(state)


def decay_mood(state: dict) -> dict:
    s = deepcopy(state)
    if s["mood"] != "neutral" and s["mood_turns_remaining"] > 0:
        s["mood_turns_remaining"] -= 1
        if s["mood_turns_remaining"] == 0:
            s["mood"] = "neutral"
    return s


def get_facts(name: str) -> list[str]:
    with facts_lock:
        return list(known_facts.get(name, []))


def add_fact(name: str, fact: str) -> None:
    with facts_lock:
        bucket = known_facts.setdefault(name, [])
        fl = fact.lower()
        if not any(fl in f.lower() or f.lower() in fl for f in bucket):
            bucket.append(fact)
            if len(bucket) > 20:
                bucket.pop(0)


def apply_state_patch(name: str, patch: dict) -> None:
    state = get_state(name)
    if patch.get("mood") and patch["mood"] in MOOD_VOCAB:
        state["mood"] = patch["mood"]
        state["mood_turns_remaining"] = int(patch.get("mood_turns") or MOOD_DECAY_TURNS)
    for person, stance in patch.get("relations", {}).items():
        if stance in RELATIONAL_VOCAB:
            state["relations"][person] = stance
    for topic, stance in patch.get("opinions", {}).items():
        if stance in OPINION_VOCAB:
            state["opinions"][topic] = stance
    if patch.get("memory"):
        state["memory"] = patch["memory"]
    for fact in patch.get("learned_facts", []):
        if isinstance(fact, str) and fact.strip():
            add_fact(name, fact.strip())
    set_state(name, state)


def state_to_english(name: str, state: dict) -> str:
    lines = []
    mood, turns = state.get("mood", "neutral"), state.get("mood_turns_remaining", 0)
    if mood != "neutral":
        lines.append(f"Mood: {mood} ({turns}t)")
    rels = state.get("relations", {})
    if rels:
        lines.append("Toward: " + "; ".join(f"{s} {t}" for t, s in rels.items()))
    ops = {t: s for t, s in state.get("opinions", {}).items() if s != "neutral on"}
    if ops:
        lines.append("Opinions: " + "; ".join(f"{s} {t}" for t, s in ops.items()))
    if state.get("memory"):
        lines.append(f"Rem: {state['memory']}")
    facts = get_facts(name)
    if facts:
        lines.append("Know: " + " | ".join(facts[-4:]))
    with states_lock:
        snapshot = {k: deepcopy(v) for k, v in emotional_states.items() if k != name}
    others = [
        f"{n} {s['relations'][name]} you"
        for n, s in snapshot.items()
        if name in s.get("relations", {})
    ]
    if others:
        lines.append("Sensed: " + "; ".join(others))
    return "\n".join(lines) if lines else "Mood: neutral"

# ---------------------------------------------------------------------------
# @mention queue + cooldown
# ---------------------------------------------------------------------------

reply_queue: deque[LiveAgent] = deque()
queue_lock  = threading.Lock()

_at_cooldowns: dict[tuple[str, str], int] = {}
_cooldown_lock = threading.Lock()


def resolve_agent_by_name(name: str) -> LiveAgent | None:
    with agents_lock:
        return AGENT_BY_NAME.get(name.strip().capitalize()) or AGENT_BY_NAME.get(name.strip())


def enqueue_mentions(text: str, allow_agent_source: str | None = None) -> None:
    mentioned = []
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

# ---------------------------------------------------------------------------
# Interest / weight system
# ---------------------------------------------------------------------------

_weights: dict[str, float] = {}
_weights_lock = threading.Lock()


def decay_weights() -> None:
    with _weights_lock:
        for name in _weights:
            excess = _weights[name] - WEIGHT_BASELINE
            if excess > 0.01:
                _weights[name] = WEIGHT_BASELINE + excess * WEIGHT_DECAY
            else:
                _weights[name] = WEIGHT_BASELINE


def boost_weights_for_message(text: str) -> None:
    text_lower = text.lower()
    with agents_lock:
        agents_snapshot = list(AGENTS)
    with _weights_lock:
        for agent in agents_snapshot:
            name_lower = agent.name.lower()
            if any(phrase in text_lower for phrase in agent.trigger_phrases):
                _weights[agent.name] = min(
                    _weights.get(agent.name, WEIGHT_BASELINE) * WEIGHT_BOOST_TRIGGER,
                    WEIGHT_CAP_TRIGGER,
                )
            elif f"@{name_lower}" in text_lower or name_lower in text_lower:
                _weights[agent.name] = min(
                    _weights.get(agent.name, WEIGHT_BASELINE) * WEIGHT_BOOST_NAMED,
                    WEIGHT_CAP_NAMED,
                )
            elif any(nick in text_lower for nick in agent.nicknames):
                _weights[agent.name] = min(
                    _weights.get(agent.name, WEIGHT_BASELINE) * WEIGHT_BOOST_NICKNAME,
                    WEIGHT_CAP_NAMED,
                )
            elif any(kw in text_lower for kw in agent.interest_keywords):
                _weights[agent.name] = min(
                    _weights.get(agent.name, WEIGHT_BASELINE) * WEIGHT_BOOST_KEYWORD,
                    WEIGHT_CAP_NAMED,
                )


def pick_next_agent() -> LiveAgent:
    with agents_lock:
        agents_snapshot = list(AGENTS)
    if not agents_snapshot:
        raise RuntimeError("No agents loaded")
    with _weights_lock:
        weights = [_weights.get(a.name, WEIGHT_BASELINE) for a in agents_snapshot]
    if not weights or max(weights) < WEIGHT_THRESHOLD:
        return random.choice(agents_snapshot)
    return random.choices(agents_snapshot, weights=weights, k=1)[0]

# ---------------------------------------------------------------------------
# Conversation log  (in-memory ring buffer; Supabase is source of truth)
# ---------------------------------------------------------------------------

@dataclass
class LogMessage:
    sender: str
    sender_type: str          # "agent" | "human"
    content: str
    state_patch: dict | None  = None
    timestamp: datetime       = field(default_factory=datetime.now)


conversation: list[LogMessage] = []
conversation_lock = threading.Lock()


def add_to_log(
    sender: str,
    sender_type: str,
    content: str,
    state_patch: dict | None = None,
) -> LogMessage:
    msg = LogMessage(
        sender=sender,
        sender_type=sender_type,
        content=content,
        state_patch=state_patch,
    )
    with conversation_lock:
        conversation.append(msg)
        if len(conversation) > 200:   # local memory cap
            conversation.pop(0)
    return msg


def get_recent_log(limit: int = CONTEXT_LIMIT) -> list[LogMessage]:
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


def build_messages(agent: LiveAgent) -> list[dict]:
    state       = get_state(agent.name)
    state_block = state_to_english(agent.name, state)
    recent      = get_recent_log()

    with agents_lock:
        all_agent_names = AGENT_NAMES.copy()

    if not recent:
        return [{"role": "user", "content": f"[State]\n{state_block}\n\nGroup chat just started. Say something."}]

    last_was_self = recent[-1].sender == agent.name
    if last_was_self:
        last_self = next((m for m in reversed(recent) if m.sender == agent.name), None)
        if last_self:
            state_block += f'\nYou just said: "{last_self.content}"'

    human_senders = list(dict.fromkeys(
        m.sender for m in recent if m.sender not in all_agent_names
    ))
    mentionable = [a for a in all_agent_names if a != agent.name] + human_senders
    state_block += f"\nParticipants you can @mention: {', '.join(mentionable)}"

    nudge = (
        "\n[You spoke last. You can follow up, react to the silence, or address someone with @Name.]"
        if last_was_self else ""
    )

    raw: list[dict] = []
    state_injected  = False

    for msg in recent:
        if msg.sender == agent.name:
            raw.append({"role": "assistant", "content": msg.content})
        else:
            content = f"{msg.sender}: {msg.content}"
            if not state_injected:
                content = f"[State]\n{state_block}{nudge}\n\n{content}"
                state_injected = True
            raw.append({"role": "user", "content": content})

    if not state_injected:
        raw.insert(0, {"role": "user", "content": f"[State]\n{state_block}{nudge}"})

    return _collapse_roles(raw)

# ---------------------------------------------------------------------------
# Parse LLM response
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
                json_str = json_str.replace("```json", "").replace("```", "").strip()
                try:
                    patch = json.loads(json_str)
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
# LLM call  — POST to local FastAPI on the Pi  (mirrors local_sim.py exactly)
# ---------------------------------------------------------------------------

def call_fastapi(agent: LiveAgent) -> tuple[str | None, dict, float]:
    """
    Returns (reply_text, state_patch, elapsed_seconds).
    Payload matches what local_sim.py sends to /chat:
      { personality, messages, agent_name }
    FastAPI handles model selection; we just send personality + history.
    """
    payload = {
        "personality": agent.personality + "\n" + SHARED_RULES + SYSTEM_SUFFIX,
        "messages":    build_messages(agent),
        "agent_name":  agent.name,
    }

    start = time.monotonic()
    with httpx.Client(timeout=FASTAPI_TIMEOUT) as client:
        resp = client.post(f"{FASTAPI_BASE}/chat", json=payload)
        resp.raise_for_status()

    elapsed = time.monotonic() - start
    raw     = resp.json()["content"].strip()
    reply, patch = parse_response(raw)
    return reply, patch, elapsed

# ---------------------------------------------------------------------------
# Push agent message outward  (Redis pub/sub + Supabase insert)
# ---------------------------------------------------------------------------

def push_message(agent: LiveAgent, content: str, patch: dict) -> None:
    """
    1. Publish to Redis so the frontend gets it instantly via pub/sub.
    2. Insert into Supabase messages table for persistence.
    Both are best-effort; failures are logged but don't crash the loop.
    """
    payload = json.dumps({
        "habitat_id":   HABITAT_ID,
        "sender_name":  agent.name,
        "sender_type":  "agent",
        "content":      content,
        "state_patch":  patch,
        "timestamp":    datetime.utcnow().isoformat(),
    })

    # Redis pub/sub — frontend subscribes for live display
    try:
        _redis.publish(FEED_CHANNEL, payload)
    except Exception as exc:
        log.warning("Redis publish failed: %s", exc)

    # Supabase insert — persistent record
    try:
        supabase.table("messages").insert({
            "habitat_id":  HABITAT_ID,
            "sender_name": agent.name,
            "sender_type": "agent",
            "content":     content,
            "state_patch": patch,
        }).execute()
    except Exception as exc:
        log.warning("Supabase insert failed: %s", exc)


def push_human_echo(sender: str, content: str) -> None:
    """Echo a human message to the feed channel so all web clients see it."""
    payload = json.dumps({
        "habitat_id":  HABITAT_ID,
        "sender_name": sender,
        "sender_type": "human",
        "content":     content,
        "timestamp":   datetime.utcnow().isoformat(),
    })
    try:
        _redis.publish(FEED_CHANNEL, payload)
    except Exception as exc:
        log.warning("Redis echo failed: %s", exc)

# ---------------------------------------------------------------------------
# Human message intake — Supabase realtime on `human_messages` table
#
# Web frontend does:
#   supabase.from("human_messages").insert({
#     habitat_id, sender_name, content
#   })
#
# Pi receives the INSERT event here and queues it for the main loop.
# ---------------------------------------------------------------------------

_pending_human: dict | None = None     # set by realtime callback, consumed by main loop
_human_lock    = threading.Lock()
last_human_time: float = 0.0


def _on_human_message(payload: dict) -> None:
    """Realtime INSERT callback — fires on every new row in human_messages."""
    global last_human_time
    record = payload.get("record") or payload.get("new") or {}
    habitat = record.get("habitat_id")
    if habitat and habitat != HABITAT_ID:
        return   # message for a different habitat, ignore
    sender  = record.get("sender_name", "Human")
    content = record.get("content", "").strip()
    if not content:
        return
    with _human_lock:
        # Only keep the most recent unprocessed message.
        # If you want a queue instead, swap this for a deque.append().
        globals()["_pending_human"] = {"sender": sender, "content": content}
    last_human_time = time.time()
    log.info("Human message received: %s: %s", sender, content)


def pop_human_message() -> dict | None:
    global _pending_human
    with _human_lock:
        msg, _pending_human = _pending_human, None
    return msg


def _start_human_inbox_listener() -> None:
    """
    Subscribe to INSERT events on the human_messages table via Supabase realtime.
    Runs the async event loop in its own daemon thread so the rest of the
    codebase stays synchronous.
    """
    import asyncio
    from supabase._async.client import AsyncClient
    from supabase import acreate_client

    async def _listen() -> None:
        async_sb: AsyncClient = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        channel = async_sb.channel("human-inbox")
        channel.on_postgres_changes(
            event="INSERT",
            schema="public",
            table="human_messages",
            callback=_on_human_message,
        )
        await channel.subscribe()
        log.info("Supabase human_messages listener subscribed")
        while True:
            await asyncio.sleep(60)

    def _run() -> None:
        asyncio.run(_listen())

    t = threading.Thread(target=_run, daemon=True, name="human-inbox-listener")
    t.start()

# ---------------------------------------------------------------------------
# Active / idle / sleep timing
# ---------------------------------------------------------------------------

def _is_sleep_time() -> bool:
    h = datetime.now().hour
    if SLEEP_START_HOUR > SLEEP_END_HOUR:
        return h >= SLEEP_START_HOUR or h < SLEEP_END_HOUR
    return SLEEP_START_HOUR <= h < SLEEP_END_HOUR


def _current_delay() -> int:
    since = time.time() - last_human_time
    if since < ACTIVE_TIMEOUT_SLOW:   return ACTIVE_DELAY
    if since < ACTIVE_TIMEOUT_IDLE:   return ACTIVE_SLOW_DELAY
    return IDLE_DELAY

# ---------------------------------------------------------------------------
# Shared stop event
# ---------------------------------------------------------------------------

stop_event = threading.Event()

# ---------------------------------------------------------------------------
# Main simulation loop
# ---------------------------------------------------------------------------

def main_loop() -> None:
    """
    Pseudocode (matches the requested structure):

    init roles (reload_agents)
    while online:
        check for changes → reload if flagged
        check if human sent a message
        countdown with interrupt on human message
        pick agent
        call FastAPI
        push message
        catch errors, loop
    """
    global last_human_time

    log.info("Main loop started")

    while not stop_event.is_set():

        # ── 1. Hot-reload check ──────────────────────────────────────────
        if _reload_flag.is_set():
            _reload_flag.clear()
            log.info("Hot-reloading agents from Supabase…")
            reload_agents()

        # ── 2. Sleep gate ────────────────────────────────────────────────
        if _is_sleep_time():
            log.debug("Sleeping (hour %d)", datetime.now().hour)
            time.sleep(30)
            continue

        # ── 3. Countdown — interruptible by human message ────────────────
        delay     = _current_delay()
        remaining = delay
        interrupted = False

        while remaining > 0 and not stop_event.is_set():
            # Check for hot-reload requests mid-countdown too
            if _reload_flag.is_set():
                _reload_flag.clear()
                reload_agents()

            # Check for incoming human message
            human_msg = pop_human_message()
            if human_msg:
                sender  = human_msg.get("sender", "Human")
                content = human_msg.get("content", "")
                if content:
                    # Log it locally
                    add_to_log(sender, "human", content)
                    # Echo to web feed
                    push_human_echo(sender, content)
                    # Boost weights + enqueue any @mentions
                    boost_weights_for_message(content)
                    enqueue_mentions(content, allow_agent_source=None)
                    # Snap countdown to grace window
                    remaining   = TYPING_GRACE
                    interrupted = True
                    last_human_time = time.time()
                    log.info("Human message injected, snapping to grace window")

            time.sleep(1)
            remaining -= 1

        if stop_event.is_set():
            break

        # ── 4. Agent selection ───────────────────────────────────────────
        decay_weights()
        decay_at_cooldowns()

        queued = dequeue_next()
        try:
            agent = queued if queued else pick_next_agent()
        except RuntimeError:
            log.warning("No agents available, waiting…")
            time.sleep(5)
            continue

        if queued:
            log.info("@→ %s (queued mention)", agent.name)
        else:
            log.info("Turn: %s", agent.name)

        # ── 5. LLM call ──────────────────────────────────────────────────
        reply: str | None = None
        patch: dict       = {}
        elapsed: float    = 0.0

        try:
            reply, patch, elapsed = call_fastapi(agent)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                log.warning("FastAPI/model rate-limited (429), sleeping 30s")
                time.sleep(30)
            else:
                log.error("FastAPI HTTP error %d: %s", status, exc)
                time.sleep(5)
            continue
        except httpx.TimeoutException:
            log.warning("FastAPI timeout for %s, skipping turn", agent.name)
            continue
        except Exception as exc:
            log.error("Unexpected LLM error: %s", exc)
            time.sleep(5)
            continue

        if not reply:
            log.warning("%s returned empty reply, skipping", agent.name)
            continue

        log.info("%s (%.1fs): %s", agent.name, elapsed, reply)

        # ── 6. State update ──────────────────────────────────────────────
        decayed = decay_mood(get_state(agent.name))
        set_state(agent.name, decayed)
        if patch:
            apply_state_patch(agent.name, patch)

        # ── 7. Add to local log + process any @mentions in reply ─────────
        add_to_log(agent.name, "agent", reply, state_patch=patch)
        enqueue_mentions(reply, allow_agent_source=agent.name)
        boost_weights_for_message(reply)

        # Penalise same-agent back-to-back
        with _weights_lock:
            _weights[agent.name] = max(
                _weights.get(agent.name, WEIGHT_BASELINE) * WEIGHT_SAME_AGENT_PENALTY,
                WEIGHT_BASELINE * 0.4,
            )

        # ── 8. Push to web ───────────────────────────────────────────────
        push_message(agent, reply, patch)

# ---------------------------------------------------------------------------
# Stdin input loop  (local terminal commands — useful while SSHed into the Pi)
# ---------------------------------------------------------------------------

def input_loop() -> None:
    global last_human_time

    while not stop_event.is_set():
        try:
            text = input()
        except EOFError:
            break

        text = text.strip()
        if not text:
            continue

        # ── Commands ──
        if text.lower() == "/states":
            with agents_lock:
                names = list(AGENT_NAMES)
            for name in names:
                s = get_state(name)
                print(f"  {name}: mood={s['mood']} rels={s['relations']} mem={s['memory']}")
            continue

        if text.lower().startswith("/state "):
            agent = resolve_agent_by_name(text[7:].strip())
            if agent:
                s = get_state(agent.name)
                print(f"  {agent.name}: {s}")
            else:
                print("  Unknown agent")
            continue

        if text.lower().startswith("/facts "):
            agent = resolve_agent_by_name(text[7:].strip())
            if agent:
                print(f"  {agent.name} facts:", get_facts(agent.name))
            continue

        if text.lower() == "/facts":
            with agents_lock:
                names = list(AGENT_NAMES)
            for name in names:
                print(f"  {name}:", get_facts(name))
            continue

        if text.lower() == "/nicknames":
            with agents_lock:
                agents_snap = list(AGENTS)
            for a in agents_snap:
                print(f"  {a.name}: @{a.name} → queue  |  boosts: {', '.join(a.nicknames)}")
            continue

        if text.lower() == "/reload":
            log.info("Manual reload triggered")
            reload_agents()
            continue

        # ── Local human message (terminal shortcut, mirrors Redis path) ──
        last_human_time = time.time()
        add_to_log("Human", "human", text)
        push_human_echo("Human", text)
        boost_weights_for_message(text)
        enqueue_mentions(text, allow_agent_source=None)
        log.info("Human (terminal): %s", text)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Digital Terrarium v4.1 starting up")

    # Initial agent load
    reload_agents()
    if not AGENTS:
        log.error("No agents loaded from Supabase — check HABITAT_ID and DB contents")
        sys.exit(1)

    # Start background services
    _start_supabase_realtime()

    _start_human_inbox_listener()

    sim_thread = threading.Thread(target=main_loop, daemon=True, name="sim-loop")
    sim_thread.start()

    try:
        input_loop()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down…")
        stop_event.set()
        sim_thread.join(timeout=5)
        log.info("Bye.")
        sys.exit(0)


if __name__ == "__main__":
    main()