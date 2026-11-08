"use client";

/**
 * PingPanel — form for issuing a ping from a device in the simulation,
 * and displaying the result.
 */

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { PingResultData, TraceEvent, runPing } from "@/lib/simulation-api";
import { Badge } from "@/components/ui/Badge";
import { CheckCircle2, XCircle, Activity } from "lucide-react";

interface PingPanelProps {
  sessionId: string | null;
  onTraceUpdate: (trace: TraceEvent[]) => void;
}

export function PingPanel({ sessionId, onTraceUpdate }: PingPanelProps) {
  const [deviceId, setDeviceId] = useState("host-a");
  const [targetIp, setTargetIp] = useState("192.168.1.2");
  const [count, setCount] = useState(4);
  const [result, setResult] = useState<PingResultData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handlePing(e: React.FormEvent) {
    e.preventDefault();
    if (!sessionId) return;
    setError(null);
    setLoading(true);

    try {
      const response = await runPing(sessionId, deviceId, targetIp, count);
      setResult(response.ping);
      onTraceUpdate(response.trace);
    } catch (err) {
      const apiErr = err as { error?: { message?: string } };
      setError(apiErr?.error?.message ?? "Ping failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <form onSubmit={handlePing} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wide">
              Source device
            </label>
            <select
              value={deviceId}
              onChange={(e) => setDeviceId(e.target.value)}
              disabled={loading || !sessionId}
              className="px-3 py-2 text-sm rounded-md bg-[var(--surface-overlay)] text-[var(--text-primary)] border border-[var(--surface-border)] focus:border-[var(--accent-primary)] focus:ring-1 focus:ring-[var(--accent-primary)]"
            >
              <option value="host-a">PC-A (host-a)</option>
              <option value="host-b">PC-B (host-b)</option>
            </select>
          </div>
          <Input
            label="Target IP"
            type="text"
            value={targetIp}
            onChange={(e) => setTargetIp(e.target.value)}
            placeholder="192.168.1.2"
            disabled={loading || !sessionId}
          />
        </div>
        <div className="flex items-end gap-3">
          <div className="w-24">
            <Input
              label="Count"
              type="number"
              value={count}
              onChange={(e) => setCount(parseInt(e.target.value) || 1)}
              min={1}
              max={100}
              disabled={loading || !sessionId}
            />
          </div>
          <Button type="submit" loading={loading} disabled={!sessionId}>
            <Activity size={13} aria-hidden="true" />
            Run ping
          </Button>
        </div>
      </form>

      {/* Error */}
      {error && (
        <div
          role="alert"
          className="rounded-md px-3 py-2 text-sm bg-[#3a1a1a] border border-[var(--status-error)] text-[var(--status-error)]"
        >
          {error}
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="rounded-md border border-[var(--surface-border)] bg-[var(--surface-overlay)] p-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs font-medium text-[var(--text-secondary)]">
              Ping {result.target_ip}
            </span>
            <Badge variant={result.received > 0 ? "success" : "error"}>
              {result.received}/{result.sent} received
            </Badge>
          </div>
          <ul className="space-y-0.5">
            {result.results.map((r) => (
              <li
                key={r.sequence}
                className="flex items-center gap-2 text-xs font-mono"
              >
                {r.success ? (
                  <CheckCircle2
                    size={12}
                    className="text-[var(--status-success)]"
                    aria-hidden="true"
                  />
                ) : (
                  <XCircle
                    size={12}
                    className="text-[var(--status-error)]"
                    aria-hidden="true"
                  />
                )}
                <span className="text-[var(--text-secondary)]">
                  seq={r.sequence}
                </span>
                {r.success && r.rtt_ticks !== null && (
                  <span className="text-[var(--text-muted)]">
                    rtt={r.rtt_ticks} ticks
                  </span>
                )}
                {r.drop_reason && (
                  <span className="text-[var(--status-error)]">
                    {r.drop_reason}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
