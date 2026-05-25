/**
 * lib/habitat_service.ts
 */

import supabase from "@/lib/supabase";
import type { Agent } from "@/lib/agents";

export interface HabitatMessage {
  id: string;
  room_id: string;
  sender_type: "agent" | "human";
  sender_id: string;
  content: string;
  created_at: string;
}

export type AgentMap = Record<string, Agent>;

// ── Messages ───────────────────────────────────────────────────────────────

export async function fetchRecentMessages(
  roomId: string,
  limit = 100,
): Promise<{ data: HabitatMessage[] | null; error: string | null }> {
  const { data, error } = await supabase
    .from("messages")
    .select("*")
    .eq("room_id", roomId)
    .order("created_at", { ascending: false }) // newest first
    .limit(limit);

  if (error) return { data: null, error: error.message };
  // reverse so oldest is at top in the feed
  return { data: (data as HabitatMessage[]).reverse(), error: null };
}
export async function sendHumanMessage(
  roomId: string,
  senderId: string,
  content: string,
): Promise<{ data: HabitatMessage | null; error: string | null }> {
  const { data, error } = await supabase
    .from("messages")
    .insert({
      room_id: roomId,
      sender_type: "human",
      sender_id: senderId,
      content: content.trim(),
    })
    .select()
    .single();

  if (error) return { data: null, error: error.message };
  return { data: data as HabitatMessage, error: null };
}

export function subscribeToMessages(
  roomId: string,
  onMessage: (msg: HabitatMessage) => void,
): () => void {
  const channel = supabase
    .channel(`habitat-messages:${roomId}`)
    .on(
      "postgres_changes",
      {
        event: "INSERT",
        schema: "public",
        table: "messages",
        filter: `room_id=eq.${roomId}`,
      },
      (payload) => onMessage(payload.new as HabitatMessage),
    )
    .subscribe();

  return () => {
    supabase.removeChannel(channel);
  };
}

// ── Agent state / moods ────────────────────────────────────────────────────

/**
 * Returns a map of agent_id → mood string.
 */
export async function fetchAgentStates(): Promise<Record<string, string>> {
  const { data, error } = await supabase
    .from("agent_state")
    .select("agent_id, state");

  if (error || !data) return {};

  const map: Record<string, string> = {};
  for (const row of data) {
    map[row.agent_id] = row.state?.mood ?? "";
  }
  return map;
}

// ── Profiles ───────────────────────────────────────────────────────────────

const _profileCache: Record<string, string> = {};

/**
 * Fetch a display name for a user ID from the profiles table.
 * Returns the user_id string as fallback if not found.
 */
export async function fetchProfileName(userId: string): Promise<string> {
  if (_profileCache[userId]) return _profileCache[userId];

  try {
    const { data } = await supabase
      .from("profiles")
      .select("username")
      .eq("id", userId)
      .single();

    const name = data?.username ?? userId;
    _profileCache[userId] = name;
    return name;
  } catch {
    return userId;
  }
}

// ── Auth ───────────────────────────────────────────────────────────────────

export async function getCurrentUserId(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.user.id ?? "00000000-0000-0000-0000-000000000000";
}
