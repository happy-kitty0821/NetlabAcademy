"use client";

/**
 * LabToolbar — CML-style top toolbar.
 *
 * Shows simulation status badge, start/stop/reset controls,
 * and the lab name. Exactly mirrors CML 2.x's workbench toolbar.
 */

import { motion, AnimatePresence } from "framer-motion";
import { Network, Play, Square, RotateCcw, AlertTriangle } from "lucide-react";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";

interface LabToolbarProps {
  simState: SimState;
  sessionId: string | null;
  onStart: () => void;
  onStop: () => void;
  onReset: () => void;
  error: string | null;
}

const STATE_CONFIG: Record<SimState, { label: string; color: string; dot: string }> = {
  stopped:  { label: "STOPPED",  color: "#484f58", dot: "#484f58" },
  starting: { label: "STARTING", color: "#d29922", dot: "#d29922" },
  running:  { label: "ACTIVE",   color: "#3fb950", dot: "#3fb950" },
  stopping: { label: "STOPPING", color: "#f85149", dot: "#f85149" },
};

export function LabToolbar({
  simState, sessionId, onStart, onStop, onReset, error,
}: LabToolbarProps) {
  const cfg = STATE_CONFIG[simState];
  const isRunning = simState === "running";
  const isTransitioning = simState === "starting" || simState === "stopping";

  return (
    <div
      className="flex items-center gap-3 px-4 h-12 shrink-0 border-b border-[#21262d]"
      style={{ background: "#161b22" }}
    >
      {/* Logo / lab name */}
      <div className="flex items-center gap-2 mr-2">
        <Network size={15} className="text-[#58a6ff]" aria-hidden="true" />
        <span className="text-sm font-semibold text-[#e6edf3] font-mono">
          Lab Workspace
        </span>
      </div>

      <div className="w-px h-5 bg-[#30363d]" />

      {/* Simulation controls */}
      <div className="flex items-center gap-1.5">
        {/* Start */}
        <button
          onClick={onStart}
          disabled={isRunning || isTransitioning}
          title="Start simulation"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: isRunning || isTransitioning ? "transparent" : "rgba(63,185,80,0.12)",
            color: "#3fb950",
            border: "1px solid rgba(63,185,80,0.25)",
          }}
        >
          <Play size={12} />
          Start
        </button>

        {/* Stop */}
        <button
          onClick={onStop}
          disabled={!isRunning}
          title="Stop simulation"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: isRunning ? "rgba(248,81,73,0.1)" : "transparent",
            color: "#f85149",
            border: "1px solid rgba(248,81,73,0.2)",
          }}
        >
          <Square size={12} />
          Stop
        </button>

        {/* Wipe / Reset */}
        <button
          onClick={onReset}
          disabled={!isRunning}
          title="Reset simulation"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium text-[#8b949e] transition-colors disabled:opacity-40 disabled:cursor-not-allowed hover:text-[#e6edf3] hover:bg-[#21262d]"
          style={{ border: "1px solid #30363d" }}
        >
          <RotateCcw size={12} />
          Wipe
        </button>
      </div>

      <div className="flex-1" />

      {/* Error indicator */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 8 }}
            className="flex items-center gap-1.5 text-xs text-[#f85149] font-mono max-w-xs truncate"
          >
            <AlertTriangle size={12} />
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Session ID */}
      {sessionId && (
        <span className="text-[10px] text-[#484f58] font-mono hidden sm:block">
          {sessionId.slice(0, 8)}
        </span>
      )}

      {/* Simulation status badge */}
      <div
        className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-mono font-semibold"
        style={{
          background: `${cfg.dot}18`,
          border: `1px solid ${cfg.dot}40`,
          color: cfg.color,
        }}
      >
        <motion.span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: cfg.dot }}
          animate={isTransitioning || isRunning ? { opacity: [1, 0.3, 1] } : {}}
          transition={{ repeat: Infinity, duration: 1.2 }}
        />
        {cfg.label}
      </div>
    </div>
  );
}
