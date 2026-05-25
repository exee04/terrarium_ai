"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "@/app/providers";
import {
  type Agent,
  type AgentFull,
  getAgents,
  createAgent,
  updateAgent,
  deleteAgent,
  getAgentFull,
  addAgentNickname,
  removeAgentNickname,
  addAgentKeyword,
  removeAgentKeyword,
  addAgentTrigger,
  removeAgentTrigger,
  resolveAvatar,
} from "@/lib/agents";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PiStatus {
  temp_c: number | null;
  uptime_sec: number | null;
  rpd_remaining: number | null;
  rpd_limit: number | null;
  updated_at: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatUptime(sec: number | null): string {
  if (sec === null) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function formatTemp(c: number | null): string {
  if (c === null) return "—";
  return `${c.toFixed(1)}°C`;
}

function tempColor(c: number | null): string {
  if (c === null) return "#3d4035";
  if (c >= 80) return "#ef4444";
  if (c >= 70) return "#ca8a04";
  return "#3d4035";
}

function rpdPercent(remaining: number | null, limit: number | null): number {
  if (!remaining || !limit) return 0;
  return Math.round(((limit - remaining) / limit) * 100);
}

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

// ---------------------------------------------------------------------------
// Mock Pi data — replace with real Pi heartbeat later
// ---------------------------------------------------------------------------

const MOCK_PI: PiStatus = {
  temp_c: 67.4,
  uptime_sec: 14523,
  rpd_remaining: 11840,
  rpd_limit: 14400,
  updated_at: new Date(Date.now() - 18000).toISOString(),
};

const MOCK_ACTIVE_USERS = 7;

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const S = {
  page: {
    minHeight: "100vh",
    backgroundColor: "var(--color-bg-primary, #fafaf8)",
    color: "#3d4035",
    fontFamily: "inherit",
  } as React.CSSProperties,

  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    borderBottom: "1px solid #D1D8BE",
    padding: "24px 32px",
  } as React.CSSProperties,

  body: {
    padding: "24px 32px",
    display: "flex",
    flexDirection: "column" as const,
    gap: "32px",
  } as React.CSSProperties,

  sectionLabel: {
    fontFamily: "monospace",
    fontSize: "9px",
    letterSpacing: "0.2em",
    textTransform: "uppercase" as const,
    color: "#c5c9b8",
    marginBottom: "16px",
  } as React.CSSProperties,

  statGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, 1fr)",
    gap: "16px",
  } as React.CSSProperties,

  statCard: {
    backgroundColor: "var(--color-bg-primary, #fafaf8)",
    border: "1px solid #D1D8BE",
    padding: "16px 20px",
  } as React.CSSProperties,

  statLabel: {
    fontFamily: "monospace",
    fontSize: "9px",
    letterSpacing: "0.2em",
    textTransform: "uppercase" as const,
    color: "#5a5f50",
    marginBottom: "8px",
  } as React.CSSProperties,

  statValue: {
    fontSize: "24px",
    fontWeight: 300,
    letterSpacing: "-0.025em",
    color: "#3d4035",
  } as React.CSSProperties,

  statSub: {
    fontFamily: "monospace",
    fontSize: "9px",
    letterSpacing: "0.2em",
    textTransform: "uppercase" as const,
    color: "#c5c9b8",
    marginTop: "4px",
  } as React.CSSProperties,

  inputStyle: {
    width: "100%",
    borderBottom: "1px solid #819A91",
    background: "transparent",
    padding: "12px 4px",
    fontSize: "14px",
    color: "#3d4035",
    outline: "none",
    boxSizing: "border-box" as const,
  } as React.CSSProperties,

  labelStyle: {
    display: "block",
    fontFamily: "monospace",
    fontSize: "9px",
    letterSpacing: "0.2em",
    textTransform: "uppercase" as const,
    color: "#5a5f50",
    marginBottom: "8px",
  } as React.CSSProperties,
} as const;

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------

function StatCard({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div style={S.statCard}>
      <p style={S.statLabel}>{label}</p>
      <p style={{ ...S.statValue, color: valueColor ?? "#3d4035" }}>{value}</p>
      {sub && <p style={S.statSub}>{sub}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RpdProgressBar
// ---------------------------------------------------------------------------

function RpdProgressBar({
  remaining,
  limit,
}: {
  remaining: number | null;
  limit: number | null;
}) {
  const used = rpdPercent(remaining, limit);
  const free = 100 - used;
  const barColor = used > 85 ? "#f87171" : used > 60 ? "#eab308" : "#819A91";
  const statusLabel =
    used > 85 ? "⚠ near limit" : used > 60 ? "moderate usage" : "healthy";

  return (
    <div
      style={{
        backgroundColor: "var(--color-bg-primary, #fafaf8)",
        border: "1px solid #D1D8BE",
        padding: "16px 20px",
        marginTop: "16px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: "12px",
        }}
      >
        <p style={S.statLabel}>Groq RPD</p>
        <span style={{ ...S.statSub, marginBottom: 0, marginTop: 0 }}>
          {statusLabel}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: "12px",
        }}
      >
        <p style={S.statValue}>
          {remaining?.toLocaleString() ?? "—"}
          <span
            style={{
              ...S.statSub,
              marginTop: 0,
              marginLeft: "6px",
              display: "inline",
            }}
          >
            remaining
          </span>
        </p>
        <span
          style={{
            fontFamily: "monospace",
            fontSize: "12px",
            color: "#5a5f50",
          }}
        >
          {limit?.toLocaleString() ?? "—"} limit
        </span>
      </div>
      <div
        style={{
          position: "relative",
          height: "12px",
          width: "100%",
          backgroundColor: "#e8ece0",
          borderRadius: "2px",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            height: "100%",
            width: `${used}%`,
            backgroundColor: barColor,
            transition: "width 0.7s ease",
          }}
        />
        {[25, 50, 75].map((pct) => (
          <div
            key={pct}
            style={{
              position: "absolute",
              top: 0,
              left: `${pct}%`,
              height: "100%",
              width: "1px",
              backgroundColor: "rgba(255,255,255,0.4)",
            }}
          />
        ))}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: "8px",
        }}
      >
        <p style={S.statSub}>{used}% used</p>
        <p style={S.statSub}>{free}% free</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TagChips — reusable chip list with add/remove
// ---------------------------------------------------------------------------

function TagChips({
  label,
  items,
  onAdd,
  onRemove,
  placeholder,
}: {
  label: string;
  items: { id: string; value: string }[];
  onAdd: (value: string) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
  placeholder: string;
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleAdd() {
    const val = input.trim();
    if (!val) return;
    setLoading(true);
    await onAdd(val);
    setInput("");
    setLoading(false);
  }

  return (
    <div>
      <label style={S.labelStyle}>{label}</label>
      {/* Chip list */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "6px",
          marginBottom: "8px",
        }}
      >
        {items.length === 0 && (
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "9px",
              color: "#c5c9b8",
              textTransform: "uppercase",
              letterSpacing: "0.1em",
            }}
          >
            none yet
          </span>
        )}
        {items.map((item) => (
          <div
            key={item.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "4px",
              backgroundColor: "#e8ece0",
              padding: "4px 8px",
            }}
          >
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "10px",
                color: "#3d4035",
              }}
            >
              {item.value}
            </span>
            <button
              onClick={() => onRemove(item.id)}
              style={{
                fontFamily: "monospace",
                fontSize: "9px",
                color: "#c5c9b8",
                background: "none",
                border: "none",
                cursor: "pointer",
                lineHeight: 1,
                padding: 0,
              }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      {/* Add input */}
      <div style={{ display: "flex", gap: "8px" }}>
        <input
          style={{ ...S.inputStyle, flex: 1 }}
          placeholder={placeholder}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          disabled={loading}
        />
        <button
          onClick={handleAdd}
          disabled={loading || !input.trim()}
          style={{
            padding: "8px 16px",
            fontFamily: "monospace",
            fontSize: "9px",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "white",
            backgroundColor: loading ? "#c5c9b8" : "#819A91",
            border: "none",
            cursor: loading ? "default" : "pointer",
          }}
        >
          Add
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AgentRow
// ---------------------------------------------------------------------------

function AgentRow({
  agent,
  onEdit,
  onDelete,
}: {
  agent: Agent;
  onEdit: (a: Agent) => void;
  onDelete: (id: string) => void;
}) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "16px 20px",
        backgroundColor: hovered ? "#f3f4ee" : "transparent",
        transition: "background-color 0.15s ease",
      }}
    >
      {/* Left */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "16px",
          minWidth: 0,
        }}
      >
        <img
          src={resolveAvatar(agent)}
          alt={agent.name}
          style={{
            width: "32px",
            height: "32px",
            borderRadius: "50%",
            border: "1px solid #D1D8BE",
            flexShrink: 0,
            objectFit: "cover",
          }}
        />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "12px",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: "#3d4035",
              }}
            >
              {agent.name}
            </span>
            {agent.vision_enabled && (
              <span
                style={{
                  border: "1px solid #A7C1A8",
                  padding: "2px 6px",
                  fontFamily: "monospace",
                  fontSize: "9px",
                  letterSpacing: "0.2em",
                  textTransform: "uppercase",
                  color: "#819A91",
                }}
              >
                vision
              </span>
            )}
          </div>
          {agent.tag && (
            <p
              style={{
                fontFamily: "monospace",
                fontSize: "9px",
                letterSpacing: "0.2em",
                textTransform: "uppercase",
                color: "#c5c9b8",
                marginTop: "2px",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {agent.tag}
            </p>
          )}
        </div>
      </div>

      {/* Right */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "16px",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontFamily: "monospace",
            fontSize: "9px",
            letterSpacing: "0.2em",
            textTransform: "uppercase",
            color: "#c5c9b8",
          }}
        >
          {agent.model_id}
        </span>
        <button
          onClick={() => onEdit(agent)}
          style={{
            fontFamily: "monospace",
            fontSize: "9px",
            letterSpacing: "0.2em",
            textTransform: "uppercase",
            color: "#5a5f50",
            background: "none",
            border: "none",
            cursor: "pointer",
          }}
        >
          Edit
        </button>
        <button
          onClick={() => onDelete(agent.id)}
          style={{
            fontFamily: "monospace",
            fontSize: "9px",
            letterSpacing: "0.2em",
            textTransform: "uppercase",
            color: "#c5c9b8",
            background: "none",
            border: "none",
            cursor: "pointer",
          }}
        >
          Remove
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AgentModal
// ---------------------------------------------------------------------------

function AgentModal({
  agent,
  onClose,
  onSaved,
}: {
  agent: Agent | null; // null = new agent
  onClose: () => void;
  onSaved: () => void; // tells parent to re-fetch
}) {
  const { session } = useAuth();
  const isNew = !agent?.id;

  const [form, setForm] = useState({
    name: agent?.name ?? "",
    tag: agent?.tag ?? "",
    personality: agent?.personality ?? "",
    model_id: agent?.model_id ?? "llama-3.1-8b-instant",
    vision_enabled: agent?.vision_enabled ?? false,
  });

  const [full, setFull] = useState<AgentFull | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Hydrate sub-lists when editing an existing agent
  useEffect(() => {
    if (!agent?.id) return;
    setLoading(true);
    getAgentFull(agent.id).then(({ data, error }) => {
      if (error) setError(error);
      else setFull(data);
      setLoading(false);
    });
  }, [agent?.id]);

  function setField(key: keyof typeof form, value: unknown) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSave() {
    if (!form.name.trim() || !form.personality.trim()) {
      setError("Name and personality are required.");
      return;
    }
    setSaving(true);
    setError(null);

    if (isNew) {
      const { error } = await createAgent({
        name: form.name.trim(),
        tag: form.tag.trim() || null,
        personality: form.personality.trim(),
        model_id: form.model_id,
        vision_enabled: form.vision_enabled,
        created_by: session!.user.id,
      });
      if (error) {
        setError(error);
        setSaving(false);
        return;
      }
    } else {
      const { error } = await updateAgent({
        agent_id: agent!.id,
        name: form.name.trim(),
        tag: form.tag.trim() || null,
        personality: form.personality.trim(),
        model_id: form.model_id,
        vision_enabled: form.vision_enabled,
      });
      if (error) {
        setError(error);
        setSaving(false);
        return;
      }
    }

    setSaving(false);
    onSaved();
    onClose();
  }

  // Sub-list handlers — only available when editing an existing agent
  async function handleAddNickname(value: string) {
    if (!full) return;
    const { data, error } = await addAgentNickname(full.id, value);
    if (error) {
      setError(error);
      return;
    }
    if (data)
      setFull((f) => (f ? { ...f, nicknames: [...f.nicknames, data] } : f));
  }

  async function handleRemoveNickname(id: string) {
    const { error } = await removeAgentNickname(id);
    if (error) {
      setError(error);
      return;
    }
    setFull((f) =>
      f ? { ...f, nicknames: f.nicknames.filter((n) => n.id !== id) } : f,
    );
  }

  async function handleAddKeyword(value: string) {
    if (!full) return;
    const { data, error } = await addAgentKeyword(full.id, value);
    if (error) {
      setError(error);
      return;
    }
    if (data)
      setFull((f) => (f ? { ...f, keywords: [...f.keywords, data] } : f));
  }

  async function handleRemoveKeyword(id: string) {
    const { error } = await removeAgentKeyword(id);
    if (error) {
      setError(error);
      return;
    }
    setFull((f) =>
      f ? { ...f, keywords: f.keywords.filter((k) => k.id !== id) } : f,
    );
  }

  async function handleAddTrigger(value: string) {
    if (!full) return;
    const { data, error } = await addAgentTrigger(full.id, value);
    if (error) {
      setError(error);
      return;
    }
    if (data)
      setFull((f) => (f ? { ...f, triggers: [...f.triggers, data] } : f));
  }

  async function handleRemoveTrigger(id: string) {
    const { error } = await removeAgentTrigger(id);
    if (error) {
      setError(error);
      return;
    }
    setFull((f) =>
      f ? { ...f, triggers: f.triggers.filter((t) => t.id !== id) } : f,
    );
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "rgba(61,64,53,0.4)",
        backdropFilter: "blur(4px)",
      }}
    >
      <div
        style={{
          backgroundColor: "var(--color-bg-primary, #fafaf8)",
          margin: "0 16px",
          maxHeight: "90vh",
          width: "100%",
          maxWidth: "512px",
          overflowY: "auto",
          border: "1px solid #D1D8BE",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottom: "1px solid #D1D8BE",
            padding: "16px 20px",
          }}
        >
          <p
            style={{
              fontFamily: "monospace",
              fontSize: "12px",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "#3d4035",
            }}
          >
            {isNew ? "New Agent" : `Edit — ${agent?.name}`}
          </p>
          <button
            onClick={onClose}
            style={{
              fontFamily: "monospace",
              fontSize: "9px",
              color: "#c5c9b8",
              background: "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            ✕
          </button>
        </div>

        {/* Form */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "20px",
            padding: "16px 20px",
          }}
        >
          {error && (
            <p
              style={{
                fontFamily: "monospace",
                fontSize: "10px",
                color: "#ef4444",
                textTransform: "uppercase",
                letterSpacing: "0.1em",
              }}
            >
              ⚠ {error}
            </p>
          )}

          <div>
            <label style={S.labelStyle}>Name *</label>
            <input
              style={S.inputStyle}
              placeholder="e.g. Gloop"
              value={form.name}
              onChange={(e) => setField("name", e.target.value)}
            />
          </div>

          <div>
            <label style={S.labelStyle}>Tag line</label>
            <input
              style={S.inputStyle}
              placeholder="e.g. man-fish • seaweed addict"
              value={form.tag}
              onChange={(e) => setField("tag", e.target.value)}
            />
          </div>

          <div>
            <label style={S.labelStyle}>Personality prompt *</label>
            <textarea
              style={{ ...S.inputStyle, resize: "none" }}
              rows={5}
              placeholder="You are [Name]..."
              value={form.personality}
              onChange={(e) => setField("personality", e.target.value)}
            />
          </div>

          <div>
            <label style={S.labelStyle}>Model</label>
            <select
              style={S.inputStyle}
              value={form.model_id}
              onChange={(e) => setField("model_id", e.target.value)}
            >
              <option value="llama-3.1-8b-instant">
                llama-3.1-8b-instant (text)
              </option>
              <option value="meta-llama/llama-4-scout-17b-16e-instruct">
                llama-4-scout (vision)
              </option>
            </select>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
              cursor: "pointer",
            }}
            onClick={() => setField("vision_enabled", !form.vision_enabled)}
          >
            <div
              style={{
                width: "32px",
                height: "16px",
                borderRadius: "9999px",
                backgroundColor: form.vision_enabled ? "#819A91" : "#e8ece0",
                display: "flex",
                alignItems: "center",
                transition: "background-color 0.2s",
                padding: "2px",
              }}
            >
              <div
                style={{
                  width: "12px",
                  height: "12px",
                  borderRadius: "50%",
                  backgroundColor: "white",
                  transform: form.vision_enabled
                    ? "translateX(16px)"
                    : "translateX(0)",
                  transition: "transform 0.2s",
                }}
              />
            </div>
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "9px",
                letterSpacing: "0.2em",
                textTransform: "uppercase",
                color: "#5a5f50",
              }}
            >
              Vision enabled
            </span>
          </div>

          {/* Sub-lists — only shown when editing an existing agent */}
          {!isNew && (
            <>
              <div
                style={{ borderTop: "1px solid #D1D8BE", paddingTop: "16px" }}
              >
                {loading ? (
                  <p
                    style={{
                      fontFamily: "monospace",
                      fontSize: "9px",
                      color: "#c5c9b8",
                      textTransform: "uppercase",
                      letterSpacing: "0.1em",
                    }}
                  >
                    Loading...
                  </p>
                ) : full ? (
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "20px",
                    }}
                  >
                    <TagChips
                      label="Nicknames"
                      items={full.nicknames.map((n) => ({
                        id: n.id,
                        value: n.nickname,
                      }))}
                      onAdd={handleAddNickname}
                      onRemove={handleRemoveNickname}
                      placeholder="e.g. gloopy"
                    />
                    <TagChips
                      label="Interest Keywords"
                      items={full.keywords.map((k) => ({
                        id: k.id,
                        value: k.keyword,
                      }))}
                      onAdd={handleAddKeyword}
                      onRemove={handleRemoveKeyword}
                      placeholder="e.g. seaweed"
                    />
                    <TagChips
                      label="Trigger Phrases"
                      items={full.triggers.map((t) => ({
                        id: t.id,
                        value: t.phrase,
                      }))}
                      onAdd={handleAddTrigger}
                      onRemove={handleRemoveTrigger}
                      placeholder="e.g. seaweed is gross"
                    />
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: "12px",
            borderTop: "1px solid #D1D8BE",
            padding: "16px 20px",
          }}
        >
          <button
            onClick={onClose}
            style={{
              padding: "8px 16px",
              fontFamily: "monospace",
              fontSize: "12px",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "#5a5f50",
              background: "none",
              border: "none",
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              padding: "12px 24px",
              fontFamily: "monospace",
              fontSize: "12px",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "white",
              backgroundColor: saving ? "#c5c9b8" : "#819A91",
              border: "none",
              cursor: saving ? "default" : "pointer",
            }}
          >
            {saving ? "Saving..." : isNew ? "Create Agent" : "Save Changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main dashboard
// ---------------------------------------------------------------------------

export default function AdminDashboard() {
  const { session } = useAuth();
  const [pi] = useState<PiStatus>(MOCK_PI);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [activeUsers] = useState(MOCK_ACTIVE_USERS);
  const [modal, setModal] = useState<Agent | null | false>(false);
  // false = closed, null = new agent, Agent = edit agent
  const [mounted, setMounted] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [agentsError, setAgentsError] = useState<string | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Fetch agents on mount
  useEffect(() => {
    fetchAgents();
  }, []);

  async function fetchAgents() {
    setLoadingAgents(true);
    setAgentsError(null);
    const { data, error } = await getAgents();
    if (error) setAgentsError(error);
    else setAgents(data ?? []);
    setLoadingAgents(false);
  }

  async function handleDelete(id: string) {
    const { error } = await deleteAgent(id);
    if (error) {
      alert(error);
      return;
    }
    setAgents((prev) => prev.filter((a) => a.id !== id));
  }

  const piOnline = pi.updated_at
    ? Date.now() - new Date(pi.updated_at).getTime() < 5 * 60 * 1000
    : false;

  return (
    <div style={{ paddingTop: "var(--nav-height)" }}>
      {/* Header */}
      <div style={S.header}>
        <div>
          <h1
            style={{
              fontSize: "36px",
              fontWeight: 300,
              letterSpacing: "-0.025em",
              color: "#3d4035",
              margin: 0,
            }}
          >
            System Dashboard
          </h1>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            border: "1px solid #D1D8BE",
            padding: "8px 16px",
          }}
        >
          <span
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              backgroundColor: piOnline ? "#819A91" : "#f87171",
              display: "inline-block",
            }}
          />
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "9px",
              letterSpacing: "0.2em",
              textTransform: "uppercase",
              color: "#5a5f50",
            }}
          >
            Pi {piOnline ? "online" : "offline"}
          </span>
          {pi.updated_at && (
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "9px",
                letterSpacing: "0.2em",
                textTransform: "uppercase",
                color: "#c5c9b8",
              }}
            >
              · {mounted ? timeAgo(pi.updated_at) : ""}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div style={S.body}>
        {/* System */}
        <section>
          <p style={S.sectionLabel}>System</p>
          <div style={S.statGrid}>
            <StatCard
              label="Agents"
              value={String(agents.length)}
              sub="active in terrarium"
            />
            <StatCard
              label="Pi Temp"
              value={formatTemp(pi.temp_c)}
              sub={pi.temp_c && pi.temp_c >= 80 ? "⚠ throttle risk" : "nominal"}
              valueColor={tempColor(pi.temp_c)}
            />
            <StatCard
              label="Uptime"
              value={formatUptime(pi.uptime_sec)}
              sub="since last restart"
            />
            <StatCard
              label="Active Users"
              value={String(activeUsers)}
              sub="in last 5 minutes"
            />
          </div>
          <RpdProgressBar remaining={pi.rpd_remaining} limit={pi.rpd_limit} />
        </section>

        {/* Agents */}
        <section>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: "16px",
            }}
          >
            <p style={S.sectionLabel}>Agents ({agents.length})</p>
            <button
              onClick={() => setModal(null)}
              style={{
                padding: "12px 24px",
                fontFamily: "monospace",
                fontSize: "12px",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: "white",
                backgroundColor: "#819A91",
                border: "none",
                cursor: "pointer",
              }}
            >
              + New Agent
            </button>
          </div>

          <div style={{ border: "1px solid #D1D8BE" }}>
            {loadingAgents ? (
              <p
                style={{
                  padding: "32px 20px",
                  textAlign: "center",
                  fontFamily: "monospace",
                  fontSize: "9px",
                  letterSpacing: "0.2em",
                  textTransform: "uppercase",
                  color: "#c5c9b8",
                }}
              >
                Loading...
              </p>
            ) : agentsError ? (
              <p
                style={{
                  padding: "32px 20px",
                  textAlign: "center",
                  fontFamily: "monospace",
                  fontSize: "9px",
                  letterSpacing: "0.2em",
                  textTransform: "uppercase",
                  color: "#ef4444",
                }}
              >
                ⚠ {agentsError}
              </p>
            ) : agents.length === 0 ? (
              <p
                style={{
                  padding: "32px 20px",
                  textAlign: "center",
                  fontFamily: "monospace",
                  fontSize: "9px",
                  letterSpacing: "0.2em",
                  textTransform: "uppercase",
                  color: "#c5c9b8",
                }}
              >
                No agents yet
              </p>
            ) : (
              agents.map((agent, i) => (
                <div
                  key={agent.id}
                  style={{ borderTop: i === 0 ? "none" : "1px solid #D1D8BE" }}
                >
                  <AgentRow
                    agent={agent}
                    onEdit={(a) => setModal(a)}
                    onDelete={handleDelete}
                  />
                </div>
              ))
            )}
          </div>
        </section>

        {/* Quick links */}
        <section>
          <p style={S.sectionLabel}>Quick Links</p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: "16px",
            }}
          >
            {[
              { label: "View Rooms", href: "/rooms" },
              { label: "Message History", href: "/admin/messages" },
              { label: "Back to Chat", href: "/" },
            ].map((link) => (
              <Link
                key={link.href}
                href={link.href}
                style={{
                  border: "1px solid #D1D8BE",
                  padding: "16px 20px",
                  fontFamily: "monospace",
                  fontSize: "12px",
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: "#5a5f50",
                  textDecoration: "none",
                  display: "block",
                }}
              >
                {link.label} →
              </Link>
            ))}
          </div>
        </section>
      </div>

      {/* Modal — false = closed, null = new, Agent = edit */}
      {modal !== false && (
        <AgentModal
          agent={modal}
          onClose={() => setModal(false)}
          onSaved={fetchAgents}
        />
      )}
    </div>
  );
}
