"use client";

/**
 * RightPanel — CML-style right panel.
 *
 * Three tabs exactly matching CML 2.x:
 *   Properties  — node details, model, status
 *   Interfaces  — interface list with IP/MAC/state
 *   Terminal    — xterm.js CLI attached to the selected node
 */

import { motion, AnimatePresence } from "framer-motion";
import { Settings2, Network, Terminal } from "lucide-react";
import type { TopologyDocument, TopologyNode } from "@/lib/simulation-api";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";
import { DeviceTerminal } from "@/components/labs/DeviceTerminal";
import { PingPanel }     from "@/components/labs/PingPanel";
import type { TraceEvent } from "@/lib/simulation-api";

type RightTab = "properties" | "interfaces" | "terminal";

interface RightPanelProps {
  node: TopologyNode | null;
  tab: RightTab;
  onTabChange: (t: RightTab) => void;
  sessionId: string | null;
  simState: SimState;
  topology: TopologyDocument;
  onTraceUpdate: (trace: TraceEvent[]) => void;
}

export function RightPanel({
  node, tab, onTabChange, sessionId, simState, topology, onTraceUpdate,
}: RightPanelProps) {
  const isRunning = simState === "running";

  const tabs: { id: RightTab; icon: React.ElementType; label: string }[] = [
    { id: "properties", icon: Settings2, label: "Properties" },
    { id: "interfaces", icon: Network,   label: "Interfaces"  },
    { id: "terminal",   icon: Terminal,  label: "Terminal"    },
  ];

  return (
    <div
      className="flex flex-col border-l border-[#21262d] shrink-0"
      style={{ width: 300, background: "#161b22" }}
    >
      {/* Tab bar */}
      <div className="flex border-b border-[#21262d]">
        {tabs.map(({ id, icon: Icon, label }) => (
          <button
            key={id}
            onClick={() => onTabChange(id)}
            className="flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px] font-mono transition-colors"
            style={{
              color: tab === id ? "#58a6ff" : "#484f58",
              borderBottom: tab === id ? "2px solid #58a6ff" : "2px solid transparent",
            }}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {/* Panel content */}
      <div className="flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, x: 6 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -6 }}
            transition={{ duration: 0.15 }}
            className="h-full"
          >
            {tab === "properties" && (
              <PropertiesTab node={node} simState={simState} />
            )}
            {tab === "interfaces" && (
              <InterfacesTab node={node} topology={topology} />
            )}
            {tab === "terminal" && (
              <TerminalTab
                node={node}
                sessionId={sessionId}
                isRunning={isRunning}
                onTraceUpdate={onTraceUpdate}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

// ── Properties tab ────────────────────────────────────────────────────────────

function PropertiesTab({ node, simState }: { node: TopologyNode | null; simState: SimState }) {
  const isRunning = simState === "running";

  if (!node) {
    return (
      <div className="flex flex-col items-center justify-center h-32 gap-2 text-[#484f58]">
        <Settings2 size={20} />
        <p className="text-xs font-mono">Select a node</p>
      </div>
    );
  }

  const ifaces = node.interfaces ?? [];

  return (
    <div className="p-3 space-y-4 text-xs font-mono">
      {/* Node status */}
      <div>
        <div className="text-[#484f58] uppercase tracking-wider mb-2 text-[10px]">
          State
        </div>
        <div className="flex items-center gap-2">
          <span
            className="w-2 h-2 rounded-full"
            style={{ background: isRunning ? "#3fb950" : "#484f58" }}
          />
          <span className="text-[#e6edf3]">
            {isRunning ? "ACTIVE" : "STOPPED"}
          </span>
        </div>
      </div>

      {/* Node details */}
      <div>
        <div className="text-[#484f58] uppercase tracking-wider mb-2 text-[10px]">
          Node
        </div>
        <table className="w-full">
          <tbody className="space-y-1">
            {[
              ["Label",   node.hostname ?? node.id],
              ["ID",      node.id],
              ["Type",    node.model],
              ["Ports",   String(ifaces.length)],
            ].map(([k, v]) => (
              <tr key={k}>
                <td className="text-[#484f58] pr-3 py-0.5">{k}</td>
                <td className="text-[#e6edf3]">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* IP summary */}
      {ifaces.some((i) => i.ip) && (
        <div>
          <div className="text-[#484f58] uppercase tracking-wider mb-2 text-[10px]">
            Addresses
          </div>
          {ifaces.filter((i) => i.ip).map((iface) => (
            <div key={iface.name} className="flex justify-between py-0.5">
              <span className="text-[#8b949e]">{iface.name}</span>
              <span className="text-[#58a6ff]">{iface.ip}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Interfaces tab ─────────────────────────────────────────────────────────────

function InterfacesTab({
  node, topology,
}: {
  node: TopologyNode | null;
  topology: TopologyDocument;
}) {
  if (!node) {
    return (
      <div className="flex flex-col items-center justify-center h-32 gap-2 text-[#484f58]">
        <Network size={20} />
        <p className="text-xs font-mono">Select a node</p>
      </div>
    );
  }

  const ifaces = node.interfaces ?? [];
  // Find connected links for each interface
  const linkMap: Record<string, string> = {};
  for (const link of topology.links) {
    if (link.device_a === node.id) linkMap[link.interface_a] = link.device_b;
    if (link.device_b === node.id) linkMap[link.interface_b] = link.device_a;
  }

  return (
    <div className="p-2">
      <table className="w-full text-[11px] font-mono">
        <thead>
          <tr className="text-[#484f58] text-[10px]">
            <th className="text-left pb-1.5 pr-2">Interface</th>
            <th className="text-left pb-1.5 pr-2">IP</th>
            <th className="text-left pb-1.5">Connected to</th>
          </tr>
        </thead>
        <tbody>
          {ifaces.length === 0 ? (
            <tr>
              <td colSpan={3} className="text-[#484f58] py-2">
                No interfaces
              </td>
            </tr>
          ) : (
            ifaces.map((iface) => {
              const peer = linkMap[iface.name];
              const peerNode = topology.nodes.find((n) => n.id === peer);
              return (
                <tr
                  key={iface.name}
                  className="border-t border-[#21262d] hover:bg-[#1c2128] transition-colors"
                >
                  <td className="py-1.5 pr-2 text-[#8b949e]">{iface.name}</td>
                  <td className="py-1.5 pr-2 text-[#58a6ff]">{iface.ip || "—"}</td>
                  <td className="py-1.5 text-[#e6edf3]">
                    {peerNode ? (peerNode.hostname ?? peerNode.id) : "—"}
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Terminal tab ───────────────────────────────────────────────────────────────

function TerminalTab({
  node, sessionId, isRunning, onTraceUpdate,
}: {
  node: TopologyNode | null;
  sessionId: string | null;
  isRunning: boolean;
  onTraceUpdate: (trace: TraceEvent[]) => void;
}) {
  if (!node) {
    return (
      <div className="flex flex-col items-center justify-center h-32 gap-2 text-[#484f58]">
        <Terminal size={20} />
        <p className="text-xs font-mono">Select a node</p>
      </div>
    );
  }

  if (!isRunning || !sessionId) {
    return (
      <div className="flex flex-col items-center justify-center h-32 gap-2 text-[#484f58] p-4 text-center">
        <Terminal size={20} />
        <p className="text-xs font-mono">Start the simulation to open a terminal</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Ping shortcut for hosts */}
      {node.model === "host" && (
        <div className="p-2 border-b border-[#21262d]">
          <PingPanel
            sessionId={sessionId}
            onTraceUpdate={onTraceUpdate}
          />
        </div>
      )}
      {/* Terminal */}
      <div className="flex-1 min-h-0">
        <DeviceTerminal
          key={`${node.id}-${sessionId}`}
          sessionId={sessionId}
          device={node}
          onClose={() => {}}
        />
      </div>
    </div>
  );
}
