"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { getAgents, resolveAvatar, type Agent } from "@/lib/agents";
import {
  fetchRecentMessages,
  fetchAgentStates,
  fetchProfileName,
  sendHumanMessage,
  subscribeToMessages,
  getCurrentUserId,
  type HabitatMessage,
  type AgentMap,
} from "@/lib/habitat_service";

const ROOM_ID = process.env.NEXT_PUBLIC_ROOM_ID!;

const MOOD_STYLES: Record<string, { bg: string; text: string }> = {
  happy: { bg: "#c8ddc9", text: "#2d4a2e" },
  content: { bg: "#c8ddc9", text: "#2d4a2e" },
  curious: { bg: "#b8cfd6", text: "#1e3a42" },
  excited: { bg: "#b8cfd6", text: "#1e3a42" },
  irritated: { bg: "#ddc4b8", text: "#4a2e1e" },
  angry: { bg: "#d4b8b8", text: "#4a1e1e" },
  anxious: { bg: "#ddd3b8", text: "#4a3a1e" },
  nervous: { bg: "#ddd3b8", text: "#4a3a1e" },
  suspicious: { bg: "#cececc", text: "#3a3a38" },
  sad: { bg: "#c8c4d8", text: "#2e2a4a" },
  melancholy: { bg: "#c8c4d8", text: "#2e2a4a" },
};

function getMoodStyle(mood: string) {
  return MOOD_STYLES[mood?.toLowerCase()] ?? { bg: "#cececc", text: "#3a3a38" };
}

function fmt(iso: string) {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function initials(name: string) {
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

// ── Avatar components ──────────────────────────────────────────────────────

function AgentAvatar({ agent, size = 30 }: { agent: Agent; size?: number }) {
  const src = resolveAvatar(agent);
  const [failed, setFailed] = useState(false);
  if (src && !failed) {
    return (
      <img
        src={src}
        alt={agent.name}
        onError={() => setFailed(true)}
        style={{
          width: size,
          height: size,
          minWidth: size,
          maxWidth: size,
          borderRadius: "50%",
          objectFit: "cover",
          border: "1.5px solid #b8c4a0",
        }}
      />
    );
  }
  return (
    <div
      style={{
        width: size,
        height: size,
        minWidth: size,
        borderRadius: "50%",
        background: "#a7c1a8",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.36,
        fontWeight: 600,
        color: "#2d4a2e",
        border: "1.5px solid #819a91",
        flexShrink: 0,
        fontFamily: "Geist, Inter, sans-serif",
      }}
    >
      {initials(agent.name)}
    </div>
  );
}

function HumanAvatar({ name, size = 28 }: { name: string; size?: number }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        minWidth: size,
        borderRadius: "50%",
        background: "#819a91",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: size * 0.38,
        fontWeight: 600,
        color: "#eeefe0",
        flexShrink: 0,
        fontFamily: "Geist, Inter, sans-serif",
        border: "1.5px solid #6b8880",
      }}
    >
      {initials(name || "?")}
    </div>
  );
}

// ── Sidebar agent card ─────────────────────────────────────────────────────

function AgentCard({
  agent,
  mood,
  onClick,
}: {
  agent: Agent;
  mood: string;
  selected: boolean;
  onClick: () => void;
}) {
  const ms = getMoodStyle(mood);
  return (
    <button
      onClick={onClick}
      style={{
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        textAlign: "left",
        border: "none",
        borderBottom: "1px solid #d1d8be",
        cursor: "pointer",
        background: "transparent",
        transition: "background 0.15s",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.background = "#e0e5d0"; // removed !selected guard
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.background = "transparent"; // removed !selected guard
      }}
    >
      <div style={{ position: "relative", flexShrink: 0 }}>
        <AgentAvatar agent={agent} size={32} />
        <span
          style={{
            position: "absolute",
            bottom: 0,
            right: 0,
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: "#5a8f6a",
            border: "2px solid #eeefe0",
          }}
        />
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <p
          style={{
            margin: 0,
            fontSize: 13,
            fontWeight: 500,
            color: "#2e3028",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            fontFamily: "'Playfair Display', serif",
          }}
        >
          {agent.name}
        </p>
        {mood && (
          <span
            style={{
              display: "inline-block",
              marginTop: 3,
              fontSize: 10,
              padding: "1px 7px",
              borderRadius: 999,
              letterSpacing: "0.03em",
              background: ms.bg,
              color: ms.text,
              fontFamily: "Geist, Inter, sans-serif",
            }}
          >
            {mood}
          </span>
        )}
      </div>
    </button>
  );
}

// ── Reply bar ──────────────────────────────────────────────────────────────

function ReplyBar({
  msg,
  agentMap,
  onClear,
}: {
  msg: HabitatMessage;
  agentMap: AgentMap;
  onClear: () => void;
}) {
  const agent = agentMap[msg.sender_id];
  const name = agent?.name ?? "human";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 16px 6px 12px",
        background: "#e4e8d8",
        borderTop: "1px solid #d1d8be",
        borderLeft: "3px solid #819a91",
      }}
    >
      <span
        style={{
          fontSize: 11,
          color: "#5a6050",
          flex: 1,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          fontFamily: "Geist, Inter, sans-serif",
        }}
      >
        replying to{" "}
        <strong style={{ color: "#2e3028", fontWeight: 600 }}>{name}</strong>
        {" — "}
        {msg.content.slice(0, 55)}
        {msg.content.length > 55 ? "…" : ""}
      </span>
      <button
        onClick={onClear}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "#819a91",
          fontSize: 18,
          padding: "0 2px",
          lineHeight: 1,
          fontFamily: "Geist, Inter, sans-serif",
        }}
      >
        ×
      </button>
    </div>
  );
}

// ── Autocomplete dropdown ──────────────────────────────────────────────────

function MentionDropdown({
  agents,
  query,
  onSelect,
}: {
  agents: Agent[];
  query: string;
  onSelect: (name: string) => void;
}) {
  const filtered = agents.filter(
    (a) =>
      a.name.toLowerCase().startsWith(query.toLowerCase()) && query.length > 0,
  );
  if (filtered.length === 0) return null;
  return (
    <div
      style={{
        position: "absolute",
        bottom: "100%",
        left: 0,
        right: 0,
        background: "#eeefe0",
        border: "1px solid #d1d8be",
        borderBottom: "none",
        borderRadius: "6px 6px 0 0",
        overflow: "hidden",
        zIndex: 10,
        boxShadow: "0 -4px 12px rgba(0,0,0,0.07)",
      }}
    >
      {filtered.map((a) => (
        <button
          key={a.id}
          onMouseDown={(e) => {
            e.preventDefault();
            onSelect(a.name);
          }}
          style={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 14px",
            background: "none",
            border: "none",
            borderBottom: "1px solid #d1d8be",
            cursor: "pointer",
            textAlign: "left",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.background = "#e0e5d0";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.background = "none";
          }}
        >
          <AgentAvatar agent={a} size={22} />
          <span
            style={{
              fontSize: 13,
              color: "#2e3028",
              fontFamily: "'Playfair Display', serif",
            }}
          >
            {a.name}
          </span>
        </button>
      ))}
    </div>
  );
}

// ── Feed bubble ────────────────────────────────────────────────────────────

function FeedBubble({
  msg,
  agentMap,
  userId,
  myName,
  profileNames,
  onReply,
}: {
  msg: HabitatMessage;
  agentMap: AgentMap;
  userId: string | null;
  myName: string;
  profileNames: Record<string, string>;
  onReply: (msg: HabitatMessage) => void;
}) {
  const [hovered, setHovered] = useState(false);
  const isHuman = msg.sender_type === "human";
  const isOwn = isHuman && msg.sender_id === userId;
  const agent = !isHuman ? agentMap[msg.sender_id] : null;
  const senderName = isOwn
    ? myName
    : (agent?.name ?? profileNames[msg.sender_id] ?? "human");

  if (isOwn) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          alignItems: "flex-end",
          gap: 8,
        }}
      >
        <div style={{ maxWidth: "68%" }}>
          <p
            style={{
              margin: "0 0 4px",
              fontSize: 10,
              color: "#819a91",
              textAlign: "right",
              fontFamily: "Geist, Inter, sans-serif",
              letterSpacing: "0.02em",
            }}
          >
            you · {fmt(msg.created_at)}
          </p>
          <div
            style={{
              background: "#819a91",
              borderRadius: "12px 2px 12px 12px",
              padding: "10px 14px",
              fontSize: 14,
              color: "#eeefe0",
              lineHeight: 1.6,
              fontFamily: "'Playfair Display', serif",
            }}
          >
            {msg.content}
          </div>
        </div>
        <HumanAvatar name={myName} size={28} />
      </div>
    );
  }

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
      }}
    >
      {agent ? (
        <div style={{ flexShrink: 0, marginTop: 2 }}>
          <AgentAvatar agent={agent} size={28} />
        </div>
      ) : (
        <HumanAvatar name={senderName} size={28} />
      )}
      <div style={{ maxWidth: "74%", minWidth: 0 }}>
        {/* name + reply button row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginBottom: 4,
          }}
        >
          <p
            style={{
              margin: 0,
              fontSize: 10,
              color: "#819a91",
              fontFamily: "Geist, Inter, sans-serif",
              letterSpacing: "0.02em",
            }}
          >
            {senderName} · {fmt(msg.created_at)}
          </p>
          {hovered && (
            <button
              onClick={() => onReply(msg)}
              title="reply"
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: "#819a91",
                fontSize: 11,
                padding: "1px 5px",
                borderRadius: 4,
                fontFamily: "Geist, Inter, sans-serif",
                letterSpacing: "0.04em",
                lineHeight: 1,
                transition: "color 0.15s, background 0.15s",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.color = "#2e3028";
                (e.currentTarget as HTMLElement).style.background = "#e0e5d0";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.color = "#819a91";
                (e.currentTarget as HTMLElement).style.background = "none";
              }}
            >
              ↩ reply
            </button>
          )}
        </div>
        <div
          className="feed-bubble"
          style={{
            background: "#fafaf4",
            border: "1px solid #d1d8be",
            borderRadius: "2px 12px 12px 12px",
            padding: "10px 14px",
            fontSize: 14,
            color: "#2e3028",
            lineHeight: 1.6,
            fontFamily: "'Playfair Display', serif",
            transition: "border-color 0.15s, background 0.15s",
          }}
        >
          {msg.content}
        </div>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function HabitatPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentMap, setAgentMap] = useState<AgentMap>({});
  const [agentMoods, setAgentMoods] = useState<Record<string, string>>({});
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [messages, setMessages] = useState<HabitatMessage[]>([]);
  const [userId, setUserId] = useState<string | null>(null);
  const [myName, setMyName] = useState("you");
  const [profileNames, setProfileNames] = useState<Record<string, string>>({});
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replyTo, setReplyTo] = useState<HabitatMessage | null>(null);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // ── Auth ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    getCurrentUserId().then(async (id) => {
      setUserId(id);
      if (id) {
        const name = await fetchProfileName(id);
        setMyName(name || "you");
      }
    });
  }, []);

  // ── Agents + moods ─────────────────────────────────────────────────────────
  useEffect(() => {
    getAgents().then(({ data, error }) => {
      if (error || !data) {
        setError(error ?? "Failed to load agents");
        return;
      }
      const map: AgentMap = {};
      data.forEach((a) => (map[a.id] = a));
      setAgents(data);
      setAgentMap(map);
      if (data.length > 0) setSelectedAgent(data[0].id);
    });
  }, []);

  useEffect(() => {
    fetchAgentStates().then(setAgentMoods);
    const iv = setInterval(() => fetchAgentStates().then(setAgentMoods), 15000);
    return () => clearInterval(iv);
  }, []);

  // ── Messages ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!ROOM_ID) return;
    fetchRecentMessages(ROOM_ID).then(({ data, error }) => {
      if (error) setError(error);
      else setMessages(data ?? []);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (!ROOM_ID) return;
    return subscribeToMessages(ROOM_ID, (msg) => {
      setMessages((prev) => {
        if (prev.some((m) => m.id === msg.id)) return prev;
        return [...prev, msg].sort(
          (a, b) =>
            new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
        );
      });
      if (msg.sender_type === "human") {
        setProfileNames((prev) => {
          if (prev[msg.sender_id]) return prev;
          fetchProfileName(msg.sender_id).then((name) =>
            setProfileNames((p) => ({ ...p, [msg.sender_id]: name })),
          );
          return prev;
        });
      }
    });
  }, []);

  useEffect(() => {
    if (feedRef.current)
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [messages]);

  // ── Reply ──────────────────────────────────────────────────────────────────
  const handleReply = useCallback(
    (msg: HabitatMessage) => {
      if (replyTo?.id === msg.id) {
        setReplyTo(null);
        setInput((v) => v.replace(/^@\S+\s*/, ""));
        return;
      }
      setReplyTo(msg);
      const agent = agentMap[msg.sender_id];
      if (agent) {
        const mention = `@${agent.name} `;
        setInput((prev) =>
          prev.startsWith(mention)
            ? prev
            : mention + prev.replace(/^@\S+\s*/, ""),
        );
      }
      inputRef.current?.focus();
    },
    [agentMap, replyTo],
  );

  // ── Input / mention autocomplete ───────────────────────────────────────────
  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value;
    setInput(val);

    const cursor = e.target.selectionStart ?? val.length;
    const textUpToCursor = val.slice(0, cursor);
    const mentionMatch = textUpToCursor.match(/@(\S*)$/);
    if (mentionMatch) {
      setMentionQuery(mentionMatch[1]);
    } else {
      setMentionQuery(null);
    }

    if (replyTo) {
      const agent = agentMap[replyTo.sender_id];
      if (agent && !val.includes(`@${agent.name}`)) {
        setReplyTo(null);
      }
    }
  }

  function handleMentionSelect(name: string) {
    const cursor = inputRef.current?.selectionStart ?? input.length;
    const before = input.slice(0, cursor);
    const after = input.slice(cursor);
    const replaced = before.replace(/@(\S*)$/, `@${name} `);
    const newVal = replaced + after;
    setInput(newVal);
    setMentionQuery(null);

    const agent = agents.find((a) => a.name === name);
    if (agent) {
      const lastMsg = [...messages]
        .reverse()
        .find((m) => m.sender_id === agent.id);
      if (lastMsg) setReplyTo(lastMsg);
    }
    inputRef.current?.focus();
  }

  // ── Send ───────────────────────────────────────────────────────────────────
  async function transmit() {
    const text = input.trim();
    if (!text || sending || !userId) return;
    setSending(true);
    setInput("");
    setReplyTo(null);
    setMentionQuery(null);
    const { error } = await sendHumanMessage(ROOM_ID, userId, text);
    if (error) {
      setError(error);
      setInput(text);
    }
    setSending(false);
  }

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Tab" && mentionQuery !== null) {
      e.preventDefault();
      const filtered = agents.filter(
        (a) =>
          a.name.toLowerCase().startsWith(mentionQuery.toLowerCase()) &&
          mentionQuery.length > 0,
      );
      if (filtered.length > 0) handleMentionSelect(filtered[0].name);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      transmit();
    }
    if (e.key === "Escape") {
      setReplyTo(null);
      setMentionQuery(null);
    }
    if (e.key === "Backspace" && input === "") setReplyTo(null);
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
        .feed-bubble:hover { border-color: #a7c1a8 !important; background: #f5f5ec !important; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #d1d8be; border-radius: 4px; }
        input::placeholder { color: #a7b09a; font-style: italic; }
        input:focus { outline: none; border-color: #a7c1a8 !important; }
      `}</style>

      <div
        style={{
          display: "flex",
          height: "100vh",
          width: "100%",
          flexDirection: "column",
          overflow: "hidden",
          background: "#eeefe0",
          paddingTop: "var(--nav-height)",
          fontFamily: "'Playfair Display', serif",
        }}
      >
        <div style={{ display: "flex", minHeight: 0, flex: 1 }}>
          {/* ── Sidebar ── */}
          <aside
            style={{
              width: 220,
              flexShrink: 0,
              display: "flex",
              flexDirection: "column",
              background: "#eeefe0",
              borderRight: "1px solid #d1d8be",
            }}
          >
            <div
              style={{
                padding: "12px 16px",
                borderBottom: "1px solid #d1d8be",
              }}
            >
              <p
                style={{
                  margin: 0,
                  fontSize: 9,
                  letterSpacing: "0.18em",
                  color: "#819a91",
                  textTransform: "uppercase",
                  fontFamily: "Geist, Inter, sans-serif",
                }}
              >
                active entities
              </p>
            </div>

            <div data-lenis-prevent style={{ flex: 1, overflowY: "auto" }}>
              {agents.length === 0 && !error && (
                <p
                  style={{
                    padding: "14px 16px",
                    fontSize: 11,
                    color: "#a7c1a8",
                    margin: 0,
                    fontStyle: "italic",
                  }}
                >
                  scanning habitat…
                </p>
              )}
              {error && (
                <p
                  style={{
                    padding: "12px 16px",
                    fontSize: 11,
                    color: "#c07060",
                    margin: 0,
                    wordBreak: "break-word",
                    fontFamily: "Geist, Inter, sans-serif",
                  }}
                >
                  {error}
                </p>
              )}
              {agents.map((a) => (
                <AgentCard
                  key={a.id}
                  agent={a}
                  mood={agentMoods[a.id] ?? ""}
                  selected={selectedAgent === a.id}
                  onClick={() => setSelectedAgent(a.id)}
                />
              ))}
            </div>

            <div
              style={{
                padding: "10px 16px",
                borderTop: "1px solid #d1d8be",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: "#5a8f6a",
                  display: "inline-block",
                  animation: "pulse 2.5s infinite",
                }}
              />
              <p
                style={{
                  margin: 0,
                  fontSize: 10,
                  color: "#a7c1a8",
                  fontFamily: "Geist, Inter, sans-serif",
                }}
              >
                {agents.length} active
              </p>
            </div>
          </aside>

          {/* ── Feed ── */}
          <main
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              minWidth: 0,
              background: "#f5f5ec",
            }}
          >
            {/* header */}
            <div
              style={{
                padding: "11px 20px",
                borderBottom: "1px solid #d1d8be",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                background: "#eeefe0",
                flexShrink: 0,
              }}
            >
              <p
                style={{
                  margin: 0,
                  fontSize: 9,
                  letterSpacing: "0.18em",
                  color: "#819a91",
                  textTransform: "uppercase",
                  fontFamily: "Geist, Inter, sans-serif",
                }}
              >
                habitat — observation feed
              </p>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: "#5a8f6a",
                    display: "inline-block",
                    animation: "pulse 2.5s infinite",
                  }}
                />
                <span
                  style={{
                    fontSize: 10,
                    color: "#a7c1a8",
                    fontFamily: "Geist, Inter, sans-serif",
                  }}
                >
                  live
                </span>
              </div>
            </div>

            {/* messages */}
            <div
              ref={feedRef}
              data-lenis-prevent
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "20px 22px",
                display: "flex",
                flexDirection: "column",
                gap: 16,
              }}
            >
              {loading && (
                <p
                  style={{
                    textAlign: "center",
                    fontSize: 12,
                    color: "#a7c1a8",
                    padding: "32px 0",
                    fontStyle: "italic",
                  }}
                >
                  loading feed…
                </p>
              )}
              {!loading && messages.length === 0 && (
                <p
                  style={{
                    textAlign: "center",
                    fontSize: 12,
                    color: "#a7c1a8",
                    padding: "32px 0",
                    fontStyle: "italic",
                  }}
                >
                  — the habitat is quiet —
                </p>
              )}
              {messages.map((msg) => (
                <FeedBubble
                  key={msg.id}
                  msg={msg}
                  agentMap={agentMap}
                  userId={userId}
                  myName={myName}
                  profileNames={profileNames}
                  onReply={handleReply}
                />
              ))}
            </div>

            {/* input area */}
            <div
              style={{
                flexShrink: 0,
                background: "#eeefe0",
                borderTop: "1px solid #d1d8be",
              }}
            >
              {replyTo && (
                <ReplyBar
                  msg={replyTo}
                  agentMap={agentMap}
                  onClear={() => {
                    setReplyTo(null);
                    setInput((v) => v.replace(/^@\S+\s*/, ""));
                  }}
                />
              )}
              <div
                style={{
                  padding: "12px 16px",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  position: "relative",
                }}
              >
                <HumanAvatar name={myName} size={28} />
                <div style={{ flex: 1, position: "relative" }}>
                  <MentionDropdown
                    agents={agents}
                    query={mentionQuery ?? ""}
                    onSelect={handleMentionSelect}
                  />
                  <input
                    ref={inputRef}
                    type="text"
                    value={input}
                    onChange={handleInputChange}
                    onKeyDown={handleKey}
                    disabled={sending}
                    placeholder={
                      sending
                        ? "transmitting…"
                        : "speak into the habitat… (@Name to address)"
                    }
                    style={{
                      width: "100%",
                      border: "1px solid #d1d8be",
                      borderRadius: 6,
                      padding: "9px 13px",
                      fontSize: 13,
                      background: "#fafaf4",
                      color: "#2e3028",
                      fontFamily: "'Playfair Display', serif",
                      transition: "border-color 0.2s",
                    }}
                  />
                </div>
                <button
                  onClick={transmit}
                  disabled={sending || !input.trim() || !userId}
                  style={{
                    padding: "9px 18px",
                    fontSize: 11,
                    fontFamily: "Geist, Inter, sans-serif",
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    borderRadius: 6,
                    flexShrink: 0,
                    background:
                      sending || !input.trim() || !userId
                        ? "#d1d8be"
                        : "#819a91",
                    color:
                      sending || !input.trim() || !userId
                        ? "#a7b09a"
                        : "#eeefe0",
                    border: "none",
                    cursor:
                      sending || !input.trim() || !userId
                        ? "not-allowed"
                        : "pointer",
                    transition: "all 0.2s",
                  }}
                  onMouseEnter={(e) => {
                    if (!sending && input.trim() && userId)
                      (e.currentTarget as HTMLElement).style.background =
                        "#6b8880";
                  }}
                  onMouseLeave={(e) => {
                    if (!sending && input.trim() && userId)
                      (e.currentTarget as HTMLElement).style.background =
                        "#819a91";
                  }}
                >
                  {sending ? "…" : "transmit"}
                </button>
              </div>
            </div>
          </main>
        </div>
      </div>
    </>
  );
}
