"""
messaging.py — inbound human messages, outbound push, Pi heartbeat

Human message flow:
  Web path:  frontend INSERT → Supabase realtime → _on_incoming_message()
             → _pending_human → main loop pops it via pop_pending_human()

  Terminal:  input_loop types text → set_pending_human() directly
             → same pop path in main loop
             + also INSERTs to Supabase so the DB stays consistent

Both paths funnel through the same _pending_human slot so the main loop
has exactly ONE place to check.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

from config import (
    supabase, ROOM_ID, TERMINAL_SENDER_ID,
    REDIS_AVAILABLE, _redis, FEED_CHANNEL,
    HEARTBEAT_INTERVAL,
)

log = logging.getLogger("terrarium")

# ---------------------------------------------------------------------------
# Pending human message slot (single-item mailbox)
# ---------------------------------------------------------------------------

_pending_human: dict | None = None
_human_lock    = threading.Lock()

last_human_time: float = 0.0


def set_pending_human(sender: str, sender_id: str, content: str) -> None:
    global _pending_human, last_human_time
    with _human_lock:
        _pending_human = {"sender": sender, "sender_id": sender_id, "content": content}
    last_human_time = time.time()  # ← already here, this is fine ✓


def pop_pending_human() -> dict | None:
    """Read-and-clear the mailbox. Returns None if empty."""
    global _pending_human
    with _human_lock:
        msg, _pending_human = _pending_human, None
    return msg

# ---------------------------------------------------------------------------
# Profile name cache
# ---------------------------------------------------------------------------

_profile_cache: dict[str, str] = {}


def resolve_profile_name(user_id: str) -> str:
    if user_id in _profile_cache:
        return _profile_cache[user_id]
    try:
        row = (
            supabase.table("profiles")
            .select("username")
            .eq("id", user_id)
            .single()
            .execute()
            .data
        )
        name = row["username"] if row else user_id
    except Exception:
        name = user_id
    _profile_cache[user_id] = name
    return name

# ---------------------------------------------------------------------------
# Supabase realtime — human inbox listener
# ---------------------------------------------------------------------------

def _on_incoming_message(payload: dict) -> None:
    log.info("RAW INBOX PAYLOAD: %s", payload)  # ← add this
    """Realtime INSERT callback for the messages table (web path)."""
    record = (payload.get("data") or {}).get("record") or {}    

    if record.get("room_id") != ROOM_ID:
        return
    if record.get("sender_type") != "human":
        return

    content = (record.get("content") or "").strip()
    if not content:
        return

    sender_id   = record.get("sender_id", "")
    sender_name = resolve_profile_name(sender_id)

    # Skip echo of terminal messages we just inserted ourselves
    if sender_id == TERMINAL_SENDER_ID:
        return

    log.info("Human message received (web) — %s: %s", sender_name, content)
    set_pending_human(sender_name, sender_id, content)


def start_human_inbox_listener() -> None:
    import asyncio
    from supabase import acreate_client
    from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

    async def _listen() -> None:
        async_sb = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        channel  = async_sb.channel("messages-inbox")
        channel.on_postgres_changes(
            event="INSERT",
            schema="public",
            table="messages",
            filter=f"room_id=eq.{ROOM_ID}",
            callback=_on_incoming_message,
        )
        await channel.subscribe()
        log.info("Human inbox listener subscribed (room %s)", ROOM_ID)
        while True:
            await asyncio.sleep(60)

    threading.Thread(
        target=lambda: asyncio.run(_listen()),
        daemon=True, name="human-inbox",
    ).start()

# ---------------------------------------------------------------------------
# Terminal → Supabase insert
# ---------------------------------------------------------------------------

def insert_terminal_message(content: str) -> None:
    """Write a terminal human message to the messages table."""
    try:
        supabase.table("messages").insert({
            "room_id":     ROOM_ID,
            "sender_type": "human",
            "sender_id":   TERMINAL_SENDER_ID,
            "content":     content,
        }).execute()
    except Exception as exc:
        log.warning("Terminal message DB insert failed: %s", exc)

# ---------------------------------------------------------------------------
# Push agent message outward
# ---------------------------------------------------------------------------

_failed_messages: list[dict] = []

def push_agent_message(agent, content: str, patch: dict) -> None:
    payload = {
        "room_id": ROOM_ID,
        "sender_type": "agent",
        "sender_id": agent.id,
        "content": content,
    }
    # retry any previously failed messages first
    global _failed_messages
    still_failed = []
    for msg in _failed_messages:
        try:
            supabase.table("messages").insert(msg).execute()
        except Exception:
            still_failed.append(msg)
    _failed_messages = still_failed

    try:
        supabase.table("messages").insert(payload).execute()
    except Exception as exc:
        log.warning("Agent message DB insert failed: %s", exc)
        _failed_messages.append(payload)

def publish_to_feed(payload: dict) -> None:
    if not REDIS_AVAILABLE:
        return
    try:
        _redis.publish(FEED_CHANNEL, json.dumps(payload))
    except Exception as exc:
        log.debug("Redis publish: %s", exc)

# ---------------------------------------------------------------------------
# Pi heartbeat
# ---------------------------------------------------------------------------

def heartbeat_loop() -> None:
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        try:
            supabase.table("rooms").update({
                "pi_last_heartbeat": datetime.now(timezone.utc).isoformat()
            }).eq("id", ROOM_ID).execute()
            log.debug("Heartbeat sent")
        except Exception as exc:
            log.warning("Heartbeat failed: %s", exc)