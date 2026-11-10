"use client";

/**
 * BottomPanel — CML-style collapsible bottom panel.
 * Shows the event trace and playback controls.
 */

import { motion, AnimatePresence } from "framer-motion";
import { ChevronUp, ChevronDown, Activity, Terminal } from "lucide-react";
import { TraceViewer }     from "@/components/labs/TraceViewer";
import { PlaybackControls } from "@/components/labs/PlaybackControls";
import type { TraceEvent }  from "@/lib/simulation-api";

interface BottomPanelProps {
  open: boolean;
  onToggle: () => void;
  tab: "trace" | "logs";
  onTabChange: (t: "trace" | "logs") => void;
  trace: TraceEvent[];
  currentStep: number;
  isPlaying: boolean;
  speed: number;
  totalSteps: number;
  onPlay: () => void;
  onPause: () => void;
  onStep: () => void;
  onReset: () => void;
  onSpeedChange: (s: number) => void;
  onStepChange: (s: number) => void;
}

export function BottomPanel({
  open, onToggle, tab, onTabChange,
  trace, currentStep, isPlaying, speed, totalSteps,
  onPlay, onPause, onStep, onReset, onSpeedChange,
}: BottomPanelProps) {
  return (
    <div
      className="shrink-0 border-t border-[#21262d]"
      style={{ background: "#161b22" }}
    >
      {/* Panel header / tab bar */}
      <div className="flex items-center px-3 h-8 gap-2">
        {/* Tabs */}
        {(["trace", "logs"] as const).map((t) => (
          <button
            key={t}
            onClick={() => { onTabChange(t); if (!open) onToggle(); }}
            className="flex items-center gap-1.5 text-[11px] font-mono px-2 py-0.5 rounded transition-colors"
            style={{
              color: tab === t && open ? "#58a6ff" : "#484f58",
              background: tab === t && open ? "rgba(88,166,255,0.08)" : "transparent",
            }}
          >
            {t === "trace" ? <Activity size={11} /> : <Terminal size={11} />}
            {t.charAt(0).toUpperCase() + t.slice(1)}
            {t === "trace" && trace.length > 0 && (
              <span
                className="text-[9px] px-1 rounded"
                style={{ background: "#1d3558", color: "#58a6ff" }}
              >
                {trace.length}
              </span>
            )}
          </button>
        ))}

        <div className="flex-1" />

        {/* Playback controls (only when trace is loaded and showing trace tab) */}
        {open && tab === "trace" && trace.length > 0 && (
          <div className="flex-1 max-w-lg">
            <PlaybackControls
              isPlaying={isPlaying}
              onPlay={onPlay}
              onPause={onPause}
              onStep={onStep}
              onReset={onReset}
              currentStep={currentStep}
              totalSteps={totalSteps}
              speed={speed}
              onSpeedChange={onSpeedChange}
            />
          </div>
        )}

        {/* Toggle */}
        <button
          onClick={onToggle}
          className="p-1 rounded text-[#484f58] hover:text-[#8b949e] hover:bg-[#21262d] transition-colors"
        >
          {open ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
        </button>
      </div>

      {/* Panel body */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 220, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="h-full overflow-y-auto">
              {tab === "trace" && (
                <TraceViewer
                  events={trace}
                  currentStep={currentStep}
                />
              )}
              {tab === "logs" && (
                <div className="p-3 text-xs font-mono text-[#484f58]">
                  No log entries yet.
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
