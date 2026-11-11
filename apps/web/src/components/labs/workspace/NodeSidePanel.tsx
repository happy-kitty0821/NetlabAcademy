"use client";

import { Settings2, Network, Terminal, X, Edit2 } from "lucide-react";
import { DeviceTerminal } from "@/components/labs/DeviceTerminal";
import { PingPanel }      from "@/components/labs/PingPanel";
import type { DeviceNode } from "@/lib/deviceTypes";
import type { TopologyDocument, TopologyNode, TraceEvent } from "@/lib/simulation-api";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";

type RightTab = "properties" | "interfaces" | "terminal";

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

const P = {
  bg:     "#ffffff",
  border: "#d0d7de",
  hover:  "#f6f8fa",
  label:  "#1f2328",
  muted:  "#656d76",
  accent: "#0969da",
  green:  "#1a7f37",
  error:  "#d1242f",
};

export function NodeSidePanel({
  flowNode, topoNode, topology,
  tab, onTabChange,
  sessionId, simState,
  onTraceUpdate, onClose, onOpenConfig,
}: NodeSidePanelProps) {
  const isRunning = simState === "running";

  const TABS = [
    { id: "properties" as RightTab, Icon: Settings2, label: "Props"   },
    { id: "interfaces" as RightTab, Icon: Network,   label: "Ifaces"  },
    { id: "terminal"   as RightTab, Icon: Terminal,  label: "Terminal"},
  ];

  return (
    <div style={{ width: 280, background: P.bg, borderLeft: `1px solid ${P.border}`,
      display: "flex", flexDirection: "column", flexShrink: 0 }}>
      {/* Title */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 12px", height: 36, borderBottom: `1px solid ${P.border}` }}>
        <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "monospace", color: P.label,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {String(flowNode.data.hostname || flowNode.id)}
        </span>
        <div style={{ display: "flex", gap: 2 }}>
          {!isRunning && (
            <Btn onClick={onOpenConfig} title="Edit" icon={<Edit2 size={12} />} />
          )}
          <Btn onClick={onClose} title="Close" icon={<X size={12} />} />
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", borderBottom: `1px solid ${P.border}` }}>
        {TABS.map(({ id, Icon, label }) => (
          <button key={id} onClick={() => onTabChange(id)}
            style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center",
              gap: 2, padding: "7px 0", fontSize: 10, fontFamily: "monospace",
              color: tab === id ? P.accent : P.muted,
              borderBottom: `2px solid ${tab === id ? P.accent : "transparent"}`,
              background: "transparent", border: "none",
              borderBottomStyle: "solid", borderBottomWidth: 2,
              borderBottomColor: tab === id ? P.accent : "transparent",
              cursor: "pointer", transition: "color 0.15s" }}>
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
        {tab === "properties" && <PropsTab flowNode={flowNode} topoNode={topoNode} isRunning={isRunning} />}
        {tab === "interfaces" && <IfacesTab flowNode={flowNode} topoNode={topoNode} topology={topology} />}
        {tab === "terminal"   && <TermTab  flowNode={flowNode} sessionId={sessionId} isRunning={isRunning} onTraceUpdate={onTraceUpdate} />}
      </div>
    </div>
  );
}

function Btn({ onClick, title, icon }: { onClick: () => void; title: string; icon: React.ReactNode }) {
  return (
    <button onClick={onClick} title={title}
      style={{ padding: 4, borderRadius: 4, border: "none", background: "transparent",
        color: "#656d76", cursor: "pointer" }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "#f0f2f4"; e.currentTarget.style.color = "#1f2328"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "#656d76"; }}>
      {icon}
    </button>
  );
}

function PropsTab({ flowNode, topoNode, isRunning }: { flowNode: DeviceNode; topoNode: TopologyNode | null; isRunning: boolean }) {
  const ifaces = topoNode?.interfaces ?? [];
  const hasIp  = ifaces.some((i: { ip?: string }) => i.ip);
  const model  = flowNode.data.model === "host" ? "PC / Host" : flowNode.data.model === "switch" ? "Catalyst 2960" : "ISR 2911";

  return (
    <div style={{ padding: "12px 14px", display: "flex", flexDirection: "column", gap: 14, fontFamily: "monospace", fontSize: 11 }}>
      <Sect label="State">
        <Row label="Status">
          <span style={{ color: isRunning ? "#1a7f37" : "#656d76", display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: isRunning ? "#1a7f37" : "#d0d7de", display: "inline-block" }} />
            {isRunning ? "ACTIVE" : "STOPPED"}
          </span>
        </Row>
      </Sect>
      <Sect label="Node">
        <Row label="Hostname">{String(flowNode.data.hostname || flowNode.id)}</Row>
        <Row label="Model">{model}</Row>
        <Row label="ID"><span style={{ color: "#9198a1", fontSize: 10 }}>{flowNode.id}</span></Row>
      </Sect>
      {!hasIp && flowNode.data.model === "host" && flowNode.data.ip && (
        <Sect label="IP">
          <Row label="eth0"><span style={{ color: "#0969da" }}>{String(flowNode.data.ip)}</span></Row>
        </Sect>
      )}
      {hasIp && (
        <Sect label="Addresses">
          {ifaces.filter((i: { ip?: string }) => i.ip).map((iface: { name: string; ip?: string }) => (
            <Row key={iface.name} label={iface.name}><span style={{ color: "#0969da" }}>{iface.ip}</span></Row>
          ))}
        </Sect>
      )}
    </div>
  );
}

function IfacesTab({ flowNode, topoNode, topology }: { flowNode: DeviceNode; topoNode: TopologyNode | null; topology: TopologyDocument | null }) {
  const ifaces = topoNode?.interfaces ?? [];
  if (!topology || ifaces.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 80, gap: 6, color: "#9198a1" }}>
        <Network size={16} />
        <span style={{ fontSize: 10, fontFamily: "monospace" }}>{topology ? "No interfaces" : "Start simulation first"}</span>
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
        <tr style={{ borderBottom: "1px solid #d0d7de" }}>
          {["Interface", "IP", "Peer"].map((h) => (
            <th key={h} style={{ textAlign: "left", padding: "5px 10px", color: "#656d76", fontWeight: 700, fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase" }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {ifaces.map((iface: { name: string; ip?: string }) => {
          const peerNode = topology.nodes.find((n) => n.id === peerMap[iface.name]);
          return (
            <tr key={iface.name} style={{ borderBottom: "1px solid #f0f2f4" }}>
              <td style={{ padding: "5px 10px", color: "#656d76" }}>{iface.name}</td>
              <td style={{ padding: "5px 10px", color: "#0969da" }}>{iface.ip || "—"}</td>
              <td style={{ padding: "5px 10px", color: "#1f2328" }}>{peerNode ? (peerNode.hostname ?? peerNode.id) : "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function TermTab({ flowNode, sessionId, isRunning, onTraceUpdate }: { flowNode: DeviceNode; sessionId: string | null; isRunning: boolean; onTraceUpdate: (t: TraceEvent[]) => void }) {
  if (!isRunning || !sessionId) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, padding: "24px 16px", textAlign: "center", color: "#9198a1" }}>
        <Terminal size={18} />
        <p style={{ fontSize: 10, fontFamily: "monospace", lineHeight: 1.6, margin: 0 }}>
          Click <span style={{ color: "#1a7f37", fontWeight: 700 }}>Start</span> to bring up the simulation, then open the terminal.
        </p>
      </div>
    );
  }
  const topoNode: TopologyNode = { id: flowNode.id, model: flowNode.data.model as TopologyNode["model"],
    hostname: String(flowNode.data.hostname ?? flowNode.id), interfaces: [] };
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {flowNode.data.model === "host" && (
        <div style={{ padding: 8, borderBottom: "1px solid #d0d7de" }}>
          <PingPanel sessionId={sessionId} onTraceUpdate={onTraceUpdate} />
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <DeviceTerminal key={`${flowNode.id}-${sessionId}`} sessionId={sessionId} device={topoNode} onClose={() => {}} />
      </div>
    </div>
  );
}

function Sect({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "#9198a1", marginBottom: 5 }}>{label}</div>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, padding: "2px 0" }}>
      <span style={{ color: "#656d76", flexShrink: 0 }}>{label}</span>
      <span style={{ color: "#1f2328", textAlign: "right", wordBreak: "break-all" }}>{children}</span>
    </div>
  );
}
