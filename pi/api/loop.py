"""
loop.py — main simulation loop
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import httpx

from config import ROOM_ID, TYPING_GRACE
from agents import (
    reload_agents, AGENTS, AGENT_NAMES, agents_lock,
    pick_next_agent, dequeue_next,
    decay_weights, decay_at_cooldowns,
    boost_weights_for_message, enqueue_mentions, penalise_agent,
)
from conversation import add_to_log, call_fastapi
from messaging import (
    pop_pending_human, publish_to_feed, push_agent_message,
    last_human_time as _lht_ref,
    set_pending_human,
)
from room import refresh_room_config, get_room_config, is_sleep_time, current_delay, get_reload_flag
from state import (
    get_state, set_state, decay_mood, apply_state_patch, persist_agent_state,
    load_agent_states,
)

log = logging.getLogger("terrarium")
stop_event = threading.Event()

# ---------------------------------------------------------------------------
# Helpers to keep last_human_time writable from this module
# ---------------------------------------------------------------------------
import messaging as _msg_mod


def _get_last_human_time() -> float:
    return _msg_mod.last_human_time


def _set_last_human_time(t: float) -> None:
    _msg_mod.last_human_time = t

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main_loop() -> None:
    log.info("Main loop started (room %s)", ROOM_ID)
    try:
        _main_loop_inner()
    except Exception as exc:
        log.exception("Main loop CRASHED: %s", exc)
def _main_loop_inner() -> None:
    log.info("Main loop started (room %s)", ROOM_ID)
    reload_flag = get_reload_flag()

    while not stop_event.is_set():

        # ── 1. Room config ────────────────────────────────────────────────
        refresh_room_config()
        cfg = get_room_config()

        if not cfg.is_active:
            log.debug("Room is_active=false — pausing 30s")
            time.sleep(30)
            continue

        # ── 2. Hot-reload agents ──────────────────────────────────────────
        if reload_flag.is_set():
            reload_flag.clear()
            log.info("Hot-reloading agents…")
            fresh = reload_agents()
            if fresh:
                load_agent_states(fresh)

        # ── 3. Sleep gate ─────────────────────────────────────────────────
        if is_sleep_time():
            log.debug("Sleep window — pausing 60s")
            time.sleep(60)
            continue

        # ── 4. Interruptible countdown ────────────────────────────────────
        remaining = current_delay(_get_last_human_time())

        while remaining > 0 and not stop_event.is_set():

            # Hot-reload inside countdown
            if reload_flag.is_set():
                reload_flag.clear()
                fresh = reload_agents()
                if fresh:
                    load_agent_states(fresh)

            # Check for incoming human message
            human_msg = pop_pending_human()
            if human_msg:
                content   = human_msg["content"]
                sender    = human_msg["sender"]
                sender_id = human_msg["sender_id"]

                add_to_log(sender, "human", sender_id, content)
                publish_to_feed({
                    "room_id":     ROOM_ID,
                    "sender_name": sender,
                    "sender_type": "human",
                    "sender_id":   sender_id,
                    "content":     content,
                    "timestamp":   datetime.now(timezone.utc).isoformat(),
                })
                boost_weights_for_message(content)
                enqueue_mentions(content, allow_agent_source=None)
                _set_last_human_time(time.time())
                remaining = TYPING_GRACE
                log.info("Human message ingested — grace window %ds", TYPING_GRACE)

            time.sleep(1)
            remaining -= 1

        if stop_event.is_set():
            break

        # ── 5. Agent selection ────────────────────────────────────────────
        decay_weights()
        decay_at_cooldowns()

        queued = dequeue_next()
        try:
            agent = queued if queued else pick_next_agent()
        except RuntimeError:
            log.warning("No agents available — waiting 10s")
            time.sleep(10)
            continue

        log.info("%sTurn: %s", "@→ " if queued else "", agent.name)

        # ── 6. LLM call ───────────────────────────────────────────────────
        with agents_lock:
            agent_names = AGENT_NAMES.copy()

        try:
            reply, patch, elapsed = call_fastapi(agent, agent_names, cfg.context_limit)
        except httpx.HTTPStatusError as exc:
            wait = 30 if exc.response.status_code == 429 else 5
            log.warning("FastAPI HTTP %d for %s — waiting %ds", exc.response.status_code, agent.name, wait)
            time.sleep(wait)
            continue
        except httpx.TimeoutException:
            log.warning("FastAPI timeout for %s — skipping", agent.name)
            continue
        except Exception as exc:
            log.error("Unexpected LLM error: %s", exc)
            time.sleep(5)
            continue

        if not reply:
            log.warning("%s returned empty reply — skipping", agent.name)
            continue

        log.info("%s (%.1fs): %s", agent.name, elapsed, reply)

        # ── 7. State update ───────────────────────────────────────────────
        set_state(agent.name, decay_mood(get_state(agent.name)))
        if patch:
            apply_state_patch(agent.name, patch)
        persist_agent_state(agent)

        # ── 8. Log + bookkeeping ──────────────────────────────────────────
        add_to_log(agent.name, "agent", agent.id, reply, state_patch=patch)
        enqueue_mentions(reply, allow_agent_source=agent.name)
        boost_weights_for_message(reply)
        penalise_agent(agent.name)

        # ── 9. Push to Supabase + Redis ───────────────────────────────────
        push_agent_message(agent, reply, patch)