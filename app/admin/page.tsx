"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/app/providers";
import { fetchPiStatus, type PiStatus } from "@/lib/pi_service";

import {
  type Agent,
  getAgents,
  deleteAgent,
  resolveAvatar,
} from "@/lib/agents";

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
  if (c >= 80) return "#c0392b";
  if (c >= 70) return "#b8860b";
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
// Mock Pi data
// ---------------------------------------------------------------------------

const MOCK_ACTIVE_USERS = 7;

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
    gap: "40px",
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

  statGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, 1fr)",
    gap: "16px",
  } as React.CSSProperties,

  statCard: {
    backgroundColor: "#e4e6d5",
    border: "1px solid #b0b89a",
    padding: "20px 24px",
  } as React.CSSProperties,

  statLabel: {
    fontFamily: "monospace",
    fontSize: "10px",
    letterSpacing: "0.18em",
    textTransform: "uppercase" as const,
    color: "#4a4f40",
    marginBottom: "10px",
    fontWeight: 600,
  } as React.CSSProperties,

  statValue: {
    fontSize: "28px",
    fontWeight: 300,
    letterSpacing: "-0.025em",
    color: "#2a2d22",
  } as React.CSSProperties,

  statSub: {
    fontFamily: "monospace",
    fontSize: "10px",
    letterSpacing: "0.12em",
    textTransform: "uppercase" as const,
    color: "#6b7060",
    marginTop: "6px",
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
      <p style={{ ...S.statValue, color: valueColor ?? "#2a2d22" }}>{value}</p>
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
  const barColor = used > 85 ? "#c0392b" : used > 60 ? "#b8860b" : "#819A91";
  const statusLabel =
    used > 85 ? "⚠ near limit" : used > 60 ? "moderate usage" : "healthy";

  return (
    <div
      style={{
        backgroundColor: "#e4e6d5",
        border: "1px solid #b0b89a",
        padding: "20px 24px",
        marginTop: "16px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "14px",
        }}
      >
        <p style={S.statLabel}>Groq RPD</p>
        <span
          style={{
            fontFamily: "monospace",
            fontSize: "10px",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "#6b7060",
            fontWeight: 600,
          }}
        >
          {statusLabel}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: "14px",
        }}
      >
        <p style={S.statValue}>
          {remaining?.toLocaleString() ?? "—"}
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "10px",
              color: "#6b7060",
              marginLeft: "8px",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            remaining
          </span>
        </p>
        <span
          style={{
            fontFamily: "monospace",
            fontSize: "12px",
            color: "#4a4f40",
            fontWeight: 600,
          }}
        >
          {limit?.toLocaleString() ?? "—"} limit
        </span>
      </div>
      <div
        style={{
          position: "relative",
          height: "10px",
          width: "100%",
          backgroundColor: "#cdd0be",
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
              backgroundColor: "rgba(255,255,255,0.5)",
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
// AgentRow (read-only overview for dashboard)
// ---------------------------------------------------------------------------

function AgentRow({ agent }: { agent: Agent }) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "14px 20px",
        backgroundColor: hovered ? "#d8dbc9" : "transparent",
        transition: "background-color 0.15s ease",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "14px",
          minWidth: 0,
        }}
      >
        <img
          src={resolveAvatar(agent)}
          alt={agent.name}
          style={{
            width: "34px",
            height: "34px",
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
                fontWeight: 600,
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
                letterSpacing: "0.12em",
                color: "#6b7060",
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
      <span
        style={{
          fontFamily: "monospace",
          fontSize: "10px",
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "#6b7060",
          flexShrink: 0,
        }}
      >
        {agent.model_id}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Dashboard
// ---------------------------------------------------------------------------

export default function AdminDashboard() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [activeUsers] = useState(MOCK_ACTIVE_USERS);
  const [mounted, setMounted] = useState(false);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [agentsError, setAgentsError] = useState<string | null>(null);

  const [pi, setPi] = useState<PiStatus>({
    temp_c: null,
    uptime_sec: null,
    rpd_remaining: null,
    rpd_limit: null,
    tokens_used_today: null,
    updated_at: null,
  });
  useEffect(() => {
    setMounted(true);
    fetchAgents();
  }, []);
  useEffect(() => {
    fetchPiStatus().then(setPi);
    const iv = setInterval(() => fetchPiStatus().then(setPi), 30000);
    return () => clearInterval(iv);
  }, []);
  async function fetchAgents() {
    setLoadingAgents(true);
    setAgentsError(null);
    const { data, error } = await getAgents();
    if (error) setAgentsError(error);
    else setAgents(data ?? []);
    setLoadingAgents(false);
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
              fontSize: "38px",
              fontWeight: 300,
              letterSpacing: "-0.025em",
              color: "#2a2d22",
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
            border: "1px solid #b0b89a",
            padding: "10px 18px",
            backgroundColor: "#e4e6d5",
          }}
        >
          <span
            style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              backgroundColor: piOnline ? "#4a7c5f" : "#c0392b",
              display: "inline-block",
            }}
          />
          <span
            style={{
              fontFamily: "monospace",
              fontSize: "11px",
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: "#3a3f30",
              fontWeight: 600,
            }}
          >
            Pi {piOnline ? "online" : "offline"}
          </span>
          {pi.updated_at && (
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "10px",
                letterSpacing: "0.1em",
                textTransform: "uppercase",
                color: "#6b7060",
              }}
            >
              · {mounted ? timeAgo(pi.updated_at) : ""}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div style={S.body}>
        {/* System Stats */}
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
              label="Tokens Today"
              value={pi.tokens_used_today?.toLocaleString() ?? "—"}
              sub="resets at midnight"
            />
          </div>
          <RpdProgressBar remaining={pi.rpd_remaining} limit={pi.rpd_limit} />
        </section>

        {/* Agents overview */}
        <section>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: "16px",
            }}
          >
            <p style={{ ...S.sectionLabel, marginBottom: 0 }}>
              Agents ({agents.length})
            </p>
            <Link
              href="/admin/agents"
              style={{
                padding: "10px 20px",
                fontFamily: "monospace",
                fontSize: "11px",
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "white",
                backgroundColor: "#819A91",
                textDecoration: "none",
                display: "inline-block",
                fontWeight: 600,
              }}
            >
              Manage Agents →
            </Link>
          </div>

          <div style={{ border: "1px solid #b0b89a" }}>
            {loadingAgents ? (
              <p
                style={{
                  padding: "32px 20px",
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
                  padding: "32px 20px",
                  textAlign: "center",
                  fontFamily: "monospace",
                  fontSize: "11px",
                  letterSpacing: "0.15em",
                  textTransform: "uppercase",
                  color: "#c0392b",
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
                  fontSize: "11px",
                  letterSpacing: "0.15em",
                  textTransform: "uppercase",
                  color: "#6b7060",
                }}
              >
                No agents yet
              </p>
            ) : (
              agents.map((agent, i) => (
                <div
                  key={agent.id}
                  style={{ borderTop: i === 0 ? "none" : "1px solid #b0b89a" }}
                >
                  <AgentRow agent={agent} />
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
              { label: "Manage Agents", href: "/admin/agents" },
              { label: "Message History", href: "/admin/messages" },
              { label: "View Rooms", href: "/rooms" },
              { label: "Back to Chat", href: "/" },
            ].map((link) => (
              <Link
                key={link.href}
                href={link.href}
                style={{
                  border: "1px solid #b0b89a",
                  padding: "18px 20px",
                  fontFamily: "monospace",
                  fontSize: "12px",
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: "#3a3f30",
                  textDecoration: "none",
                  display: "block",
                  backgroundColor: "#e4e6d5",
                  fontWeight: 600,
                  transition: "background-color 0.15s",
                }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.backgroundColor = "#d8dbc9")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.backgroundColor = "#e4e6d5")
                }
              >
                {link.label} →
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
