"use client";

import { useState, useCallback } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { TopologyCanvas } from "@/components/labs/TopologyCanvas";
import { PingPanel } from "@/components/labs/PingPanel";
import { TraceViewer } from "@/components/labs/TraceViewer";
import { PlaybackControls } from "@/components/labs/PlaybackControls";
import {
  DEFAULT_TOPOLOGY,
  TraceEvent,
  createSimulation,
  resetSimulation,
} from "@/lib/simulation-api";
import { Play, RotateCcw, Wifi, Eye, EyeOff } from "lucide-react";

export default function LabsPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Playback
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [speed, setSpeed] = useState(700);

  // Simulation overlay toggle
  const [showSimulation, setShowSimulation] = useState(true);

  const totalSteps = trace.length;

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
      const session = await createSimulation(DEFAULT_TOPOLOGY, 42);
      setSessionId(session.id);
    } catch (err) {
      const e = err as { error?: { message?: string } };
      setError(e?.error?.message ?? "Failed to create simulation.");
    } finally {
      setCreating(false);
    }
  }, []);

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

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* Header */}
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
          {sessionId && (
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

      {/* Topology + controls */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Topology
            </h2>
            <div className="flex items-center gap-2">
              {/* Simulation mode toggle */}
              {trace.length > 0 && (
                <Button
                  size="sm"
                  variant={showSimulation ? "primary" : "secondary"}
                  onClick={() => setShowSimulation((v) => !v)}
                >
                  {showSimulation ? (
                    <><EyeOff size={12} aria-hidden="true" /> Hide simulation</>
                  ) : (
                    <><Eye size={12} aria-hidden="true" /> Show simulation</>
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
            </div>
          </div>
        </CardHeader>
        <CardBody className="p-0">
          <TopologyCanvas
            topology={DEFAULT_TOPOLOGY}
            trace={trace}
            isPlaying={isPlaying}
            currentStep={currentStep}
            speed={speed}
            onStepChange={handleStepChange}
            totalSteps={totalSteps}
            showSimulation={showSimulation}
          />
          {/* Playback controls */}
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
        </CardBody>
      </Card>

      {/* Ping + trace panel */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card>
          <CardHeader>
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">Ping</h2>
          </CardHeader>
          <CardBody>
            {!sessionId ? (
              <p className="text-sm text-[var(--text-secondary)] text-center py-8">
                Start a simulation first.
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

      {!sessionId && (
        <p className="text-center text-xs text-[var(--text-muted)] py-2">
          Default topology: PC-A — SW1 — PC-B. Click &quot;Start simulation&quot;,
          then run a ping to watch packet flow.
        </p>
      )}
    </div>
  );
}
