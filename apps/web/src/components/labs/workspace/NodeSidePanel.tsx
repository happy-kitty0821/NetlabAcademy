"use client";

/**
 * NodeSidePanel — right panel (CML style).
 * Opens when a node is selected on the canvas.
 * Tabs: Properties · Interfaces · Terminal
 */

import { Settings2, Network, Terminal, X, Edit2 } from "lucide-react";
import { DeviceTerminal } from "@/components/labs/DeviceTerminal";
import { PingPanel }      from "@/components/labs/PingPanel";
import type { DeviceNode } from "@/lib/deviceTypes";
import type { TopologyDocument, TopologyNode, TraceEvent } from "@/lib/simulation-api";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";

type RightTab = "properties" | "interfaces" | "terminal";

// CML palette
const P = {
  bg:     "#16213e",
  border: "#0f3460",
  label:  "#cdd6f4",
  muted:  "#7c7f93",
  active: "#00b4d8",
  error:  "#e94560",
  green:  "#a6e3a1",
  hover:  "#0f3460",
};

interface NodeSidePanelProps {
  flowNode:      DeviceNode;
  topoNode:      TopologyNode | null;
  topology:      TopologyDocument | null;
  tab:           RightTab;
  onTabChange:   (t: RightTab) => void;
  sessionId:     string | null;
  simState:      SimState;
  trace:         TraceEvent[];
  onTraceUpdate: (trace: TraceEvent[]) => void;
  onClose:       () => void;
  onOpenConfig:  () => void;
}

export function NodeSidePanel({
  flowNode, topoNode, topology,
  tab, onTabChange,
  sessionId, simState,
  onTraceUpdate,
  onClose, onOpenConfig,
}: NodeSidePanelProps) {
  const isRunning = simState === "running";

  const TABS: { id: RightTab; Icon: React.ElementType; label: string }[] = [
    { id: "properties", Icon: Settings2, label: "Props"    },
    { id: "interfaces", Icon: Network,   label: "Ifaces"   },
    { id: "terminal",   Icon: Terminal,  label: "Terminal" },
  ];

  return (
    <div
      className="flex flex-col shrink-0"
      style={{ width: 280, background: P.bg, borderLeft: `1px solid ${P.border}` }}
    >
      {/* Title bar */}
      <div
        className="flex items-center justify-between px-3"
        style={{ height: 36, borderBottom: `1px solid ${P.border}` }}
      >
        <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "monospace", color: P.label, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {String(flowNode.data.hostname || flowNode.id)}
        </span>
        <div className="flex items-center gap-1">
          {!isRunning && (
            <button
              onClick={onOpenConfig}
              title="Edit configuration"
              style={{ padding: 4, borderRadius: 4, color: P.muted, background: "transparent", border: "none", cursor: "pointer" }}
              onMouseEnter={(e) => { e.currentTarget.style.color = P.active; e.currentTarget.style.background = P.hover; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = P.muted; e.currentTarget.style.background = "transparent"; }}
            >
              <Edit2 size={12} />
            </button>
          )}
          <button
            onClick={onClose}
            title="Close"
            style={{ padding: 4, borderRadius: 4, color: P.muted, background: "transparent", border: "none", cursor: "pointer" }}
            onMouseEnter={(e) => { e.currentTarget.style.color = P.label; e.currentTarget.style.background = P.hover; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = P.muted; e.currentTarget.style.background = "transparent"; }}
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex" style={{ borderBottom: `1px solid ${P.border}` }}>
        {TABS.map(({ id, Icon, label }) => (
          <button
            key={id}
            onClick={() => onTabChange(id)}
            className="flex-1 flex flex-col items-center gap-0.5 py-2 transition-colors"
            style={{
              fontSize:     10,
              fontFamily:   "monospace",
              color:        tab === id ? P.active : P.muted,
              borderBottom: tab === id ? `2px solid ${P.active}` : "2px solid transparent",
              background:   "transparent",
              border:       "none",
              borderBottomStyle: "solid",
              borderBottomWidth: 2,
              borderBottomColor: tab === id ? P.active : "transparent",
              cursor: "pointer",
            }}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {tab === "properties" && (
          <PropertiesTab flowNode={flowNode} topoNode={topoNode} isRunning={isRunning} />
        )}
        {tab === "interfaces" && (
          <InterfacesTab flowNode={flowNode} topoNode={topoNode} topology={topology} />
        )}
        {tab === "terminal" && (
          <TerminalTab
            flowNode={flowNode}
            sessionId={sessionId}
            isRunning={isRunning}
            onTraceUpdate={onTraceUpdate}
          />
        )}
      </div>
    </div>
  );
}

// ── Properties ────────────────────────────────────────────────────────────────

function PropertiesTab({ flowNode, topoNode, isRunning }: {
  flowNode:  DeviceNode;
  topoNode:  TopologyNode | null;
  isRunning: boolean;
}) {
  const ifaces = topoNode?.interfaces ?? [];
  const hasIp  = ifaces.some((i: { ip?: string }) => i.ip);
  const model  =
    flowNode.data.model === "host"   ? "PC / Host"      :
    flowNode.data.model === "switch" ? "Catalyst 2960"  :
    "ISR 2911";

  return (
    <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 16, fontFamily: "monospace", fontSize: 11 }}>
      <Section label="State">
        <Row label="Status">
          <span style={{ color: isRunning ? P.green : P.muted, display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: isRunning ? P.green : P.muted, display: "inline-block" }} />
            {isRunning ? "ACTIVE" : "STOPPED"}
          </span>
        </Row>
      </Section>
      <Section label="Node">
        <Row label="Hostname">{String(flowNode.data.hostname || flowNode.id)}</Row>
        <Row label="Model">{model}</Row>
        <Row label="ID"><span style={{ color: P.muted, fontSize: 10 }}>{flowNode.id}</span></Row>
      </Section>
      {hasIp && (
        <Section label="Addresses">
          {ifaces.filter((i: { ip?: string }) => i.ip).map((iface: { name: string; ip?: string }) => (
            <Row key={iface.name} label={iface.name}>
              <span style={{ color: P.active }}>{iface.ip}</span>
            </Row>
          ))}
        </Section>
      )}
      {!hasIp && flowNode.data.model === "host" && flowNode.data.ip && (
        <Section label="Configured IP">
          <Row label="eth0"><span style={{ color: P.active }}>{String(flowNode.data.ip)}</span></Row>
        </Section>
      )}
    </div>
  );
}

// ── Interfaces ────────────────────────────────────────────────────────────────

function InterfacesTab({ flowNode, topoNode, topology }: {
  flowNode:  DeviceNode;
  topoNode:  TopologyNode | null;
  topology:  TopologyDocument | null;
}) {
  const ifaces = topoNode?.interfaces ?? [];

  if (!topology || ifaces.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 80, gap: 6, color: P.muted }}>
        <Network size={16} />
        <span style={{ fontSize: 10, fontFamily: "monospace" }}>
          {topology ? "No interfaces" : "Start simulation first"}
        </span>
      </div>
    );
  }

  const peerMap: Record<string, string> = {};
  for (const link of topology.links) {
    if (link.device_a === flowNode.id) peerMap[link.interface_a] = link.device_b;
    if (link.device_b === flowNode.id) peerMap[link.interface_b] = link.device_a;
  }

  return (
    <table style={{ width: "100%", fontFamily: "monospace", fontSize: 10, borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ borderBottom: `1px solid ${P.border}` }}>
          {["Interface", "IP", "Peer"].map((h) => (
            <th key={h} style={{ textAlign: "left", padding: "6px 10px", color: P.muted, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase" }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {ifaces.map((iface: { name: string; ip?: string }) => {
          const peerId   = peerMap[iface.name];
          const peerNode = topology.nodes.find((n) => n.id === peerId);
          return (
            <tr key={iface.name} style={{ borderBottom: `1px solid ${P.border}` }}>
              <td style={{ padding: "6px 10px", color: P.muted }}>{iface.name}</td>
              <td style={{ padding: "6px 10px", color: P.active }}>{iface.ip || "—"}</td>
              <td style={{ padding: "6px 10px", color: P.label }}>{peerNode ? (peerNode.hostname ?? peerNode.id) : "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ── Terminal ──────────────────────────────────────────────────────────────────

function TerminalTab({ flowNode, sessionId, isRunning, onTraceUpdate }: {
  flowNode:      DeviceNode;
  sessionId:     string | null;
  isRunning:     boolean;
  onTraceUpdate: (trace: TraceEvent[]) => void;
}) {
  if (!isRunning || !sessionId) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, padding: "24px 16px", textAlign: "center", color: P.muted }}>
        <Terminal size={18} />
        <p style={{ fontSize: 10, fontFamily: "monospace", lineHeight: 1.6 }}>
          Click <span style={{ color: P.green }}>Start</span> to bring up the simulation, then open the terminal here.
        </p>
      </div>
    );
  }

  const topoNode: TopologyNode = {
    id:         flowNode.id,
    model:      flowNode.data.model as TopologyNode["model"],
    hostname:   String(flowNode.data.hostname ?? flowNode.id),
    interfaces: [],
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {flowNode.data.model === "host" && (
        <div style={{ padding: 8, borderBottom: `1px solid ${P.border}` }}>
          <PingPanel sessionId={sessionId} onTraceUpdate={onTraceUpdate} />
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <DeviceTerminal
          key={`${flowNode.id}-${sessionId}`}
          sessionId={sessionId}
          device={topoNode}
          onClose={() => {}}
        />
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: P.muted, marginBottom: 6 }}>
        {label}
      </div>
      <div>{children}</div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, padding: "2px 0" }}>
      <span style={{ color: P.muted, flexShrink: 0 }}>{label}</span>
      <span style={{ color: "#cdd6f4", textAlign: "right", wordBreak: "break-all" }}>{children}</span>
    </div>
  );
}
