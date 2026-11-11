"use client";

/**
 * NodeSidePanel — right panel shown when a node is selected.
 *
 * Three tabs:
 *  Properties — hostname, model, status, IP summary
 *  Interfaces — interface table with connected peer
 *  Terminal   — xterm.js CLI attached to the selected device
 *
 * Matches Cisco CML right-panel layout.
 */

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

export function NodeSidePanel({
  flowNode, topoNode, topology,
  tab, onTabChange,
  sessionId, simState,
  onTraceUpdate,
  onClose, onOpenConfig,
}: NodeSidePanelProps) {
  const isRunning = simState === "running";

  const TABS: { id: RightTab; Icon: React.ElementType; label: string }[] = [
    { id: "properties", Icon: Settings2, label: "Properties" },
    { id: "interfaces", Icon: Network,   label: "Interfaces" },
    { id: "terminal",   Icon: Terminal,  label: "Terminal"   },
  ];

  return (
    <div
      className="flex flex-col border-l border-[#21262d] shrink-0"
      style={{ width: 288, background: "#161b22" }}
    >
      {/* Panel title + close */}
      <div className="flex items-center justify-between px-3 h-9 border-b border-[#21262d]">
        <span className="text-[11px] font-semibold font-mono text-[#8b949e] uppercase tracking-wider truncate">
          {String(flowNode.data.hostname || flowNode.id)}
        </span>
        <div className="flex items-center gap-1">
          {/* Edit config (only when stopped) */}
          {!isRunning && (
            <button
              onClick={onOpenConfig}
              title="Edit device configuration"
              className="p-1 rounded text-[#484f58] hover:text-[#8b949e] hover:bg-[#21262d] transition-colors"
            >
              <Edit2 size={12} />
            </button>
          )}
          <button
            onClick={onClose}
            title="Close panel"
            className="p-1 rounded text-[#484f58] hover:text-[#8b949e] hover:bg-[#21262d] transition-colors"
            aria-label="Close side panel"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-[#21262d]">
        {TABS.map(({ id, Icon, label }) => (
          <button
            key={id}
            onClick={() => onTabChange(id)}
            className="flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px] font-mono transition-colors"
            style={{
              color:        tab === id ? "#58a6ff" : "#484f58",
              borderBottom: tab === id ? "2px solid #58a6ff" : "2px solid transparent",
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
          <PropertiesTab
            flowNode={flowNode}
            topoNode={topoNode}
            isRunning={isRunning}
          />
        )}
        {tab === "interfaces" && (
          <InterfacesTab
            flowNode={flowNode}
            topoNode={topoNode}
            topology={topology}
          />
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

function PropertiesTab({
  flowNode, topoNode, isRunning,
}: {
  flowNode:  DeviceNode;
  topoNode:  TopologyNode | null;
  isRunning: boolean;
}) {
  const ifaces  = topoNode?.interfaces ?? [];
  const hasIp   = ifaces.some((i: { ip?: string }) => i.ip);
  const model   =
    flowNode.data.model === "host"   ? "PC / Host" :
    flowNode.data.model === "switch" ? `Catalyst 2960` :
    flowNode.data.model === "router" ? "ISR 2911"  : "Unknown";

  return (
    <div className="p-3 space-y-4 text-xs font-mono">
      {/* State */}
      <Section label="State">
        <Row label="Status">
          <span
            className="flex items-center gap-1.5"
            style={{ color: isRunning ? "#3fb950" : "#6e7681" }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: isRunning ? "#3fb950" : "#6e7681" }}
            />
            {isRunning ? "ACTIVE" : "STOPPED"}
          </span>
        </Row>
      </Section>

      {/* Node */}
      <Section label="Node">
        <Row label="Hostname">{String(flowNode.data.hostname || flowNode.id)}</Row>
        <Row label="Model">{model}</Row>
        <Row label="ID"><span className="text-[#484f58]">{flowNode.id}</span></Row>
        <Row label="Ports">{String(ifaces.length)}</Row>
      </Section>

      {/* Addresses */}
      {hasIp && (
        <Section label="Addresses">
          {ifaces.filter((i: { ip?: string }) => i.ip).map((iface: { name: string; ip?: string }) => (
            <Row key={iface.name} label={iface.name}>
              <span className="text-[#58a6ff]">{iface.ip}</span>
            </Row>
          ))}
        </Section>
      )}

      {/* Host IP from canvas (pre-simulation) */}
      {!hasIp && flowNode.data.model === "host" && flowNode.data.ip && (
        <Section label="Configured IP">
          <Row label="eth0">
            <span className="text-[#58a6ff]">{String(flowNode.data.ip)}</span>
          </Row>
        </Section>
      )}
    </div>
  );
}

// ── Interfaces ────────────────────────────────────────────────────────────────

function InterfacesTab({
  flowNode, topoNode, topology,
}: {
  flowNode:  DeviceNode;
  topoNode:  TopologyNode | null;
  topology:  TopologyDocument | null;
}) {
  const ifaces = topoNode?.interfaces ?? [];

  if (!topology || ifaces.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-24 gap-2 text-[#484f58]">
        <Network size={16} />
        <p className="text-[10px] font-mono">
          {topology ? "No interfaces" : "Start simulation to see interfaces"}
        </p>
      </div>
    );
  }

  // Build connected-to map
  const peerMap: Record<string, string> = {};
  for (const link of topology.links) {
    if (link.device_a === flowNode.id) peerMap[link.interface_a] = link.device_b;
    if (link.device_b === flowNode.id) peerMap[link.interface_b] = link.device_a;
  }

  return (
    <table className="w-full text-[10px] font-mono">
      <thead>
        <tr className="border-b border-[#21262d]">
          {["Interface", "IP", "Connected to"].map((h) => (
            <th key={h} className="text-left px-3 py-1.5 text-[#484f58] font-semibold uppercase tracking-wider">
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
            <tr key={iface.name} className="border-b border-[#21262d] hover:bg-[#1c2128] transition-colors">
              <td className="px-3 py-1.5 text-[#8b949e]">{iface.name}</td>
              <td className="px-3 py-1.5 text-[#58a6ff]">{iface.ip || "—"}</td>
              <td className="px-3 py-1.5 text-[#e6edf3]">
                {peerNode ? (peerNode.hostname ?? peerNode.id) : "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ── Terminal ──────────────────────────────────────────────────────────────────

function TerminalTab({
  flowNode, sessionId, isRunning, onTraceUpdate,
}: {
  flowNode:      DeviceNode;
  sessionId:     string | null;
  isRunning:     boolean;
  onTraceUpdate: (trace: TraceEvent[]) => void;
}) {
  if (!isRunning || !sessionId) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-6 text-center text-[#484f58]">
        <Terminal size={18} />
        <p className="text-[10px] font-mono leading-relaxed">
          Click <span className="text-[#3fb950]">Start</span> in the toolbar to bring up the simulation,
          then come back here for the CLI.
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
    <div className="flex flex-col h-full min-h-0">
      {/* Ping shortcut for hosts */}
      {flowNode.data.model === "host" && (
        <div className="p-2 border-b border-[#21262d] shrink-0">
          <PingPanel sessionId={sessionId} onTraceUpdate={onTraceUpdate} />
        </div>
      )}
      <div className="flex-1 min-h-0">
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
      <div className="text-[9px] uppercase tracking-widest text-[#484f58] mb-1.5 font-semibold">
        {label}
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-2 py-0.5">
      <span className="text-[#6e7681] shrink-0">{label}</span>
      <span className="text-[#e6edf3] text-right break-all">{children}</span>
    </div>
  );
}
