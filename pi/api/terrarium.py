"""
terrarium.py — Digital Terrarium v4.3
Entry point. Wires up all modules and runs the input loop.

Architecture:
  config.py       — env vars, constants, shared Supabase/Redis clients
  agents.py       — agent registry, hot-reload, weights, @mention queue
  state.py        — emotional state, facts, Supabase persistence
  conversation.py — in-memory log, prompt builder, LLM call
  messaging.py    — human message intake, push outward, heartbeat
  room.py         — room config, timing, realtime agent watcher
  loop.py         — main simulation loop

Controls (stdin / SSH):
  @Name       → guaranteed reply next turn
  /states     → print all emotional states
  /state NAME → print one agent's state
  /facts      → print all known facts
  /facts NAME → print one agent's facts
  /nicknames  → list agent nicknames
  /reload     → force agent reload
  Ctrl+C      → graceful shutdown
"""
from __future__ import annotations

import logging
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("terrarium")

# Import after logging is configured so module-level log calls work
from config import ROOM_ID
from agents import (
    reload_agents, AGENTS, AGENT_NAMES, agents_lock,
    resolve_agent_by_name, boost_weights_for_message, enqueue_mentions,
)
from state import get_state, get_facts, load_agent_states
from messaging import (
    set_pending_human, insert_terminal_message,
    start_human_inbox_listener, heartbeat_loop,
)
from room import start_agent_watcher
from loop import main_loop, stop_event
from config import TERMINAL_SENDER_ID


# ---------------------------------------------------------------------------
# Input loop (terminal / SSH)
# ---------------------------------------------------------------------------

def input_loop() -> None:
    while not stop_event.is_set():
        try:
            text = input()
        except EOFError:
            break

        text = text.strip()
        if not text:
            continue

        # ── Commands ──────────────────────────────────────────────────────
        if text.lower() == "/states":
            with agents_lock:
                names = list(AGENT_NAMES)
            for name in names:
                s = get_state(name)
                print(f"  {name}: mood={s['mood']}  rels={s['relations']}  mem={s['memory']}")
            continue

        if text.lower().startswith("/state "):
            a = resolve_agent_by_name(text[7:].strip())
            print(f"  {a.name}: {get_state(a.name)}" if a else "  Unknown agent")
            continue

        if text.lower() == "/facts":
            with agents_lock:
                names = list(AGENT_NAMES)
            for name in names:
                print(f"  {name}: {get_facts(name)}")
            continue

        if text.lower().startswith("/facts "):
            a = resolve_agent_by_name(text[7:].strip())
            if a:
                print(f"  {a.name}: {get_facts(a.name)}")
            continue

        if text.lower() == "/nicknames":
            with agents_lock:
                snap = list(AGENTS)
            for a in snap:
                print(f"  {a.name}: @{a.name} → queue  |  boosts: {', '.join(a.nicknames)}")
            continue

        if text.lower() == "/reload":
            fresh = reload_agents()
            if fresh:
                load_agent_states(fresh)
            continue        # ← was missing, causing fallthrough to human message


        # ── Human message ─────────────────────────────────────────────────
        # 1. Put in the mailbox so the main loop picks it up immediately
        set_pending_human("Terminal", TERMINAL_SENDER_ID, text)
        # 2. Write to Supabase for DB consistency
        insert_terminal_message(text)
        # 3. Boost weights now (main loop will also call this when it pops,
        #    but doing it here makes @mention queueing instant)
        boost_weights_for_message(text)
        enqueue_mentions(text, allow_agent_source=None)
        log.info("Terminal human: %s", text)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Digital Terrarium v4.3 starting (room %s)", ROOM_ID)

    fresh = reload_agents()
    if not fresh:                    # ← check return value, not imported name
        log.error("No agents found for room %s — check room_agents table", ROOM_ID)
        sys.exit(1)
    load_agent_states(fresh)

    start_agent_watcher()
    start_human_inbox_listener()
    threading.Thread(target=heartbeat_loop, daemon=True, name="heartbeat").start()
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