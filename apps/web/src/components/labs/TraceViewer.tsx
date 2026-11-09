"use client";

/**
 * TraceViewer — terminal-style display for simulation event traces.
 *
 * Renders events with colour-coded type names, timestamps, and metadata.
 * Scrollable, with a header showing event count and a clear visual
 * distinction from regular page content.
 */

import { TraceEvent } from "@/lib/simulation-api";

interface TraceViewerProps {
  events: TraceEvent[];
  loading?: boolean;
  currentStep?: number;  // index of the active event during playback
}

// Event type → colour class for the type label.
const TYPE_COLORS: Record<string, string> = {
  ARPRequestSent:       "text-[var(--status-warning)]",
  ARPReplySent:         "text-[var(--status-warning)]",
  ARPCacheUpdated:      "text-[#d4a72c]",
  MACTableLearned:      "text-[#bf96ff]",
  ICMPEchoRequestSent:  "text-[var(--status-success)]",
  ICMPEchoReplySent:    "text-[var(--status-success)]",
  FrameTransmit:        "text-[var(--accent-primary)]",
  FrameArrival:         "text-[var(--text-secondary)]",
  FrameDropped:         "text-[var(--status-error)]",
  TraceLimitReached:    "text-[var(--status-error)]",
};

export function TraceViewer({ events, loading, currentStep }: TraceViewerProps) {
  return (
    <div className="rounded-lg overflow-hidden border border-[var(--surface-border)]">
      {/* Header bar */}
      <div className="flex items-center gap-1.5 px-3 py-2.5 bg-[var(--terminal-bg)] border-b border-[var(--surface-border)]">
        {["#f85149", "#d29922", "#3fb950"].map((c, i) => (
          <span
            key={i}
            className="w-2.5 h-2.5 rounded-full"
            style={{ background: c }}
            aria-hidden="true"
          />
        ))}
        <span className="ml-2 text-xs text-[var(--text-muted)] font-mono">
          event trace {events.length > 0 && `(${events.length} events)`}
        </span>
        {loading && (
          <span className="ml-auto text-xs text-[var(--accent-primary)] font-mono animate-pulse">
            running...
          </span>
        )}
      </div>

      {/* Trace body */}
      <div
        className="p-4 text-xs font-mono leading-relaxed bg-[var(--terminal-bg)] overflow-x-auto max-h-[400px] overflow-y-auto"
        role="log"
        aria-label="Simulation event trace"
      >
        {events.length === 0 && !loading && (
          <span className="text-[var(--text-muted)]">
            No events yet. Run a ping to generate a trace.
          </span>
        )}
        {loading && events.length === 0 && (
          <span className="text-[var(--text-muted)] animate-pulse">
            Waiting for events...
          </span>
        )}
        {events.map((evt, i) => (
          <TraceLine
            key={`${evt.seq}-${i}`}
            event={evt}
            active={currentStep !== undefined && i === currentStep}
          />
        ))}
      </div>
    </div>
  );
}

function TraceLine({ event, active }: { event: TraceEvent; active?: boolean }) {
  const colorClass = TYPE_COLORS[event.type] ?? "text-[var(--text-primary)]";
  const timeStr = String(event.time).padStart(4, " ");

  let detail = "";
  if (event.operation) {
    detail = `${event.sender_ip} -> ${event.target_ip} (${event.operation})`;
  } else if (event.icmp_type) {
    detail = `seq=${event.sequence} ${event.icmp_type}`;
  } else if (event.reason) {
    detail = `dropped: ${event.reason}`;
  } else if (event.mac_address && event.interface_name) {
    detail = `${event.mac_address} on ${event.interface_name}`;
  } else if (event.ip_address && event.mac_address) {
    detail = `${event.ip_address} -> ${event.mac_address}`;
  } else if (event.interface_name) {
    detail = `iface: ${event.interface_name}`;
  }

  return (
    <div
      className={`flex gap-2 whitespace-nowrap px-1 rounded ${
        active ? "bg-[var(--accent-subtle)] border-l-2 border-[var(--accent-primary)]" : ""
      }`}
    >
      <span className="text-[var(--text-muted)] select-none">{timeStr}</span>
      <span className={colorClass}>{event.type}</span>
      {detail && (
        <span className="text-[var(--text-secondary)]">{detail}</span>
      )}
    </div>
  );
}
