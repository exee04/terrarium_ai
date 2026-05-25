"""
room.py — room config, timing helpers, Supabase realtime agent watcher
"""
from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from config import supabase, ROOM_ID, SLEEP_START_HOUR, SLEEP_END_HOUR
from config import ACTIVE_TIMEOUT_SLOW, ACTIVE_TIMEOUT_IDLE
from config import ACTIVE_DELAY_MULTIPLIER, SLOW_DELAY_MULTIPLIER, IDLE_DELAY_MULTIPLIER

log = logging.getLogger("terrarium")

# ---------------------------------------------------------------------------
# Room config
# ---------------------------------------------------------------------------

@dataclass
class RoomConfig:
    interval_sec:  int  = 60
    context_limit: int  = 20
    is_active:     bool = True


_room_config      = RoomConfig()
_room_config_lock = threading.Lock()


def fetch_room_config() -> RoomConfig:
    try:
        row = (
            supabase.table("rooms")
            .select("interval_sec, context_limit, is_active")
            .eq("id", ROOM_ID)
            .single()
            .execute()
            .data
        )
        return RoomConfig(
            interval_sec=row["interval_sec"],
            context_limit=row["context_limit"],
            is_active=row["is_active"],
        )
    except Exception as exc:
        log.warning("fetch_room_config failed: %s — using cached", exc)
        with _room_config_lock:
            return deepcopy(_room_config)


def get_room_config() -> RoomConfig:
    with _room_config_lock:
        return deepcopy(_room_config)


def refresh_room_config() -> None:
    fresh = fetch_room_config()
    with _room_config_lock:
        global _room_config
        _room_config = fresh

# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def is_sleep_time() -> bool:
    h = datetime.now().hour
    if SLEEP_START_HOUR > SLEEP_END_HOUR:
        return h >= SLEEP_START_HOUR or h < SLEEP_END_HOUR
    return SLEEP_START_HOUR <= h < SLEEP_END_HOUR


# room.py
def current_delay(last_human_time: float) -> int:
    from config import ACTIVE_DELAY_SEC, SLOW_DELAY_SEC, IDLE_DELAY_SEC
    since = time.time() - last_human_time
    if since < ACTIVE_TIMEOUT_SLOW:
        return ACTIVE_DELAY_SEC
    if since < ACTIVE_TIMEOUT_IDLE:
        return SLOW_DELAY_SEC
    return IDLE_DELAY_SEC

# ---------------------------------------------------------------------------
# Supabase realtime — agent hot-reload watcher
# ---------------------------------------------------------------------------

_reload_flag = threading.Event()


def start_agent_watcher() -> None:
    import asyncio
    from supabase import acreate_client
    from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

    async def _listen() -> None:
        async_sb = await acreate_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

        def _flag(_payload: dict) -> None:
            log.info("Realtime: agent/room change detected, scheduling reload")
            _reload_flag.set()

        ch1 = async_sb.channel("room-agents-watch")
        ch1.on_postgres_changes(
            event="*", schema="public", table="room_agents",
            filter=f"room_id=eq.{ROOM_ID}", callback=_flag,
        )
        await ch1.subscribe()

        ch2 = async_sb.channel("agents-watch")
        ch2.on_postgres_changes(event="*", schema="public", table="agents", callback=_flag)
        await ch2.subscribe()

        for tbl in ("agent_nicknames", "agent_keywords", "agent_triggers"):
            ch = async_sb.channel(f"{tbl}-watch")
            ch.on_postgres_changes(event="*", schema="public", table=tbl, callback=_flag)
            await ch.subscribe()

        log.info("Supabase realtime agent watcher active")
        while True:
            await asyncio.sleep(60)

    threading.Thread(
        target=lambda: asyncio.run(_listen()),
        daemon=True, name="sb-realtime",
    ).start()


def get_reload_flag() -> threading.Event:
    return _reload_flag