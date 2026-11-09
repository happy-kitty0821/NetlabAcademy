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
import { Play, RotateCcw, Wifi } from "lucide-react";

export default function LabsPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Playback state
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [speed, setSpeed] = useState(800); // ms per step

  // Total animation steps = trace length
  const totalSteps = trace.length;

  // When a ping result comes in, load the trace and auto-play
  const handleTraceUpdate = useCallback((newTrace: TraceEvent[]) => {
    setTrace(newTrace);
    setCurrentStep(0);
    setIsPlaying(true); // auto-play on new trace
  }, []);

  // Playback handlers
  const handlePlay = useCallback(() => setIsPlaying(true), []);
  const handlePause = useCallback(() => setIsPlaying(false), []);
  const handleStep = useCallback(() => {
    setCurrentStep((s) => Math.min(s + 1, totalSteps));
  }, [totalSteps]);
  const handleResetPlayback = useCallback(() => {
    setIsPlaying(false);
    setCurrentStep(0);
  }, []);
  const handleStepChange = useCallback((s: number) => {
    setCurrentStep(s);
    if (s >= totalSteps) setIsPlaying(false);
  }, [totalSteps]);

  // Highlight the current trace event in the TraceViewer during playback.
  const traceHighlight =
    trace.length > 0 && currentStep < trace.length ? currentStep : undefined;

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
      const apiErr = err as { error?: { message?: string } };
      setError(apiErr?.error?.message ?? "Failed to create simulation.");
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
      const apiErr = err as { error?: { message?: string } };
      setError(apiErr?.error?.message ?? "Failed to reset simulation.");
    } finally {
      setResetting(false);
    }
  }, [sessionId]);

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">
            Lab Workspace
          </h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Build a topology, run simulations and watch packet flow in real time.
          </p>
        </div>
        {sessionId && (
          <Badge variant="success">
            <Wifi size={11} className="mr-1" aria-hidden="true" />
            Session active
          </Badge>
        )}
      </div>

      {/* Error banner */}
      {error && (
        <div
          role="alert"
          className="rounded-md px-4 py-3 text-sm bg-[#3a1a1a] border border-[var(--status-error)] text-[var(--status-error)]"
        >
          {error}
        </div>
      )}

      {/* Animated topology canvas */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Topology
            </h2>
            <div className="flex items-center gap-2">
              {!sessionId ? (
                <Button
                  size="sm"
                  onClick={handleCreateSession}
                  loading={creating}
                >
                  <Play size={12} aria-hidden="true" />
                  Start simulation
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={handleReset}
                  loading={resetting}
                >
                  <RotateCcw size={12} aria-hidden="true" />
                  Reset sim
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardBody>
          <TopologyCanvas
            topology={DEFAULT_TOPOLOGY}
            trace={trace}
            isPlaying={isPlaying}
            currentStep={currentStep}
            speed={speed}
            onStepChange={handleStepChange}
            totalSteps={totalSteps}
          />

          {/* Playback controls — only show when there's a trace */}
          {trace.length > 0 && (
            <div className="mt-4 pt-4 border-t border-[var(--surface-border)]">
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

      {/* Two-column: ping panel + trace viewer */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Ping panel */}
        <Card>
          <CardHeader>
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Ping
            </h2>
          </CardHeader>
          <CardBody>
            {!sessionId ? (
              <div className="flex flex-col items-center gap-2 py-8 text-center">
                <p className="text-sm text-[var(--text-secondary)]">
                  Start a simulation to run pings.
                </p>
              </div>
            ) : (
              <PingPanel
                sessionId={sessionId}
                onTraceUpdate={handleTraceUpdate}
              />
            )}
          </CardBody>
        </Card>

        {/* Trace viewer */}
        <Card>
          <CardHeader>
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">
              Event trace
            </h2>
          </CardHeader>
          <CardBody>
            <TraceViewer events={trace} currentStep={traceHighlight} />
          </CardBody>
        </Card>
      </div>

      {/* Info banner */}
      {!sessionId && (
        <div className="text-center py-4">
          <p className="text-xs text-[var(--text-muted)]">
            The default topology has two PCs connected through a switch.
            Click &quot;Start simulation&quot; to create a live session, then run a ping
            to watch ARP resolution and ICMP echo packets animate across the topology.
          </p>
        </div>
      )}
    </div>
  );
}
