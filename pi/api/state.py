"""
state.py — per-agent emotional state, facts, persistence to agent_state table
"""
from __future__ import annotations

import logging
import threading
from copy import deepcopy
from datetime import datetime, timezone

from config import supabase, MOOD_VOCAB, RELATIONAL_VOCAB, OPINION_VOCAB, MOOD_DECAY_TURNS

log = logging.getLogger("terrarium")

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

emotional_states: dict[str, dict] = {}
states_lock = threading.Lock()

known_facts: dict[str, list[str]] = {}
facts_lock  = threading.Lock()

# ---------------------------------------------------------------------------
# Default + CRUD
# ---------------------------------------------------------------------------

def make_default_state() -> dict:
    return {
        "mood": "neutral",
        "mood_turns_remaining": 0,
        "relations": {},
        "opinions": {},
        "memory": None,
    }


def ensure_state(name: str) -> None:
    with states_lock:
        if name not in emotional_states:
            emotional_states[name] = make_default_state()


def get_state(name: str) -> dict:
    with states_lock:
        if name not in emotional_states:
            emotional_states[name] = make_default_state()
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

# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# State → English summary (injected into prompts)
# ---------------------------------------------------------------------------

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
# Supabase persistence
# ---------------------------------------------------------------------------

def load_agent_states(agents: list) -> None:
    """Pull persisted states from agent_state table on startup / reload."""
    ids = [a.id for a in agents]
    if not ids:
        return
    try:
        rows = (
            supabase.table("agent_state")
            .select("agent_id, state")
            .in_("agent_id", ids)
            .execute()
            .data or []
        )
    except Exception as exc:
        log.warning("load_agent_states failed: %s", exc)
        return

    id_to_name = {a.id: a.name for a in agents}
    for row in rows:
        name = id_to_name.get(row["agent_id"])
        if name and isinstance(row.get("state"), dict):
            with states_lock:
                emotional_states[name] = row["state"]
            log.debug("Loaded persisted state for %s", name)


def persist_agent_state(agent) -> None:
    """Upsert current in-memory state to agent_state table (best-effort)."""
    state = get_state(agent.name)
    try:
        supabase.table("agent_state").upsert({
            "agent_id":   agent.id,
            "state":      state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        log.debug("persist_agent_state failed for %s: %s", agent.name, exc)