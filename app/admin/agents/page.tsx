"use client";

import { useState, useEffect, useCallback } from "react";
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
// Styles
// ---------------------------------------------------------------------------

const S = {
  page: {
    minHeight: "100vh",
    backgroundColor: "var(--color-bg-primary, #eeefe0)",
    color: "#2a2d22",
  } as React.CSSProperties,

  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    borderBottom: "1px solid #b0b89a",
    padding: "24px 32px",
  } as React.CSSProperties,

  body: {
    padding: "32px",
    display: "flex",
    flexDirection: "column" as const,
    gap: "24px",
  } as React.CSSProperties,

  sectionLabel: {
    fontFamily: "monospace",
    fontSize: "11px",
    letterSpacing: "0.18em",
    textTransform: "uppercase" as const,
    color: "#5a5f50",
    marginBottom: "16px",
    fontWeight: 600,
  } as React.CSSProperties,

  inputStyle: {
    width: "100%",
    borderBottom: "1px solid #819A91",
    background: "transparent",
    padding: "10px 4px",
    fontSize: "14px",
    color: "#2a2d22",
    outline: "none",
    boxSizing: "border-box" as const,
    fontFamily: "inherit",
  } as React.CSSProperties,

  labelStyle: {
    display: "block",
    fontFamily: "monospace",
    fontSize: "10px",
    letterSpacing: "0.18em",
    textTransform: "uppercase" as const,
    color: "#4a4f40",
    marginBottom: "8px",
    fontWeight: 600,
  } as React.CSSProperties,

  btn: {
    padding: "10px 20px",
    fontFamily: "monospace",
    fontSize: "11px",
    letterSpacing: "0.12em",
    textTransform: "uppercase" as const,
    border: "none",
    cursor: "pointer",
    fontWeight: 600,
  } as React.CSSProperties,
} as const;

// ---------------------------------------------------------------------------
// TagChips
// ---------------------------------------------------------------------------

function TagChips({
  label,
  items,
  onAdd,
  onRemove,
  placeholder,
  hint,
}: {
  label: string;
  items: { id: string; value: string }[];
  onAdd: (value: string) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
  placeholder: string;
  hint?: string;
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
      {hint && (
        <p
          style={{
            fontFamily: "monospace",
            fontSize: "10px",
            color: "#6b7060",
            marginBottom: "10px",
            letterSpacing: "0.05em",
          }}
        >
          {hint}
        </p>
      )}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "6px",
          marginBottom: "10px",
          minHeight: "28px",
        }}
      >
        {items.length === 0 && (
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "10px",
              color: "#8a9080",
              letterSpacing: "0.1em",
              fontStyle: "italic",
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
              gap: "6px",
              backgroundColor: "#d0d8c0",
              border: "1px solid #b0b89a",
              padding: "4px 10px",
            }}
          >
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "11px",
                color: "#2a2d22",
                fontWeight: 600,
              }}
            >
              {item.value}
            </span>
            <button
              onClick={() => onRemove(item.id)}
              style={{
                fontFamily: "monospace",
                fontSize: "10px",
                color: "#6b7060",
                background: "none",
                border: "none",
                cursor: "pointer",
                lineHeight: 1,
                padding: 0,
                marginTop: "-1px",
              }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: "8px" }}>
        <input
          style={{ ...S.inputStyle, flex: 1, fontSize: "13px" }}
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
            ...S.btn,
            padding: "8px 16px",
            fontSize: "10px",
            color: "white",
            backgroundColor: loading || !input.trim() ? "#b0b89a" : "#819A91",
            cursor: loading || !input.trim() ? "default" : "pointer",
          }}
        >
          Add
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AgentModal — handles both create and edit
// On create: two-step: fill form → save → then manage sub-lists inline
// On edit: everything visible at once
// ---------------------------------------------------------------------------

function AgentModal({
  agent,
  onClose,
  onSaved,
}: {
  agent: Agent | null;
  onClose: () => void;
  onSaved: () => void;
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

  // For new agents: after first save, we have an ID and can manage sub-lists
  const [savedAgent, setSavedAgent] = useState<Agent | null>(null);

  const [full, setFull] = useState<AgentFull | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeAgentId = savedAgent?.id ?? agent?.id;

  // ESC to close
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  // Hydrate full agent when we have an ID
  useEffect(() => {
    if (!activeAgentId) return;
    setLoading(true);
    getAgentFull(activeAgentId).then(({ data, error }) => {
      if (error) setError(error);
      else setFull(data);
      setLoading(false);
    });
  }, [activeAgentId]);

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

    if (isNew && !savedAgent) {
      const { data, error } = await createAgent({
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
      setSavedAgent(data);
      onSaved(); // refresh list in background
    } else {
      const { error } = await updateAgent({
        agent_id: activeAgentId!,
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
      onSaved();
    }

    setSaving(false);
  }

  // Sub-list handlers
  async function handleAddNickname(value: string) {
    if (!activeAgentId) return;
    const { data, error } = await addAgentNickname(activeAgentId, value);
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
    if (!activeAgentId) return;
    const { data, error } = await addAgentKeyword(activeAgentId, value);
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
    if (!activeAgentId) return;
    const { data, error } = await addAgentTrigger(activeAgentId, value);
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

  const showSubLists = !!activeAgentId;
  const hasBeenSaved = !isNew || !!savedAgent;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "rgba(42,45,34,0.5)",
        backdropFilter: "blur(4px)",
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        style={{
          backgroundColor: "var(--color-bg-primary, #eeefe0)",
          margin: "0 16px",
          maxHeight: "90vh",
          width: "100%",
          maxWidth: "560px",
          overflowY: "auto",
          border: "1px solid #b0b89a",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottom: "1px solid #b0b89a",
            padding: "18px 24px",
            position: "sticky",
            top: 0,
            backgroundColor: "var(--color-bg-primary, #eeefe0)",
            zIndex: 1,
          }}
        >
          <p
            style={{
              fontFamily: "monospace",
              fontSize: "13px",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              color: "#2a2d22",
              fontWeight: 700,
              margin: 0,
            }}
          >
            {isNew
              ? savedAgent
                ? `Agent Created — ${savedAgent.name}`
                : "New Agent"
              : `Edit — ${agent?.name}`}
          </p>
          <button
            onClick={onClose}
            title="Close (Esc)"
            style={{
              fontFamily: "monospace",
              fontSize: "11px",
              color: "#6b7060",
              background: "none",
              border: "none",
              cursor: "pointer",
              letterSpacing: "0.1em",
            }}
          >
            ✕ ESC
          </button>
        </div>

        {/* Form fields */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "22px",
            padding: "24px",
          }}
        >
          {error && (
            <p
              style={{
                fontFamily: "monospace",
                fontSize: "11px",
                color: "#c0392b",
                textTransform: "uppercase",
                letterSpacing: "0.1em",
                fontWeight: 600,
              }}
            >
              ⚠ {error}
            </p>
          )}

          {/* Show note after first save for new agents */}
          {isNew && savedAgent && (
            <div
              style={{
                backgroundColor: "#d0e0d1",
                border: "1px solid #819A91",
                padding: "12px 16px",
              }}
            >
              <p
                style={{
                  fontFamily: "monospace",
                  fontSize: "11px",
                  color: "#2a5040",
                  letterSpacing: "0.08em",
                  margin: 0,
                }}
              >
                ✓ Agent saved. You can now add nicknames, keywords, and trigger
                phrases below, or close to finish.
              </p>
            </div>
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
              style={{ ...S.inputStyle, resize: "vertical" }}
              rows={5}
              placeholder="You are [Name]..."
              value={form.personality}
              onChange={(e) => setField("personality", e.target.value)}
            />
          </div>

          <div>
            <label style={S.labelStyle}>Model</label>
            <select
              style={{ ...S.inputStyle, cursor: "pointer" }}
              value={form.model_id}
              onChange={(e) => setField("model_id", e.target.value)}
            >
              <option value="llama-3.1-8b-instant">
                llama-3.1-8b-instant — text
              </option>
              <option value="meta-llama/llama-4-scout-17b-16e-instruct">
                llama-4-scout-17b — vision
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
                width: "36px",
                height: "18px",
                borderRadius: "9999px",
                backgroundColor: form.vision_enabled ? "#819A91" : "#cdd0be",
                display: "flex",
                alignItems: "center",
                transition: "background-color 0.2s",
                padding: "3px",
                flexShrink: 0,
              }}
            >
              <div
                style={{
                  width: "12px",
                  height: "12px",
                  borderRadius: "50%",
                  backgroundColor: "white",
                  transform: form.vision_enabled
                    ? "translateX(18px)"
                    : "translateX(0)",
                  transition: "transform 0.2s",
                }}
              />
            </div>
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "11px",
                letterSpacing: "0.15em",
                textTransform: "uppercase",
                color: "#4a4f40",
                fontWeight: 600,
              }}
            >
              Vision enabled
            </span>
          </div>

          {/* Save / update button for the core form */}
          <div
            style={{ display: "flex", justifyContent: "flex-end", gap: "10px" }}
          >
            {hasBeenSaved && !isNew && (
              <button
                onClick={onClose}
                style={{
                  ...S.btn,
                  color: "#5a5f50",
                  background: "none",
                }}
              >
                Cancel
              </button>
            )}
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                ...S.btn,
                color: "white",
                backgroundColor: saving ? "#b0b89a" : "#819A91",
                cursor: saving ? "default" : "pointer",
              }}
            >
              {saving
                ? "Saving..."
                : isNew && !savedAgent
                  ? "Create Agent"
                  : "Save Changes"}
            </button>
          </div>

          {/* Sub-lists */}
          {showSubLists && (
            <div
              style={{
                borderTop: "1px solid #b0b89a",
                paddingTop: "24px",
                display: "flex",
                flexDirection: "column",
                gap: "28px",
              }}
            >
              <p
                style={{
                  fontFamily: "monospace",
                  fontSize: "11px",
                  letterSpacing: "0.18em",
                  textTransform: "uppercase",
                  color: "#5a5f50",
                  fontWeight: 700,
                  margin: 0,
                }}
              >
                Behaviour &amp; Recognition
              </p>

              {loading ? (
                <p
                  style={{
                    fontFamily: "monospace",
                    fontSize: "11px",
                    color: "#8a9080",
                    textTransform: "uppercase",
                    letterSpacing: "0.1em",
                  }}
                >
                  Loading...
                </p>
              ) : full ? (
                <>
                  <TagChips
                    label="Nicknames"
                    hint="Alternative names users might call this agent."
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
                    hint="Topics this agent is passionate about and will react to."
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
                    hint="Exact phrases that will cause this agent to respond."
                    items={full.triggers.map((t) => ({
                      id: t.id,
                      value: t.phrase,
                    }))}
                    onAdd={handleAddTrigger}
                    onRemove={handleRemoveTrigger}
                    placeholder="e.g. seaweed is gross"
                  />
                </>
              ) : null}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: "12px",
            borderTop: "1px solid #b0b89a",
            padding: "18px 24px",
            position: "sticky",
            bottom: 0,
            backgroundColor: "var(--color-bg-primary, #eeefe0)",
          }}
        >
          <button
            onClick={onClose}
            style={{
              ...S.btn,
              color: "#4a4f40",
              background: "none",
            }}
          >
            {isNew && savedAgent ? "Done" : "Cancel"}
          </button>
          {hasBeenSaved && (
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                ...S.btn,
                color: "white",
                backgroundColor: saving ? "#b0b89a" : "#819A91",
                cursor: saving ? "default" : "pointer",
              }}
            >
              {saving ? "Saving..." : "Save Changes"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AgentRow (full, with edit/delete)
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
        padding: "16px 24px",
        backgroundColor: hovered ? "#d8dbc9" : "transparent",
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
            width: "38px",
            height: "38px",
            borderRadius: "50%",
            border: "1px solid #b0b89a",
            flexShrink: 0,
            objectFit: "cover",
          }}
        />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "13px",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "#2a2d22",
                fontWeight: 700,
              }}
            >
              {agent.name}
            </span>
            {agent.vision_enabled && (
              <span
                style={{
                  border: "1px solid #819A91",
                  padding: "2px 6px",
                  fontFamily: "monospace",
                  fontSize: "9px",
                  letterSpacing: "0.2em",
                  textTransform: "uppercase",
                  color: "#4a6b5e",
                  backgroundColor: "#d0e0d1",
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
                fontSize: "10px",
                letterSpacing: "0.1em",
                color: "#6b7060",
                marginTop: "3px",
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
          gap: "20px",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontFamily: "monospace",
            fontSize: "10px",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "#6b7060",
          }}
        >
          {agent.model_id}
        </span>
        <button
          onClick={() => onEdit(agent)}
          style={{
            fontFamily: "monospace",
            fontSize: "10px",
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            color: "#3a3f30",
            background: "none",
            border: "1px solid #b0b89a",
            cursor: "pointer",
            padding: "6px 14px",
            fontWeight: 600,
          }}
        >
          Edit
        </button>
        <button
          onClick={() => onDelete(agent.id)}
          style={{
            fontFamily: "monospace",
            fontSize: "10px",
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            color: "#8a5050",
            background: "none",
            border: "none",
            cursor: "pointer",
            fontWeight: 600,
          }}
        >
          Remove
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main — Agents Page
// ---------------------------------------------------------------------------

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [modal, setModal] = useState<Agent | null | false>(false);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [agentsError, setAgentsError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    fetchAgents();
  }, []);

  // ESC closes modal if open, otherwise does nothing
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape" && modal !== false) setModal(false);
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [modal]);

  async function fetchAgents() {
    setLoadingAgents(true);
    setAgentsError(null);
    const { data, error } = await getAgents();
    if (error) setAgentsError(error);
    else setAgents(data ?? []);
    setLoadingAgents(false);
  }

  async function handleDelete(id: string) {
    if (!confirm("Remove this agent? This cannot be undone.")) return;
    const { error } = await deleteAgent(id);
    if (error) {
      alert(error);
      return;
    }
    setAgents((prev) => prev.filter((a) => a.id !== id));
  }

  const filtered = agents.filter(
    (a) =>
      !search ||
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      (a.tag ?? "").toLowerCase().includes(search.toLowerCase()) ||
      a.model_id.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div style={{ paddingTop: "var(--nav-height)" }}>
      {/* Header */}
      <div style={S.header}>
        <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
          <Link
            href="/admin"
            style={{
              fontFamily: "monospace",
              fontSize: "11px",
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: "#6b7060",
              textDecoration: "none",
              fontWeight: 600,
            }}
          >
            ← Dashboard
          </Link>
          <h1
            style={{
              fontSize: "38px",
              fontWeight: 300,
              letterSpacing: "-0.025em",
              color: "#2a2d22",
              margin: 0,
            }}
          >
            Agents
          </h1>
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "13px",
              color: "#6b7060",
              letterSpacing: "0.08em",
              marginTop: "8px",
            }}
          >
            {agents.length} total
          </span>
        </div>

        <button
          onClick={() => setModal(null)}
          style={{
            ...S.btn,
            color: "white",
            backgroundColor: "#819A91",
            fontSize: "12px",
          }}
        >
          + New Agent
        </button>
      </div>

      {/* Body */}
      <div style={S.body}>
        {/* Search */}
        <div style={{ maxWidth: "400px" }}>
          <input
            style={{
              ...S.inputStyle,
              fontSize: "14px",
              borderBottom: "1px solid #b0b89a",
            }}
            placeholder="Search agents by name, tag, or model..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Agent list */}
        <div style={{ border: "1px solid #b0b89a" }}>
          {loadingAgents ? (
            <p
              style={{
                padding: "40px 24px",
                textAlign: "center",
                fontFamily: "monospace",
                fontSize: "11px",
                letterSpacing: "0.15em",
                textTransform: "uppercase",
                color: "#6b7060",
              }}
            >
              Loading...
            </p>
          ) : agentsError ? (
            <p
              style={{
                padding: "40px 24px",
                textAlign: "center",
                fontFamily: "monospace",
                fontSize: "11px",
                letterSpacing: "0.15em",
                textTransform: "uppercase",
                color: "#c0392b",
                fontWeight: 600,
              }}
            >
              ⚠ {agentsError}
            </p>
          ) : filtered.length === 0 ? (
            <p
              style={{
                padding: "40px 24px",
                textAlign: "center",
                fontFamily: "monospace",
                fontSize: "11px",
                letterSpacing: "0.15em",
                textTransform: "uppercase",
                color: "#6b7060",
              }}
            >
              {search
                ? "No agents match that search"
                : "No agents yet — create one above"}
            </p>
          ) : (
            filtered.map((agent, i) => (
              <div
                key={agent.id}
                style={{ borderTop: i === 0 ? "none" : "1px solid #b0b89a" }}
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

        {/* Stats row */}
        {agents.length > 0 && !loadingAgents && (
          <div
            style={{
              display: "flex",
              gap: "32px",
              fontFamily: "monospace",
              fontSize: "11px",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "#6b7060",
              fontWeight: 600,
            }}
          >
            <span>
              {agents.filter((a) => a.vision_enabled).length} with vision
            </span>
            <span>
              {[...new Set(agents.map((a) => a.model_id))].length} distinct
              models
            </span>
          </div>
        )}
      </div>

      {/* Modal */}
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
