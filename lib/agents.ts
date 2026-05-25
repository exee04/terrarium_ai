import supabase from "@/lib/supabase";

// =============================================================================
// Types
// =============================================================================

export interface Agent {
  id: string;
  name: string;
  tag: string | null;
  avatar_url: string | null;
  personality: string;
  model_id: string;
  inference_provider: string;
  vision_enabled: boolean;
  created_by: string;
  created_at: string;
}

export interface AgentNickname {
  id: string;
  agent_id: string;
  nickname: string;
  created_at: string;
}

export interface AgentKeyword {
  id: string;
  agent_id: string;
  keyword: string;
  created_at: string;
}

export interface AgentTrigger {
  id: string;
  agent_id: string;
  phrase: string;
  created_at: string;
}

// Full agent with all related data hydrated
export interface AgentFull extends Agent {
  nicknames: AgentNickname[];
  keywords: AgentKeyword[];
  triggers: AgentTrigger[];
}

// Payload types for create / update
export interface CreateAgentPayload {
  name: string;
  tag: string | null;
  personality: string;
  model_id: string;
  vision_enabled: boolean;
  created_by: string;
}

export interface UpdateAgentPayload {
  agent_id: string;
  name: string;
  tag: string | null;
  personality: string;
  model_id: string;
  vision_enabled: boolean;
}

// =============================================================================
// Avatar helper
// Falls back to a DiceBear initials avatar if avatar_url is null
// =============================================================================

export function resolveAvatar(
  agent: Pick<Agent, "name" | "avatar_url">,
): string {
  if (agent.avatar_url) return agent.avatar_url;
  return `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(agent.name)}`;
}

// =============================================================================
// Agent service
// =============================================================================

export async function getAgents(): Promise<{
  data: Agent[] | null;
  error: string | null;
}> {
  const { data, error } = await supabase.rpc("get_agents");
  if (error) return { data: null, error: error.message };
  return { data: data as Agent[], error: null };
}

export async function createAgent(
  payload: CreateAgentPayload,
): Promise<{ data: Agent | null; error: string | null }> {
  const { data, error } = await supabase.rpc("create_agent", {
    p_name: payload.name,
    p_tag: payload.tag,
    p_personality: payload.personality,
    p_model_id: payload.model_id,
    p_vision_enabled: payload.vision_enabled,
    p_created_by: payload.created_by,
  });
  if (error) return { data: null, error: error.message };
  // rpc returns an array for RETURNS TABLE — grab the first row
  const row = Array.isArray(data) ? data[0] : data;
  return { data: (row as Agent) ?? null, error: null };
}

export async function updateAgent(
  payload: UpdateAgentPayload,
): Promise<{ data: Agent | null; error: string | null }> {
  const { data, error } = await supabase.rpc("update_agent", {
    p_agent_id: payload.agent_id,
    p_name: payload.name,
    p_tag: payload.tag,
    p_personality: payload.personality,
    p_model_id: payload.model_id,
    p_vision_enabled: payload.vision_enabled,
  });
  if (error) return { data: null, error: error.message };
  const row = Array.isArray(data) ? data[0] : data;
  return { data: (row as Agent) ?? null, error: null };
}

export async function deleteAgent(
  agentId: string,
): Promise<{ error: string | null }> {
  const { error } = await supabase.rpc("delete_agent", { p_agent_id: agentId });
  if (error) return { error: error.message };
  return { error: null };
}

// =============================================================================
// Nickname service
// =============================================================================

export async function getAgentNicknames(
  agentId: string,
): Promise<{ data: AgentNickname[] | null; error: string | null }> {
  const { data, error } = await supabase.rpc("get_agent_nicknames", {
    p_agent_id: agentId,
  });
  if (error) return { data: null, error: error.message };
  return { data: data as AgentNickname[], error: null };
}

export async function addAgentNickname(
  agentId: string,
  nickname: string,
): Promise<{ data: AgentNickname | null; error: string | null }> {
  const { data, error } = await supabase.rpc("add_agent_nickname", {
    p_agent_id: agentId,
    p_nickname: nickname,
  });
  if (error) return { data: null, error: error.message };
  const row = Array.isArray(data) ? data[0] : data;
  return { data: (row as AgentNickname) ?? null, error: null };
}

export async function removeAgentNickname(
  nicknameId: string,
): Promise<{ error: string | null }> {
  const { error } = await supabase.rpc("remove_agent_nickname", {
    p_nickname_id: nicknameId,
  });
  if (error) return { error: error.message };
  return { error: null };
}

// =============================================================================
// Keyword service
// =============================================================================

export async function getAgentKeywords(
  agentId: string,
): Promise<{ data: AgentKeyword[] | null; error: string | null }> {
  const { data, error } = await supabase.rpc("get_agent_keywords", {
    p_agent_id: agentId,
  });
  if (error) return { data: null, error: error.message };
  return { data: data as AgentKeyword[], error: null };
}

export async function addAgentKeyword(
  agentId: string,
  keyword: string,
): Promise<{ data: AgentKeyword | null; error: string | null }> {
  const { data, error } = await supabase.rpc("add_agent_keyword", {
    p_agent_id: agentId,
    p_keyword: keyword,
  });
  if (error) return { data: null, error: error.message };
  const row = Array.isArray(data) ? data[0] : data;
  return { data: (row as AgentKeyword) ?? null, error: null };
}

export async function removeAgentKeyword(
  keywordId: string,
): Promise<{ error: string | null }> {
  const { error } = await supabase.rpc("remove_agent_keyword", {
    p_keyword_id: keywordId,
  });
  if (error) return { error: error.message };
  return { error: null };
}

// =============================================================================
// Trigger service
// =============================================================================

export async function getAgentTriggers(
  agentId: string,
): Promise<{ data: AgentTrigger[] | null; error: string | null }> {
  const { data, error } = await supabase.rpc("get_agent_triggers", {
    p_agent_id: agentId,
  });
  if (error) return { data: null, error: error.message };
  return { data: data as AgentTrigger[], error: null };
}

export async function addAgentTrigger(
  agentId: string,
  phrase: string,
): Promise<{ data: AgentTrigger | null; error: string | null }> {
  const { data, error } = await supabase.rpc("add_agent_trigger", {
    p_agent_id: agentId,
    p_phrase: phrase,
  });
  if (error) return { data: null, error: error.message };
  const row = Array.isArray(data) ? data[0] : data;
  return { data: (row as AgentTrigger) ?? null, error: null };
}

export async function removeAgentTrigger(
  triggerId: string,
): Promise<{ error: string | null }> {
  const { error } = await supabase.rpc("remove_agent_trigger", {
    p_trigger_id: triggerId,
  });
  if (error) return { error: error.message };
  return { error: null };
}

// =============================================================================
// Convenience: fetch a fully hydrated agent (agent + all related data)
// =============================================================================

export async function getAgentFull(
  agentId: string,
): Promise<{ data: AgentFull | null; error: string | null }> {
  const [agentsRes, nicknamesRes, keywordsRes, triggersRes] = await Promise.all(
    [
      getAgents(),
      getAgentNicknames(agentId),
      getAgentKeywords(agentId),
      getAgentTriggers(agentId),
    ],
  );

  if (agentsRes.error) return { data: null, error: agentsRes.error };

  const agent = agentsRes.data?.find((a) => a.id === agentId) ?? null;
  if (!agent) return { data: null, error: "Agent not found" };

  return {
    data: {
      ...agent,
      nicknames: nicknamesRes.data ?? [],
      keywords: keywordsRes.data ?? [],
      triggers: triggersRes.data ?? [],
    },
    error: null,
  };
}
