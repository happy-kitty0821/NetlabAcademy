"use client";

/**
 * BottomPanel — CML-style tabbed pane under the canvas.
 *
 *  - One console tab per device the user opened (double-click a device or
 *    use "Console" in the inspector). Consoles stay connected while hidden
 *    so their scrollback and history survive tab switches.
 *  - Lab log: every device's syslog (link up/down, config changes), live.
 *  - Packet trace: the simulator's event trace from pings.
 *
 * Collapsible and resizable from its top edge.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ChevronDown, ChevronUp, ScrollText, Terminal, X } from "lucide-react";
import { DeviceTerminal } from "@/components/labs/DeviceTerminal";
import { PingPanel } from "@/components/labs/PingPanel";
import type { DeviceNode } from "@/lib/deviceTypes";
import type { SyslogEntry, TopologyNode, TraceEvent } from "@/lib/simulation-api";
import type { SimState } from "@/app/(dashboard)/labs/workspace/page";

export type BottomTab = "log" | "trace" | `console:${string}`;

interface BottomPanelProps {
  nodes:          DeviceNode[];
  consoles:       string[];               // device ids with an open console
  tab:            BottomTab;
  open:           boolean;
  onOpenChange:   (open: boolean) => void;
  onTabChange:    (tab: BottomTab) => void;
  onCloseConsole: (deviceId: string) => void;
  sessionId:      string | null;
  simState:       SimState;
  syslog:         SyslogEntry[];
  trace:          TraceEvent[];
  onTraceUpdate:  (t: TraceEvent[]) => void;
}

const DEFAULT_HEIGHT = 260;
const MIN_HEIGHT = 120;
const MAX_HEIGHT = 600;

export function BottomPanel({
  nodes, consoles, tab, open, onOpenChange, onTabChange, onCloseConsole,
  sessionId, simState, syslog, trace, onTraceUpdate,
}: BottomPanelProps) {
  const [height, setHeight] = useState(DEFAULT_HEIGHT);
  const dragging = useRef(false);
  const startY = useRef(0);
  const startH = useRef(0);
  const running = simState === "running" && !!sessionId;
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    dragging.current = true;
    startY.current = e.clientY;
    startH.current = height;
    e.preventDefault();
  }, [height]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      setHeight(Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, startH.current + (startY.current - e.clientY))));
    };
    const onUp = () => { dragging.current = false; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);

  const select = (t: BottomTab) => { onTabChange(t); onOpenChange(true); };

  return (
    <div className="flex shrink-0 flex-col border-t border-[#d0d7de] bg-white">
      {open && (
        <div onMouseDown={onDragStart} title="Drag to resize"
          className="h-1 cursor-row-resize border-t-2 border-transparent hover:border-[#0969da]" />
      )}

      {/* Tab strip */}
      <div className="flex h-9 select-none items-center gap-1 overflow-x-auto bg-[#f6f8fa] px-2"
        style={{ borderBottom: open ? "1px solid #d0d7de" : "none" }}>
        {consoles.map((id) => {
          const name = String(byId.get(id)?.data.hostname ?? id);
          const key: BottomTab = `console:${id}`;
          const active = open && tab === key;
          return (
            <div key={id} className={"flex shrink-0 items-center rounded " + (active ? "bg-white shadow-[inset_0_0_0_1px_#d0d7de]" : "")}>
              <button onClick={() => select(key)}
                className={"flex items-center gap-1.5 py-1 pl-2.5 pr-1 font-mono text-xs " + (active ? "font-semibold text-[#0969da]" : "text-[#656d76] hover:text-[#1f2328]")}>
                <Terminal size={12} aria-hidden="true" /> {name}
              </button>
              <button onClick={() => onCloseConsole(id)} aria-label={`Close ${name} console`}
                className="mr-1 rounded p-0.5 text-[#9198a1] hover:bg-[#eaeef2] hover:text-[#1f2328]">
                <X size={11} />
              </button>
            </div>
          );
        })}
        {consoles.length > 0 && <span className="mx-1 h-4 w-px shrink-0 bg-[#d0d7de]" />}
        <TabButton active={open && tab === "log"} onClick={() => select("log")} icon={ScrollText}
          label="Lab log" count={syslog.length} />
        <TabButton active={open && tab === "trace"} onClick={() => select("trace")} icon={Activity}
          label="Packet trace" count={trace.length} />
        <div className="flex-1" />
        <button onClick={() => onOpenChange(!open)} title={open ? "Collapse" : "Expand"}
          className="flex shrink-0 items-center gap-1 rounded px-2 py-1 text-xs text-[#656d76] hover:bg-[#eaeef2]">
          {open ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
          {open ? "Hide" : "Show"}
        </button>
      </div>

      {/* Body — consoles stay mounted (hidden) so they keep their state */}
      <div style={{ height: open ? height : 0 }} className="relative overflow-hidden">
        {consoles.map((id) => {
          const node = byId.get(id);
          const visible = open && tab === `console:${id}`;
          return (
            <div key={id} className="absolute inset-0 flex flex-col" style={{ display: visible ? "flex" : "none" }}>
              {!running || !node ? (
                <Empty icon={Terminal}>
                  The lab is not running. Click <strong className="text-[#1a7f37]">Start</strong> to connect
                  to {String(node?.data.hostname ?? id)}.
                </Empty>
              ) : (
                <ConsolePane node={node} sessionId={sessionId!} onTraceUpdate={onTraceUpdate} />
              )}
            </div>
          );
        })}
        {open && tab === "log" && <LabLogPane entries={syslog} running={running} />}
        {open && tab === "trace" && <TracePane trace={trace} />}
        {open && tab.startsWith("console:") && !consoles.includes(tab.slice(8)) && (
          <Empty icon={Terminal}>Double-click a device to open its console.</Empty>
        )}
      </div>
    </div>
  );
}

function TabButton({ active, onClick, icon: Icon, label, count }: {
  active: boolean; onClick: () => void; icon: React.ElementType; label: string; count: number;
}) {
  return (
    <button onClick={onClick}
      className={"flex shrink-0 items-center gap-1.5 rounded px-2.5 py-1 text-xs " +
        (active ? "bg-white font-semibold text-[#0969da] shadow-[inset_0_0_0_1px_#d0d7de]" : "text-[#656d76] hover:text-[#1f2328]")}>
      <Icon size={12} aria-hidden="true" /> {label}
      {count > 0 && <span className="font-mono text-[10px] text-[#9198a1]">{count}</span>}
    </button>
  );
}

function Empty({ icon: Icon, children }: { icon: React.ElementType; children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-xs text-[#9198a1]">
      <Icon size={18} aria-hidden="true" />
      <p>{children}</p>
    </div>
  );
}

function ConsolePane({ node, sessionId, onTraceUpdate }: {
  node: DeviceNode; sessionId: string; onTraceUpdate: (t: TraceEvent[]) => void;
}) {
  const topoNode: TopologyNode = {
    id: node.id,
    model: node.data.model as TopologyNode["model"],
    hostname: String(node.data.hostname ?? node.id),
    interfaces: [],
  };
  return (
    <>
      {node.data.model === "host" && (
        <div className="border-b border-[#d0d7de] bg-[#f6f8fa] px-3 py-1.5">
          <PingPanel sessionId={sessionId} onTraceUpdate={onTraceUpdate} />
        </div>
      )}
      <div className="min-h-0 flex-1">
        <DeviceTerminal key={`${node.id}-${sessionId}`} sessionId={sessionId} device={topoNode} onClose={() => {}} />
      </div>
    </>
  );
}

/** Link changes read by meaning (up green, down red); others by severity. */
function messageColor(e: SyslogEntry): string {
  if (/changed state to up$/.test(e.message)) return "#1a7f37";
  if (/changed state to (administratively )?down$/.test(e.message)) return "#d1242f";
  return e.severity <= 3 ? "#d1242f" : e.severity === 4 ? "#9a6700" : "#656d76";
}

function LabLogPane({ entries, running }: { entries: SyslogEntry[]; running: boolean }) {
  const [device, setDevice] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const devices = useMemo(() => Array.from(new Set(entries.map((e) => e.hostname))).sort(), [entries]);
  const shown = device ? entries.filter((e) => e.hostname === device) : entries;
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [shown.length]);

  if (entries.length === 0) {
    return (
      <Empty icon={ScrollText}>
        {running ? "No messages yet. Connect or shut down an interface to see link events."
                 : "Start the lab to see device logs (link up/down, configuration changes)."}
      </Empty>
    );
  }
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-[#eaeef2] px-3 py-1 text-xs text-[#656d76]">
        <label htmlFor="lab-log-device">Device</label>
        <select id="lab-log-device" value={device} onChange={(e) => setDevice(e.target.value)}
          className="rounded border border-[#d0d7de] bg-white px-1.5 py-0.5 text-xs text-[#1f2328]">
          <option value="">All</option>
          {devices.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <span className="ml-auto">{shown.length} messages</span>
      </div>
      <div className="flex-1 overflow-y-auto font-mono text-[11.5px] leading-5">
        {shown.map((e) => (
          <div key={e.seq} className="flex gap-3 border-b border-[#f6f8fa] px-3 hover:bg-[#f6f8fa]">
            <span className="w-14 shrink-0 text-right text-[#9198a1]">{e.tick}</span>
            <span className="w-20 shrink-0 truncate font-semibold text-[#1f2328]">{e.hostname}</span>
            <span style={{ color: messageColor(e) }}>{e.text}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}

function TracePane({ trace }: { trace: TraceEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [trace.length]);
  if (trace.length === 0) return <Empty icon={Activity}>Run a ping from a PC console to see its packet trace.</Empty>;
  return (
    <div className="h-full overflow-y-auto font-mono text-[11.5px]">
      <table className="w-full border-collapse">
        <thead className="sticky top-0 bg-[#f6f8fa] text-left text-[10px] uppercase tracking-wide text-[#656d76]">
          <tr>{["Tick", "Event", "Device", "Detail"].map((h) => <th key={h} className="border-b border-[#d0d7de] px-3 py-1 font-semibold">{h}</th>)}</tr>
        </thead>
        <tbody>
          {trace.map((ev, i) => (
            <tr key={i} className="border-b border-[#f6f8fa] hover:bg-[#f6f8fa]">
              <td className="w-14 px-3 py-0.5 text-[#9198a1]">{ev.time}</td>
              <td className="whitespace-nowrap px-3 py-0.5 font-semibold text-[#0969da]">{ev.type}</td>
              <td className="px-3 py-0.5 text-[#1f2328]">{ev.device_id ?? ev.switch_id ?? ev.src_device_id ?? ""}</td>
              <td className="px-3 py-0.5 text-[#656d76]">
                {[ev.interface_name, ev.ip_address ?? ev.target_ip ?? ev.sender_ip, ev.mac_address, ev.reason].filter(Boolean).join("  ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div ref={endRef} />
    </div>
  );
}
