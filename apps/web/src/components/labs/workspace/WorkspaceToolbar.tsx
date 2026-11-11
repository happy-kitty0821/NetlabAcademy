"use client";

/**
 * WorkspaceToolbar — top bar of the lab workspace (CML style).
 */

import { Play, Square, RotateCcw, Trash2, AlertTriangle, Network } from "lucide-react";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";

const P = {
  bg:     "#16213e",
  border: "#0f3460",
  label:  "#cdd6f4",
  muted:  "#7c7f93",
  active: "#00b4d8",
  green:  "#a6e3a1",
  error:  "#e94560",
  warn:   "#fab387",
  hover:  "#0f3460",
};

const SIM_BADGE: Record<SimState, { label: string; color: string }> = {
  stopped:  { label: "STOPPED",  color: P.muted  },
  starting: { label: "STARTING", color: P.warn   },
  running:  { label: "ACTIVE",   color: P.green  },
  stopping: { label: "STOPPING", color: P.error  },
};

interface WorkspaceToolbarProps {
  simState:  SimState;
  sessionId: string | null;
  nodeCount: number;
  onStart:   () => void;
  onStop:    () => void;
  onWipe:    () => void;
  onClear:   () => void;
  error:     string | null;
}

export function WorkspaceToolbar({
  simState, sessionId, nodeCount,
  onStart, onStop, onWipe, onClear, error,
}: WorkspaceToolbarProps) {
  const badge     = SIM_BADGE[simState];
  const isRunning = simState === "running";
  const isBusy    = simState === "starting" || simState === "stopping";
  const canStart  = !isRunning && !isBusy && nodeCount > 0;
  const pulse     = isRunning || isBusy;

  return (
    <div
      style={{
        display:        "flex",
        alignItems:     "center",
        gap:            12,
        padding:        "0 16px",
        height:         44,
        background:     P.bg,
        borderBottom:   `1px solid ${P.border}`,
        flexShrink:     0,
        userSelect:     "none",
      }}
    >
      {/* Lab name */}
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <Network size={14} color={P.active} />
        <span style={{ fontSize: 13, fontWeight: 700, fontFamily: "monospace", color: P.label, letterSpacing: "-0.01em" }}>
          Untitled Lab
        </span>
      </div>

      <div style={{ width: 1, height: 20, background: P.border }} />

      {/* Controls */}
      <div style={{ display: "flex", gap: 4 }}>
        <Btn onClick={onStart} disabled={!canStart} color={P.green}
          title={nodeCount === 0 ? "Add devices first" : "Start simulation"}
          icon={<Play size={12} />} label="Start" />
        <Btn onClick={onStop}  disabled={!isRunning} color={P.error}
          title="Stop simulation"
          icon={<Square size={12} />} label="Stop" />
        <Btn onClick={onWipe}  disabled={!isRunning && !sessionId} color={P.muted}
          title="Reset simulation"
          icon={<RotateCcw size={12} />} label="Wipe" />
      </div>

      <div style={{ width: 1, height: 20, background: P.border }} />

      {/* Clear */}
      <button
        onClick={onClear}
        title="Clear canvas"
        style={ghostBtnStyle(P.muted)}
        onMouseEnter={(e) => { Object.assign(e.currentTarget.style, ghostBtnStyle(P.error, true)); }}
        onMouseLeave={(e) => { Object.assign(e.currentTarget.style, ghostBtnStyle(P.muted)); }}
      >
        <Trash2 size={11} />
        Clear
      </button>

      <div style={{ flex: 1 }} />

      {/* Error */}
      {error && (
        <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, fontFamily: "monospace", color: P.error, maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          <AlertTriangle size={11} />
          {error}
        </div>
      )}

      {/* Session ID */}
      {sessionId && (
        <span style={{ fontSize: 10, fontFamily: "monospace", color: P.border }}>
          {sessionId.slice(0, 8)}
        </span>
      )}

      {/* Status badge */}
      <div
        style={{
          display:      "flex",
          alignItems:   "center",
          gap:          6,
          padding:      "3px 10px",
          borderRadius: 5,
          fontSize:     11,
          fontFamily:   "monospace",
          fontWeight:   700,
          color:        badge.color,
          background:   `${badge.color}1a`,
          border:       `1px solid ${badge.color}40`,
        }}
      >
        <span
          style={{
            width: 6, height: 6, borderRadius: "50%", background: badge.color,
            animation: pulse ? "tbPulse 1.4s ease-in-out infinite" : "none",
          }}
        />
        {badge.label}
      </div>

      <style>{`@keyframes tbPulse { 0%,100%{opacity:1} 50%{opacity:0.25} }`}</style>
    </div>
  );
}

function Btn({ onClick, disabled, color, title, icon, label }: {
  onClick: () => void; disabled: boolean; color: string;
  title: string; icon: React.ReactNode; label: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: "flex", alignItems: "center", gap: 5,
        padding: "5px 10px", borderRadius: 5, fontSize: 11,
        fontFamily: "monospace", fontWeight: 600, cursor: disabled ? "not-allowed" : "pointer",
        color, background: disabled ? "transparent" : `${color}18`,
        border: `1px solid ${color}35`,
        opacity: disabled ? 0.3 : 1, transition: "opacity 0.15s, background 0.15s",
      }}
    >
      {icon}{label}
    </button>
  );
}

function ghostBtnStyle(color: string, hovered = false): React.CSSProperties {
  return {
    display: "flex", alignItems: "center", gap: 5,
    padding: "5px 8px", borderRadius: 5, fontSize: 11,
    fontFamily: "monospace", cursor: "pointer",
    color, background: hovered ? "#0f3460" : "transparent",
    border: `1px solid ${hovered ? "#0f3460" : "transparent"}`,
    transition: "color 0.15s",
  };
}
