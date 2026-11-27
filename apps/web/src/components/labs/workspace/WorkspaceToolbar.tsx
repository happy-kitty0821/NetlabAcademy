"use client";

import {
  Play, Square, RotateCcw, Trash2, AlertTriangle, Network,
  Save, CopyPlus, FolderOpen, FilePlus2, CheckCircle2,
} from "lucide-react";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";

const BADGE: Record<SimState, { label: string; color: string; bg: string }> = {
  stopped:  { label: "STOPPED",  color: "#656d76", bg: "#f6f8fa"  },
  starting: { label: "STARTING", color: "#9a6700", bg: "#fff8c5"  },
  running:  { label: "ACTIVE",   color: "#1a7f37", bg: "#dafbe1"  },
  stopping: { label: "STOPPING", color: "#d1242f", bg: "#ffebe9"  },
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
  /** Saved-lab name; null for an unsaved canvas. */
  labName:   string | null;
  /** Canvas differs from what was last saved/opened. */
  dirty:     boolean;
  saving:    boolean;
  /** Short success message (e.g. "Saved"). */
  notice:    string | null;
  onSave:    () => void;
  onSaveAs:  () => void;
  onOpen:    () => void;
  onNew:     () => void;
}

export function WorkspaceToolbar({
  simState, sessionId, nodeCount,
  onStart, onStop, onWipe, onClear, error,
  labName, dirty, saving, notice, onSave, onSaveAs, onOpen, onNew,
}: WorkspaceToolbarProps) {
  const badge     = BADGE[simState];
  const isRunning = simState === "running";
  const isBusy    = simState === "starting" || simState === "stopping";
  const canStart  = !isRunning && !isBusy && nodeCount > 0;
  const pulse     = isRunning || isBusy;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "0 12px", height: 44, minWidth: 0, overflowX: "auto",
      background: "#ffffff", borderBottom: "1px solid #d0d7de",
      flexShrink: 0, userSelect: "none",
    }}>
      {/* Lab name */}
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <Network size={14} color="#0969da" />
        <span
          title={labName ? `Saved lab: ${labName}` : "Not saved yet"}
          style={{ fontSize: 13, fontWeight: 700, fontFamily: "ui-monospace,monospace", color: "#1f2328",
            maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {labName ?? "Untitled Lab"}
        </span>
        {dirty && (
          <span title="Unsaved changes" aria-label="Unsaved changes"
            style={{ width: 7, height: 7, borderRadius: "50%", background: "#9a6700" }} />
        )}
      </div>

      {/* Lab file actions */}
      <div style={{ display: "flex", gap: 4 }}>
        <Btn onClick={onSave} disabled={saving || nodeCount === 0} color="#0969da" bg="#ddf4ff" border="#b6e3ff"
          title={labName ? "Save changes (Ctrl+S)" : "Save as a new lab (Ctrl+S)"}
          icon={<Save size={12} />} label={saving ? "Saving…" : "Save"} />
        <Btn onClick={onSaveAs} disabled={saving || nodeCount === 0} color="#656d76" bg="#f6f8fa" border="#d0d7de"
          title="Save a copy as a new lab" icon={<CopyPlus size={12} />} label="Save as" />
        <Btn onClick={onOpen} disabled={false} color="#656d76" bg="#f6f8fa" border="#d0d7de"
          title="Open a saved lab" icon={<FolderOpen size={12} />} label="Open" />
        <Btn onClick={onNew} disabled={false} color="#656d76" bg="#f6f8fa" border="#d0d7de"
          title="Start a new, empty lab" icon={<FilePlus2 size={12} />} label="New" />
      </div>

      <div style={{ width: 1, height: 20, background: "#d0d7de" }} />

      {/* Controls */}
      <div style={{ display: "flex", gap: 4 }}>
        <Btn onClick={onStart} disabled={!canStart} color="#1a7f37" bg="#dafbe1" border="#b4f1be"
          title={nodeCount === 0 ? "Add devices first" : "Start simulation"}
          icon={<Play size={12} />} label="Start" />
        <Btn onClick={onStop} disabled={!isRunning} color="#d1242f" bg="#ffebe9" border="#ffd7d5"
          title="Stop simulation" icon={<Square size={12} />} label="Stop" />
        <Btn onClick={onWipe} disabled={!isRunning && !sessionId} color="#656d76" bg="#f6f8fa" border="#d0d7de"
          title="Reset simulation" icon={<RotateCcw size={12} />} label="Wipe" />
      </div>

      <div style={{ width: 1, height: 20, background: "#d0d7de" }} />

      <button
        onClick={onClear}
        title="Clear canvas"
        style={{ display: "flex", alignItems: "center", gap: 5, padding: "5px 8px",
          borderRadius: 5, fontSize: 11, fontFamily: "ui-monospace,monospace",
          color: "#656d76", background: "transparent", border: "1px solid transparent", cursor: "pointer" }}
        onMouseEnter={(e) => { e.currentTarget.style.color = "#d1242f"; e.currentTarget.style.background = "#ffebe9"; e.currentTarget.style.borderColor = "#ffd7d5"; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = "#656d76"; e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = "transparent"; }}
      >
        <Trash2 size={11} />
        Clear
      </button>

      <div style={{ flex: 1 }} />

      {notice && !error && (
        <div role="status" style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11,
          fontFamily: "ui-monospace,monospace", color: "#1a7f37" }}>
          <CheckCircle2 size={11} />
          {notice}
        </div>
      )}

      {error && (
        <div role="alert" style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11,
          fontFamily: "ui-monospace,monospace", color: "#d1242f",
          maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          <AlertTriangle size={11} />
          {error}
        </div>
      )}

      {sessionId && (
        <span style={{ fontSize: 10, fontFamily: "monospace", color: "#9198a1" }}>
          {sessionId.slice(0, 8)}
        </span>
      )}

      <div style={{
        display: "flex", alignItems: "center", gap: 6, flexShrink: 0,
        padding: "3px 10px", borderRadius: 20, fontSize: 11,
        fontFamily: "ui-monospace,monospace", fontWeight: 700,
        color: badge.color, background: badge.bg,
        border: `1px solid ${badge.color}40`,
      }}>
        <span style={{
          width: 6, height: 6, borderRadius: "50%", background: badge.color,
          animation: pulse ? "tbPulse 1.4s ease-in-out infinite" : "none",
        }} />
        {badge.label}
      </div>

      <style>{`@keyframes tbPulse { 0%,100%{opacity:1} 50%{opacity:0.25} }`}</style>
    </div>
  );
}

function Btn({ onClick, disabled, color, bg, border, title, icon, label }: {
  onClick: () => void; disabled: boolean; color: string; bg: string; border: string;
  title: string; icon: React.ReactNode; label: string;
}) {
  return (
    <button onClick={onClick} disabled={disabled} title={title}
      style={{ display: "flex", alignItems: "center", gap: 5, whiteSpace: "nowrap", flexShrink: 0,
        padding: "5px 8px", borderRadius: 6, fontSize: 11,
        fontFamily: "ui-monospace,monospace", fontWeight: 600,
        color, background: disabled ? "#f6f8fa" : bg,
        border: `1px solid ${disabled ? "#d0d7de" : border}`,
        opacity: disabled ? 0.5 : 1, cursor: disabled ? "not-allowed" : "pointer",
        transition: "opacity 0.15s" }}>
      {icon}{label}
    </button>
  );
}
