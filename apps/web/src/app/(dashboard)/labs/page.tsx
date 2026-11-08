"use client";

import { useState, useCallback } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { TopologyView } from "@/components/labs/TopologyView";
import { PingPanel } from "@/components/labs/PingPanel";
import { TraceViewer } from "@/components/labs/TraceViewer";
import {
  DEFAULT_TOPOLOGY,
  TraceEvent,
  createSimulation,
  resetSimulation,
} from "@/lib/simulation-api";
import { FlaskConical, Play, RotateCcw, Wifi } from "lucide-react";

export default function LabsPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleCreateSession = useCallback(async () => {
    setError(null);
    setCreating(true);
    setTrace([]);
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
    try {
      const result = await resetSimulation(sessionId);
      setTrace(result.trace);
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
            Build a topology, run simulations and inspect packet traces.
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

      {/* Topology section */}
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
                  Reset
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardBody>
          <TopologyView topology={DEFAULT_TOPOLOGY} />
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
                <FlaskConical
                  size={20}
                  className="text-[var(--text-muted)]"
                  aria-hidden="true"
                />
                <p className="text-sm text-[var(--text-secondary)]">
                  Start a simulation to run pings.
                </p>
              </div>
            ) : (
              <PingPanel
                sessionId={sessionId}
                onTraceUpdate={setTrace}
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
            <TraceViewer events={trace} />
          </CardBody>
        </Card>
      </div>

      {/* Info banner */}
      {!sessionId && (
        <div className="text-center py-4">
          <p className="text-xs text-[var(--text-muted)]">
            The default topology has two PCs connected through a switch.
            Click &quot;Start simulation&quot; to create a live session, then run a ping
            to observe ARP resolution and ICMP echo in the event trace.
          </p>
        </div>
      )}
    </div>
  );
}
