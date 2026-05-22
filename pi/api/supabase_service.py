from supabase import create_client, Client
from datetime import datetime, timezone
from uuid import UUID

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY
from supabase_models import (
    Agent, Room, Message, AgentMemory, AgentTurn, RoomAgent,
    AgentContext,
    agent_from_row, room_from_row, message_from_row,
    agent_memory_from_row, agent_turn_from_row,
)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

# Service key bypasses RLS — safe for the Pi cron worker (never exposed to browser)
_client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

def get_active_rooms() -> list[Room]:
    """Fetch all rooms where is_active = true."""
    rows = (
        _client.table("rooms")
        .select("*")
        .eq("is_active", True)
        .execute()
        .data
    )
    return [room_from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def get_room_agents(room_id: UUID) -> list[Agent]:
    """Fetch agents assigned to a room, ordered by turn_order."""
    rows = (
        _client.table("room_agents")
        .select("agent_id, turn_order, agents(*)")
        .eq("room_id", str(room_id))
        .order("turn_order")
        .execute()
        .data
    )
    return [agent_from_row(r["agents"]) for r in rows]


def get_next_agent(room_id: UUID) -> Agent | None:
    """
    Determine whose turn it is.
    Picks the agent in this room with the oldest last_response_at
    (or NULL — never responded yet), respecting turn_order as tiebreaker.
    """
    rows = (
        _client.table("agent_turns")
        .select("agent_id, last_response_at, turn_order:room_agents(turn_order)")
        .eq("room_id", str(room_id))
        .order("last_response_at", nullsfirst=True)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        # No turn records yet — fall back to first agent by turn_order
        agents = get_room_agents(room_id)
        return agents[0] if agents else None

    agent_id = rows[0]["agent_id"]
    agent_row = (
        _client.table("agents")
        .select("*")
        .eq("id", agent_id)
        .single()
        .execute()
        .data
    )
    return agent_from_row(agent_row)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def get_recent_messages(room_id: UUID, limit: int) -> list[Message]:
    """Fetch the last N messages in a room, returned oldest-first."""
    rows = (
        _client.table("messages")
        .select("*")
        .eq("room_id", str(room_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
    )
    rows.reverse()  # oldest first for prompt building
    return [message_from_row(r) for r in rows]


def insert_message(room_id: UUID, agent_id: UUID, content: str) -> Message:
    """Insert an agent message and return the created row."""
    row = (
        _client.table("messages")
        .insert({
            "room_id": str(room_id),
            "sender_type": "agent",
            "sender_id": str(agent_id),
            "content": content,
        })
        .execute()
        .data[0]
    )
    return message_from_row(row)


# ---------------------------------------------------------------------------
# Agent turns
# ---------------------------------------------------------------------------

def upsert_agent_turn(room_id: UUID, agent_id: UUID) -> None:
    """
    Update last_response_at and increment total_messages.
    Uses an RPC so the increment is atomic — no read-modify-write race.
    """
    _client.rpc(
        "upsert_agent_turn",
        {"p_room_id": str(room_id), "p_agent_id": str(agent_id)},
    ).execute()


# ---------------------------------------------------------------------------
# Agent memory
# ---------------------------------------------------------------------------

def get_latest_memory(room_id: UUID, agent_id: UUID) -> AgentMemory | None:
    """Fetch the most recent summary for this agent+room pair."""
    rows = (
        _client.table("agent_memory")
        .select("*")
        .eq("room_id", str(room_id))
        .eq("agent_id", str(agent_id))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return agent_memory_from_row(rows[0]) if rows else None


def count_unsummarized_messages(
    room_id: UUID, since: datetime | None
) -> int:
    """
    Count messages in the room after `since`.
    If since is None (no memory exists yet) counts all messages.
    """
    query = (
        _client.table("messages")
        .select("id", count="exact")
        .eq("room_id", str(room_id))
    )
    if since:
        query = query.gt("created_at", since.isoformat())

    return query.execute().count or 0


def insert_agent_memory(
    agent_id: UUID,
    room_id: UUID,
    summary: str,
    message_count: int,
    range_start: datetime,
    range_end: datetime,
) -> AgentMemory:
    """Persist a new compressed memory summary."""
    row = (
        _client.table("agent_memory")
        .insert({
            "agent_id": str(agent_id),
            "room_id": str(room_id),
            "summary": summary,
            "message_count": message_count,
            "message_range_start": range_start.isoformat(),
            "message_range_end": range_end.isoformat(),
        })
        .execute()
        .data[0]
    )
    return agent_memory_from_row(row)


# ---------------------------------------------------------------------------
# AgentContext assembly — the main thing the cron worker calls
# ---------------------------------------------------------------------------

def build_agent_context(room: Room, agent: Agent) -> AgentContext:
    """
    Pull everything needed for one agent turn and return it as AgentContext.
    This is the single DB-heavy call the cron loop makes per turn.
    """
    latest_memory = get_latest_memory(room.id, agent.id)
    recent_messages = get_recent_messages(room.id, limit=room.context_limit)
    unsummarized_count = count_unsummarized_messages(
        room.id,
        since=latest_memory.message_range_end if latest_memory else None,
    )

    return AgentContext(
        agent=agent,
        room=room,
        latest_memory=latest_memory,
        recent_messages=recent_messages,
        unsummarized_count=unsummarized_count,
    )