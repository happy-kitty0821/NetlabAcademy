"use client";
"use client";

import { useState, useCallback } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { TopologyCanvas } from "@/components/labs/TopologyCanvas";
import { TopologyEditor } from "@/components/labs/TopologyEditor";
import { DeviceTerminal } from "@/components/labs/DeviceTerminal";
import { PingPanel } from "@/components/labs/PingPanel";
import { TraceViewer } from "@/components/labs/TraceViewer";
import { PlaybackControls } from "@/components/labs/PlaybackControls";
import {
  DEFAULT_TOPOLOGY,
  type TopologyDocument,
  type TopologyNode,
  type TraceEvent,
  createSimulation,
  resetSimulation,
} from "@/lib/simulation-api";
import { Play, RotateCcw, Wifi, Eye, EyeOff, PenLine, Terminal } from "lucide-react";

export default function LabsPage() {
  // ── Topology state ─────────────────────────────────────────────────────────
  const [topology, setTopology] = useState<TopologyDocument>(DEFAULT_TOPOLOGY);
  const [showEditor, setShowEditor] = useState(false);

  // ── Simulation state ───────────────────────────────────────────────────────
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Playback ───────────────────────────────────────────────────────────────
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [speed, setSpeed] = useState(700);
  const [showSimulation, setShowSimulation] = useState(true);

  // ── Terminal ───────────────────────────────────────────────────────────────
  const [activeTerminal, setActiveTerminal] = useState<TopologyNode | null>(null);

  const totalSteps = trace.length;

  // ── Handlers ───────────────────────────────────────────────────────────────

  /** Called by the TopologyEditor when the user clicks "Use this topology" */
  const handleApplyTopology = useCallback(
    async (newTopo: TopologyDocument) => {
      setTopology(newTopo);
      setShowEditor(false);
      setError(null);
      setTrace([]);
      setCurrentStep(0);
      setIsPlaying(false);
      // Auto-create a simulation session with the new topology
      setCreating(true);
      try {
        const session = await createSimulation(newTopo, 42);
        setSessionId(session.id);
      } catch (err) {
        const e = err as { error?: { message?: string } };
        setError(e?.error?.message ?? "Failed to create simulation.");
      } finally {
        setCreating(false);
      }
    },
    [],
  );

  const handleTraceUpdate = useCallback((newTrace: TraceEvent[]) => {
    setTrace(newTrace);
    setCurrentStep(0);
    setIsPlaying(true);
    setShowSimulation(true);
  }, []);

  const handlePlay = useCallback(() => setIsPlaying(true), []);
  const handlePause = useCallback(() => setIsPlaying(false), []);
  const handleStep = useCallback(
    () => setCurrentStep((s) => Math.min(s + 1, totalSteps)),
    [totalSteps],
  );
  const handleResetPlayback = useCallback(() => {
    setIsPlaying(false);
    setCurrentStep(0);
  }, []);
  const handleStepChange = useCallback(
    (s: number) => {
      setCurrentStep(s);
      if (s >= totalSteps) setIsPlaying(false);
    },
    [totalSteps],
  );

  const handleCreateSession = useCallback(async () => {
    setError(null);
    setCreating(true);
    setTrace([]);
    setCurrentStep(0);
    setIsPlaying(false);
    try {
      const session = await createSimulation(topology, 42);
      setSessionId(session.id);
    } catch (err) {
      const e = err as { error?: { message?: string } };
      setError(e?.error?.message ?? "Failed to create simulation.");
    } finally {
      setCreating(false);
    }
  }, [topology]);

  const handleReset = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    setResetting(true);
    setIsPlaying(false);
    try {
      const result = await resetSimulation(sessionId);
      setTrace(result.trace);
      setCurrentStep(0);
    } catch (err) {
      const e = err as { error?: { message?: string } };
      setError(e?.error?.message ?? "Failed to reset.");
    } finally {
      setResetting(false);
    }
  }, [sessionId]);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="w-full space-y-4 px-1">
      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">
            Lab Workspace
          </h1>
          <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
            Build topologies, run simulations, and inspect packet-by-packet flow.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {sessionId && !showEditor && (
            <Badge variant="success">
              <Wifi size={10} className="mr-1" />
              Session active
            </Badge>
          )}
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-md px-4 py-3 text-sm bg-[#3a1a1a] border border-[#f85149] text-[#f85149]">
          {error}
        </div>
      )}

      {/* ── Topology editor panel ───────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              {showEditor ? "Build topology" : "Topology"}
            </h2>
            <div className="flex items-center gap-2">
              {/* Editor toggle */}
              <Button
                size="sm"
                variant={showEditor ? "primary" : "secondary"}
                onClick={() => setShowEditor((v) => !v)}
              >
                <PenLine size={12} aria-hidden="true" />
                {showEditor ? "Close editor" : "Build topology"}
              </Button>

              {/* Simulation controls (only when editor is closed) */}
              {!showEditor && (
                <>
                  {trace.length > 0 && (
                    <Button
                      size="sm"
                      variant={showSimulation ? "primary" : "secondary"}
                      onClick={() => setShowSimulation((v) => !v)}
                    >
                      {showSimulation ? (
                        <><EyeOff size={12} aria-hidden="true" /> Hide sim</>
                      ) : (
                        <><Eye size={12} aria-hidden="true" /> Show sim</>
                      )}
                    </Button>
                  )}
                  {!sessionId ? (
                    <Button size="sm" onClick={handleCreateSession} loading={creating}>
                      <Play size={12} aria-hidden="true" />
                      Start simulation
                    </Button>
                  ) : (
                    <Button size="sm" variant="secondary" onClick={handleReset} loading={resetting}>
                      <RotateCcw size={12} aria-hidden="true" />
                      Reset
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
        </CardHeader>
        <CardBody className={showEditor ? "p-4" : "p-0"}>
          {showEditor ? (
            <TopologyEditor onApply={handleApplyTopology} />
          ) : (
            <>
              <TopologyCanvas
                topology={topology}
                trace={trace}
                isPlaying={isPlaying}
                currentStep={currentStep}
                speed={speed}
                onStepChange={handleStepChange}
                totalSteps={totalSteps}
                showSimulation={showSimulation}
              />
              {trace.length > 0 && showSimulation && (
                <div className="px-4 py-3 border-t border-[var(--surface-border)]">
                  <PlaybackControls
                    isPlaying={isPlaying}
                    onPlay={handlePlay}
                    onPause={handlePause}
                    onStep={handleStep}
                    onReset={handleResetPlayback}
                    currentStep={currentStep}
                    totalSteps={totalSteps}
                    speed={speed}
                    onSpeedChange={setSpeed}
                  />
                </div>
              )}
            </>
          )}
        </CardBody>
      </Card>

      {/* ── Ping + trace ───────────────────────────────────────────────────── */}
      {!showEditor && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">Ping</h2>
            </CardHeader>
            <CardBody>
              {!sessionId ? (
                <p className="text-sm text-[var(--text-secondary)] text-center py-8">
                  Start a simulation to run pings.
                </p>
              ) : (
                <PingPanel sessionId={sessionId} onTraceUpdate={handleTraceUpdate} />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">Event trace</h2>
            </CardHeader>
            <CardBody>
              <TraceViewer
                events={trace}
                currentStep={showSimulation ? currentStep : undefined}
              />
            </CardBody>
          </Card>
        </div>
      )}

      {/* ── Device terminals ───────────────────────────────────────────────── */}
      {!showEditor && sessionId && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between flex-wrap gap-2">
              <h2 className="text-sm font-semibold text-[var(--text-primary)]">
                Device terminals
              </h2>
              <div className="flex items-center gap-2 flex-wrap">
                {topology.nodes.map((node) => (
                  <Button
                    key={node.id}
                    size="sm"
                    variant={activeTerminal?.id === node.id ? "primary" : "secondary"}
                    onClick={() =>
                      setActiveTerminal(
                        activeTerminal?.id === node.id ? null : node,
                      )
                    }
                  >
                    <Terminal size={12} aria-hidden="true" />
                    {node.hostname ?? node.id}
                  </Button>
                ))}
              </div>
            </div>
          </CardHeader>
          {activeTerminal && (
            <CardBody className="p-0">
              <DeviceTerminal
                key={activeTerminal.id}
                sessionId={sessionId}
                device={activeTerminal}
                onClose={() => setActiveTerminal(null)}
              />
            </CardBody>
          )}
          {!activeTerminal && (
            <CardBody>
              <p className="text-xs text-[var(--text-muted)] text-center py-4">
                Click a device button above to open its CLI terminal.
              </p>
            </CardBody>
          )}
        </Card>
      )}

      {!sessionId && !showEditor && (
        <p className="text-center text-xs text-[var(--text-muted)] py-2">
          Use the default topology or click &quot;Build topology&quot; to design your own.
          Then click &quot;Start simulation&quot; and run a ping.
        </p>
      )}
    </div>
  );
}
