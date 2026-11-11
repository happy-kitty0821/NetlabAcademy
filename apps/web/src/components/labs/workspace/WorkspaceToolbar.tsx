"use client";

/**
 * WorkspaceToolbar — top bar of the lab workspace.
 *
 * Mirrors Cisco CML 2.x exactly:
 *  - Lab name on the left
 *  - Start / Stop / Wipe controls
 *  - Live status indicator on the right
 */

import { Play, Square, RotateCcw, Trash2, AlertTriangle, Network } from "lucide-react";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";

interface WorkspaceToolbarProps {
  simState:   SimState;
  sessionId:  string | null;
  nodeCount:  number;
  onStart:    () => void;
  onStop:     () => void;
  onWipe:     () => void;
  onClear:    () => void;
  error:      string | null;
}

const SIM_BADGE: Record<SimState, { label: string; color: string }> = {
  stopped:  { label: "STOPPED",  color: "#6e7681" },
  starting: { label: "STARTING", color: "#d29922" },
  running:  { label: "ACTIVE",   color: "#3fb950" },
  stopping: { label: "STOPPING", color: "#f85149" },
};

export function WorkspaceToolbar({
  simState, sessionId, nodeCount,
  onStart, onStop, onWipe, onClear, error,
}: WorkspaceToolbarProps) {
  const badge     = SIM_BADGE[simState];
  const isRunning = simState === "running";
  const isBusy    = simState === "starting" || simState === "stopping";
  const canStart  = !isRunning && !isBusy && nodeCount > 0;

  return (
    <div
      className="flex items-center gap-3 px-4 shrink-0 border-b border-[#21262d] select-none"
      style={{ height: 44, background: "#161b22" }}
    >
      {/* Lab name */}
      <div className="flex items-center gap-2">
        <Network size={14} color="#58a6ff" aria-hidden="true" />
        <span className="text-[13px] font-semibold text-[#e6edf3] font-mono tracking-tight">
          Untitled Lab
        </span>
      </div>

      <div className="w-px h-5 bg-[#30363d]" />

      {/* Primary controls */}
      <div className="flex items-center gap-1">
        <ToolBtn
          onClick={onStart}
          disabled={!canStart}
          title={nodeCount === 0 ? "Add devices first" : "Start simulation"}
          color="#3fb950"
          icon={<Play size={12} />}
          label="Start"
        />
        <ToolBtn
          onClick={onStop}
          disabled={!isRunning}
          title="Stop simulation"
          color="#f85149"
          icon={<Square size={12} />}
          label="Stop"
        />
        <ToolBtn
          onClick={onWipe}
          disabled={!isRunning && !sessionId}
          title="Reset simulation state"
          color="#8b949e"
          icon={<RotateCcw size={12} />}
          label="Wipe"
        />
      </div>

      <div className="w-px h-5 bg-[#30363d]" />

      {/* Clear canvas */}
      <button
        onClick={onClear}
        title="Clear canvas"
        className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-mono text-[#6e7681] hover:text-[#f85149] hover:bg-[#21262d] transition-colors"
      >
        <Trash2 size={11} />
        Clear
      </button>

      <div className="flex-1" />

      {/* Error */}
      {error && (
        <div className="flex items-center gap-1.5 text-[11px] font-mono text-[#f85149] max-w-sm truncate">
          <AlertTriangle size={11} />
          {error}
        </div>
      )}

      {/* Session ID */}
      {sessionId && (
        <span className="text-[10px] font-mono text-[#484f58] hidden lg:block">
          {sessionId.slice(0, 8)}
        </span>
      )}

      {/* Status badge */}
      <div
        className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-semibold font-mono"
        style={{
          color:      badge.color,
          background: `${badge.color}18`,
          border:     `1px solid ${badge.color}40`,
        }}
      >
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{
            background: badge.color,
            animation:  (isRunning || isBusy) ? "toolbarPulse 1.4s ease-in-out infinite" : "none",
          }}
        />
        {badge.label}
      </div>

      <style>{`
        @keyframes toolbarPulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}

function ToolBtn({
  onClick, disabled, title, color, icon, label,
}: {
  onClick:  () => void;
  disabled: boolean;
  title:    string;
  color:    string;
  icon:     React.ReactNode;
  label:    string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-mono font-medium transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
      style={{
        color,
        background: disabled ? "transparent" : `${color}14`,
        border:     `1px solid ${color}30`,
      }}
    >
      {icon}
      {label}
    </button>
  );
}
