"use client";

/**
 * BottomPanel — CML-style bottom panel.
 *
 * Shows:
 *  - Terminal tab: xterm.js CLI for the selected device
 *  - Logs tab:     simulation event trace
 *
 * Collapsible (click tab bar to toggle), resizable by dragging the top edge.
 * Sits at the bottom of the workspace, below the canvas.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Terminal, Activity, ChevronDown, ChevronUp } from "lucide-react";
import { DeviceTerminal } from "@/components/labs/DeviceTerminal";
import { PingPanel }      from "@/components/labs/PingPanel";
import type { DeviceNode }   from "@/lib/deviceTypes";
import type { TopologyNode, TraceEvent } from "@/lib/simulation-api";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";

type BottomTab = "terminal" | "logs";

interface BottomPanelProps {
  selectedNode:  DeviceNode | null;
  sessionId:     string | null;
  simState:      SimState;
  trace:         TraceEvent[];
  onTraceUpdate: (t: TraceEvent[]) => void;
}

const DEFAULT_HEIGHT = 260;
const MIN_HEIGHT     = 120;
const MAX_HEIGHT     = 600;

export function BottomPanel({
  selectedNode, sessionId, simState, trace, onTraceUpdate,
}: BottomPanelProps) {
  const [open,   setOpen]   = useState(false);
  const [tab,    setTab]    = useState<BottomTab>("terminal");
  const [height, setHeight] = useState(DEFAULT_HEIGHT);
  const dragging = useRef(false);
  const startY   = useRef(0);
  const startH   = useRef(0);
  const isRunning = simState === "running";

  // Open panel when a node is selected or sim starts
  useEffect(() => {
    if (selectedNode) setOpen(true);
  }, [selectedNode?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Drag-resize from top edge ─────────────────────────────────────────────
  const onDragStart = useCallback((e: React.MouseEvent) => {
    dragging.current = true;
    startY.current   = e.clientY;
    startH.current   = height;
    e.preventDefault();
  }, [height]);

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragging.current) return;
      const delta = startY.current - e.clientY;
      setHeight(Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, startH.current + delta)));
    }
    function onUp() { dragging.current = false; }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // ── Tab bar ───────────────────────────────────────────────────────────────
  const TABS: { id: BottomTab; icon: React.ElementType; label: string; badge?: number }[] = [
    { id: "terminal", icon: Terminal, label: "Terminal" },
    { id: "logs",     icon: Activity, label: "Event Log",
      badge: trace.length > 0 ? trace.length : undefined },
  ];

  const deviceLabel = selectedNode
    ? String(selectedNode.data.hostname || selectedNode.id)
    : null;

  return (
    <div
      style={{
        background:   "#ffffff",
        borderTop:    "1px solid #d0d7de",
        flexShrink:   0,
        display:      "flex",
        flexDirection:"column",
      }}
    >
      {/* Resize handle */}
      {open && (
        <div
          onMouseDown={onDragStart}
          style={{
            height: 4, cursor: "row-resize", background: "transparent",
            borderTop: "2px solid transparent",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderTopColor = "#0969da"; }}
          onMouseLeave={(e) => { e.currentTarget.style.borderTopColor = "transparent"; }}
        />
      )}

      {/* Tab bar */}
      <div style={{
        display:        "flex",
        alignItems:     "center",
        height:         36,
        padding:        "0 12px",
        gap:            4,
        borderBottom:   open ? "1px solid #d0d7de" : "none",
        background:     "#f6f8fa",
        userSelect:     "none",
      }}>
        {/* Tabs */}
        {TABS.map(({ id, icon: Icon, label, badge }) => (
          <button
            key={id}
            onClick={() => { setTab(id); setOpen(true); }}
            style={{
              display:      "flex",
              alignItems:   "center",
              gap:          5,
              padding:      "4px 10px",
              borderRadius: 5,
              fontSize:     12,
              fontWeight:   tab === id && open ? 600 : 400,
              color:        tab === id && open ? "#0969da" : "#656d76",
              background:   tab === id && open ? "#ddf4ff" : "transparent",
              border:       "none",
              cursor:       "pointer",
              transition:   "color 0.15s, background 0.15s",
            }}
          >
            <Icon size={12} />
            {label}
            {badge !== undefined && (
              <span style={{
                fontSize: 10, fontWeight: 700, padding: "1px 5px",
                borderRadius: 10, background: "#ddf4ff", color: "#0969da",
              }}>
                {badge}
              </span>
            )}
          </button>
        ))}

        {/* Device label */}
        {deviceLabel && (
          <span style={{
            fontSize: 11, color: "#9198a1", fontFamily: "monospace",
            marginLeft: 4, padding: "2px 7px",
            background: "#f0f2f4", borderRadius: 4,
          }}>
            {deviceLabel}
          </span>
        )}

        <div style={{ flex: 1 }} />

        {/* Toggle open/close */}
        <button
          onClick={() => setOpen((v) => !v)}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "4px 8px", borderRadius: 5, fontSize: 11,
            color: "#656d76", background: "transparent", border: "none", cursor: "pointer",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#f0f2f4"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
          title={open ? "Collapse panel" : "Expand panel"}
        >
          {open ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
          {open ? "Hide" : "Show"}
        </button>
      </div>

      {/* Panel body */}
      {open && (
        <div style={{ height, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          {tab === "terminal" && (
            <TerminalPane
              selectedNode={selectedNode}
              sessionId={sessionId}
              isRunning={isRunning}
              onTraceUpdate={onTraceUpdate}
            />
          )}
          {tab === "logs" && (
            <LogsPane trace={trace} />
          )}
        </div>
      )}
    </div>
  );
}

// ── Terminal pane ─────────────────────────────────────────────────────────────

function TerminalPane({
  selectedNode, sessionId, isRunning, onTraceUpdate,
}: {
  selectedNode:  DeviceNode | null;
  sessionId:     string | null;
  isRunning:     boolean;
  onTraceUpdate: (t: TraceEvent[]) => void;
}) {
  if (!selectedNode) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 8,
        color: "#9198a1", padding: 24 }}>
        <Terminal size={20} />
        <p style={{ fontSize: 12, margin: 0, fontFamily: "monospace" }}>
          Click a device on the canvas to open its terminal
        </p>
      </div>
    );
  }

  if (!isRunning || !sessionId) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 8,
        color: "#9198a1", padding: 24, textAlign: "center" }}>
        <Terminal size={20} />
        <p style={{ fontSize: 12, margin: 0, fontFamily: "monospace", lineHeight: 1.6 }}>
          Click <strong style={{ color: "#1a7f37" }}>Start</strong> to bring up the simulation,<br />
          then the terminal for <strong style={{ color: "#1f2328" }}>
            {String(selectedNode.data.hostname || selectedNode.id)}
          </strong> will open here.
        </p>
      </div>
    );
  }

  const topoNode: TopologyNode = {
    id:         selectedNode.id,
    model:      selectedNode.data.model as TopologyNode["model"],
    hostname:   String(selectedNode.data.hostname ?? selectedNode.id),
    interfaces: [],
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      {selectedNode.data.model === "host" && (
        <div style={{ padding: "6px 12px", borderBottom: "1px solid #d0d7de", background: "#f6f8fa" }}>
          <PingPanel sessionId={sessionId} onTraceUpdate={onTraceUpdate} />
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <DeviceTerminal
          key={`${selectedNode.id}-${sessionId}`}
          sessionId={sessionId}
          device={topoNode}
          onClose={() => {}}
        />
      </div>
    </div>
  );
}

// ── Logs / event trace pane ───────────────────────────────────────────────────

function LogsPane({ trace }: { trace: TraceEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [trace.length]);

  if (trace.length === 0) {
    return (
      <div style={{ flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 8,
        color: "#9198a1", padding: 24 }}>
        <Activity size={20} />
        <p style={{ fontSize: 12, margin: 0, fontFamily: "monospace" }}>
          Run a ping to see event trace
        </p>
      </div>
    );
  }

  const TYPE_COLOR: Record<string, string> = {
    arp_request:   "#9a6700",
    arp_reply:     "#1a7f37",
    icmp_echo:     "#0969da",
    icmp_reply:    "#0969da",
    frame_forward: "#656d76",
    mac_learned:   "#6639ba",
    stp:           "#d1242f",
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", fontFamily: "monospace",
      fontSize: 11, background: "#0d1117", color: "#e6edf3" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead style={{ position: "sticky", top: 0, background: "#161b22", zIndex: 1 }}>
          <tr>
            {["T", "Type", "Device", "Detail"].map((h) => (
              <th key={h} style={{ textAlign: "left", padding: "4px 10px",
                color: "#656d76", fontSize: 9, fontWeight: 700,
                letterSpacing: "0.08em", textTransform: "uppercase",
                borderBottom: "1px solid #30363d" }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trace.map((ev, i) => {
            const color = TYPE_COLOR[ev.type] ?? "#656d76";
            const device = ev.device_id ?? ev.switch_id ?? ev.src_device_id ?? "";
            const detail = ev.ip_address ?? ev.mac_address ?? ev.target_ip
              ?? ev.sender_ip ?? ev.reason ?? ev.message_type ?? "";
            return (
              <tr key={i} style={{ borderBottom: "1px solid #21262d" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "#161b22"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
                <td style={{ padding: "3px 10px", color: "#484f58", width: 50 }}>
                  {ev.time}
                </td>
                <td style={{ padding: "3px 10px", color, fontWeight: 600, whiteSpace: "nowrap" }}>
                  {ev.type.replace(/_/g, " ")}
                </td>
                <td style={{ padding: "3px 10px", color: "#8b949e", width: 100 }}>
                  {device}
                </td>
                <td style={{ padding: "3px 10px", color: "#e6edf3" }}>
                  {detail}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div ref={bottomRef} />
    </div>
  );
}
