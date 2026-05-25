import supabase from "@/lib/supabase";

export interface PiStatus {
  temp_c: number | null;
  uptime_sec: number | null;
  rpd_remaining: number | null;
  rpd_limit: number | null;
  tokens_used_today: number | null;
  updated_at: string | null;
}

const EMPTY: PiStatus = {
  temp_c: null,
  uptime_sec: null,
  rpd_remaining: null,
  rpd_limit: null,
  tokens_used_today: null,
  updated_at: null,
};

export async function fetchPiStatus(): Promise<PiStatus> {
  const { data, error } = await supabase.rpc("get_pi_status");
  if (error || !data?.length) return EMPTY;
  return data[0] as PiStatus;
}
