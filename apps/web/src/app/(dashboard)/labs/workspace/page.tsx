"use client";

/**
 * /labs/workspace — CML-style lab workspace.
 *
 * Layout mirrors Cisco Modeling Labs 2.x:
 *
 *  ┌──────────────────────────────────────────────────────┐
 *  │  Toolbar (start/stop/reset, sim status)               │
 *  ├──────┬───────────────────────────────┬───────────────┤
 *  │ Left │  Center: topology canvas       │ Right panel   │
 *  │      │  (React Flow)                  │ - Properties  │
 *  │ Pal- │                                │ - Interfaces  │
 *  │ ette │                                │ - Terminal    │
 *  │      │                                │               │
 *  ├──────┴───────────────────────────────┴───────────────┤
 *  │  Bottom: event trace / logs                           │
 *  └──────────────────────────────────────────────────────┘
 */

import { useState, useCallback } from "react";

// ── Lab sub-components
import { LabToolbar }       from "@/components/labs/workspace/LabToolbar";
import { NodePalette }      from "@/components/labs/workspace/NodePalette";
import { TopologyCanvas }   from "@/components/labs/workspace/TopologyCanvas";
import { RightPanel }       from "@/components/labs/workspace/RightPanel";
import { BottomPanel }      from "@/components/labs/workspace/BottomPanel";

// ── Types
import type { TopologyDocument, TopologyNode, TraceEvent } from "@/lib/simulation-api";
import { DEFAULT_TOPOLOGY }         from "@/lib/simulation-api";
import { createSimulation, resetSimulation } from "@/lib/simulation-api";

export type SimState = "stopped" | "starting" | "running" | "stopping";

export default function WorkspacePage() {
  // ── Simulation state ───────────────────────────────────────────────
  const [simState, setSimState] = useState<SimState>("stopped");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [topology, setTopology] = useState<TopologyDocument>(DEFAULT_TOPOLOGY);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  // ── Selection ──────────────────────────────────────────────────────
  const [selectedNode, setSelectedNode] = useState<TopologyNode | null>(null);
  const [rightTab, setRightTab] = useState<"properties" | "interfaces" | "terminal">("properties");

  // ── Bottom panel ───────────────────────────────────────────────────
  const [bottomOpen, setBottomOpen] = useState(false);
  const [bottomTab, setBottomTab] = useState<"trace" | "logs">("trace");

  // ── Playback ───────────────────────────────────────────────────────
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(700);

  // ── Handlers ───────────────────────────────────────────────────────

  const handleStart = useCallback(async () => {
    setError(null);
    setSimState("starting");
    setTrace([]);
    setCurrentStep(0);
    try {
      const session = await createSimulation(topology, 42);
      setSessionId(session.id);
      setSimState("running");
    } catch (err) {
      const e = err as { error?: { message?: string } };
      setError(e?.error?.message ?? "Failed to start simulation.");
      setSimState("stopped");
    }
  }, [topology]);

  const handleStop = useCallback(async () => {
    setSimState("stopping");
    setIsPlaying(false);
    // Session remains in memory — just mark stopped locally
    setTimeout(() => setSimState("stopped"), 400);
  }, []);

  const handleReset = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    setIsPlaying(false);
    try {
      await resetSimulation(sessionId);
      setTrace([]);
      setCurrentStep(0);
    } catch (err) {
      const e = err as { error?: { message?: string } };
      setError(e?.error?.message ?? "Failed to reset.");
    }
  }, [sessionId]);

  const handleTraceUpdate = useCallback((newTrace: TraceEvent[]) => {
    setTrace(newTrace);
    setCurrentStep(0);
    setIsPlaying(true);
    setBottomOpen(true);
    setBottomTab("trace");
  }, []);

  const handleNodeSelect = useCallback((node: TopologyNode | null) => {
    setSelectedNode(node);
    if (node) setRightTab("properties");
  }, []); // eslint-disable-next-line react-hooks/exhaustive-deps

  // Selection is currently wired via the right panel; the canvas
  // will call this once click overlays are implemented.
  void handleNodeSelect;

  const handleApplyTopology = useCallback(async (newTopo: TopologyDocument) => {
    setTopology(newTopo);
    setError(null);
    setTrace([]);
    setCurrentStep(0);
    setIsPlaying(false);
    setSimState("starting");
    try {
      const session = await createSimulation(newTopo, 42);
      setSessionId(session.id);
      setSimState("running");
    } catch (err) {
      const e = err as { error?: { message?: string } };
      setError(e?.error?.message ?? "Failed to start simulation.");
      setSimState("stopped");
    }
  }, []);

  return (
    <div className="flex flex-col h-full bg-[#0d1117] overflow-hidden">
      {/* ── Toolbar ───────────────────────────────────────────────── */}
      <LabToolbar
        simState={simState}
        sessionId={sessionId}
        onStart={handleStart}
        onStop={handleStop}
        onReset={handleReset}
        error={error}
      />

      {/* ── Main area ─────────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Left: node palette */}
        <NodePalette onApplyTopology={handleApplyTopology} />

        {/* Center: topology canvas */}
        <div className="flex-1 min-w-0 relative">
          <TopologyCanvas
            topology={topology}
            trace={trace}
            isPlaying={isPlaying}
            currentStep={currentStep}
            speed={speed}
            onStepChange={(s) => {
              setCurrentStep(s);
              if (s >= trace.length) setIsPlaying(false);
            }}
            simState={simState}
          />
        </div>

        {/* Right: properties / interfaces / terminal */}
        <RightPanel
          node={selectedNode}
          tab={rightTab}
          onTabChange={setRightTab}
          sessionId={sessionId}
          simState={simState}
          topology={topology}
          onTraceUpdate={handleTraceUpdate}
        />
      </div>

      {/* ── Bottom panel: trace / logs ─────────────────────────────── */}
      <BottomPanel
        open={bottomOpen}
        onToggle={() => setBottomOpen((v) => !v)}
        tab={bottomTab}
        onTabChange={setBottomTab}
        trace={trace}
        currentStep={currentStep}
        isPlaying={isPlaying}
        speed={speed}
        totalSteps={trace.length}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onStep={() => setCurrentStep((s) => Math.min(s + 1, trace.length))}
        onReset={() => { setIsPlaying(false); setCurrentStep(0); }}
        onSpeedChange={setSpeed}
        onStepChange={(s) => {
          setCurrentStep(s);
          if (s >= trace.length) setIsPlaying(false);
        }}
      />
    </div>
  );
}
