"use client";

/**
 * TopologyCanvas — SVG topology with real-time animated PDU flow.
 *
 * Key design decisions:
 * - Packets move along the actual link line using requestAnimationFrame,
 *   not CSS transitions (which snap instead of animate in React SVG).
 * - Clicking a packet opens an inline PDU inspector panel.
 * - Simulation mode can be toggled on/off via props.
 * - Each device glows when it is the active node in the current step.
 */

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { PcIconSVG, SwitchIconSVG } from "./icons";
import { TopologyDocument, TraceEvent } from "@/lib/simulation-api";

// ── Layout ────────────────────────────────────────────────────────────────────

const W = 640;
const H = 300;
const ICON_SIZE = 52;

interface NodePos {
  id: string;
  x: number;
  y: number;
  model: "host" | "switch";
  hostname: string;
  interfaces: string[];
}

interface LinkLine {
  id: string;
  ax: number; ay: number;
  bx: number; by: number;
  fromIface: string;
  toIface: string;
  fromId: string;
  toId: string;
}

function buildLayout(topo: TopologyDocument) {
  const hosts = topo.nodes.filter((n) => n.model === "host");
  const switches = topo.nodes.filter((n) => n.model === "switch");

  const nodeMap = new Map<string, NodePos>();

  // Hosts: spread across top/bottom quadrants.  For 2 hosts: left and right.
  hosts.forEach((h, i) => {
    const x = hosts.length === 1 ? W / 2 : 90 + (i * (W - 180)) / Math.max(hosts.length - 1, 1);
    nodeMap.set(h.id, {
      id: h.id,
      x,
      y: H / 2,
      model: "host",
      hostname: h.hostname ?? h.id,
      interfaces: h.interfaces.map((ifc) => ifc.name),
    });
  });

  // Switches: center, spread vertically if multiple
  switches.forEach((sw, i) => {
    const offset = switches.length > 1 ? (i - (switches.length - 1) / 2) * 110 : 0;
    nodeMap.set(sw.id, {
      id: sw.id,
      x: W / 2 + offset,
      y: H / 2,
      model: "switch",
      hostname: sw.hostname ?? sw.id,
      interfaces: sw.interfaces.map((ifc) => ifc.name),
    });
  });

  // Links
  const links: LinkLine[] = topo.links.map((l) => {
    const a = nodeMap.get(l.device_a)!;
    const b = nodeMap.get(l.device_b)!;
    return {
      id: l.id,
      ax: a.x, ay: a.y,
      bx: b.x, by: b.y,
      fromIface: l.interface_a,
      toIface: l.interface_b,
      fromId: l.device_a,
      toId: l.device_b,
    };
  });

  return { nodeMap, links };
}

// ── Packet types ──────────────────────────────────────────────────────────────

const PDU_COLORS: Record<string, string> = {
  ARPRequestSent:      "#d4a017",
  ARPReplySent:        "#d4a017",
  ICMPEchoRequestSent: "#3fb950",
  ICMPEchoReplySent:   "#26a641",
  FrameDropped:        "#f85149",
  FrameTransmit:       "#58a6ff",
  MACTableLearned:     "#bf96ff",
  ARPCacheUpdated:     "#d4a017",
};

const PDU_SHORT: Record<string, string> = {
  ARPRequestSent:      "ARP?",
  ARPReplySent:        "ARP!",
  ICMPEchoRequestSent: "ICMP",
  ICMPEchoReplySent:   "ICMP",
  FrameDropped:        "DROP",
  FrameTransmit:       "ETH",
  MACTableLearned:     "MAC",
  ARPCacheUpdated:     "ARP",
};

// ── Animation step ────────────────────────────────────────────────────────────

interface AnimStep {
  event: TraceEvent;
  fromX: number; fromY: number;
  toX: number; toY: number;
  color: string;
  label: string;
  highlight: string | undefined;
  isMove: boolean;  // true = animate packet along the link
}

function buildSteps(
  trace: TraceEvent[],
  nodeMap: Map<string, NodePos>,
  links: LinkLine[],
): AnimStep[] {
  // peer lookup: "deviceId:iface" → { x, y, id }
  const peer = new Map<string, { x: number; y: number; id: string }>();
  for (const l of links) {
    peer.set(`${l.fromId}:${l.fromIface}`, { x: l.bx, y: l.by, id: l.toId });
    peer.set(`${l.toId}:${l.toIface}`, { x: l.ax, y: l.ay, id: l.fromId });
  }

  const steps: AnimStep[] = [];
  let curType = "FrameTransmit";
  let curLabel = "ETH";

  for (const evt of trace) {
    const color = PDU_COLORS[evt.type] ?? "#58a6ff";
    const label = PDU_SHORT[evt.type] ?? evt.type.replace("Sent", "").replace("Updated", "");

    if (evt.type.startsWith("ARP") || evt.type.startsWith("ICMP")) {
      curType = evt.type;
      curLabel = PDU_SHORT[evt.type] ?? label;
      const deviceId = evt.device_id ?? evt.src_device_id;
      const node = deviceId ? nodeMap.get(deviceId) : undefined;
      steps.push({
        event: evt,
        fromX: node?.x ?? W / 2,
        fromY: node?.y ?? H / 2,
        toX: node?.x ?? W / 2,
        toY: node?.y ?? H / 2,
        color,
        label: curLabel,
        highlight: deviceId,
        isMove: false,
      });

    } else if (evt.type === "FrameTransmit") {
      const deviceId = evt.device_id ?? "";
      const iface = evt.interface_name ?? "";
      const src = nodeMap.get(deviceId);
      const dst = peer.get(`${deviceId}:${iface}`);

      steps.push({
        event: evt,
        fromX: src?.x ?? W / 2,
        fromY: src?.y ?? H / 2,
        toX: dst?.x ?? W / 2,
        toY: dst?.y ?? H / 2,
        color: PDU_COLORS[curType] ?? "#58a6ff",
        label: curLabel,
        highlight: deviceId,
        isMove: !!(src && dst),
      });

    } else if (evt.type === "FrameDropped") {
      const deviceId = evt.device_id ?? "";
      const node = nodeMap.get(deviceId);
      steps.push({
        event: evt,
        fromX: node?.x ?? W / 2,
        fromY: node?.y ?? H / 2,
        toX: node?.x ?? W / 2,
        toY: node?.y ?? H / 2,
        color: "#f85149",
        label: "DROP",
        highlight: deviceId,
        isMove: false,
      });

    } else {
      const deviceId = evt.switch_id ?? evt.device_id;
      const node = deviceId ? nodeMap.get(deviceId) : undefined;
      steps.push({
        event: evt,
        fromX: node?.x ?? W / 2,
        fromY: node?.y ?? H / 2,
        toX: node?.x ?? W / 2,
        toY: node?.y ?? H / 2,
        color,
        label,
        highlight: deviceId,
        isMove: false,
      });
    }
  }
  return steps;
}

// ── PDU Inspector panel ────────────────────────────────────────────────────────

function PDUInspector({ step, onClose }: { step: AnimStep; onClose: () => void }) {
  const evt = step.event;
  const rows: [string, string][] = [
    ["Event type", evt.type],
    ["Logical time", String(evt.time)],
    ["Sequence", String(evt.seq)],
  ];
  if (evt.device_id)      rows.push(["Device", evt.device_id]);
  if (evt.interface_name) rows.push(["Interface", evt.interface_name]);
  if (evt.operation)      rows.push(["ARP op", evt.operation]);
  if (evt.sender_ip)      rows.push(["Sender IP", evt.sender_ip]);
  if (evt.target_ip)      rows.push(["Target IP", evt.target_ip]);
  if (evt.icmp_type)      rows.push(["ICMP type", evt.icmp_type]);
  if (evt.sequence !== undefined) rows.push(["Seq#", String(evt.sequence)]);
  if (evt.mac_address)    rows.push(["MAC", evt.mac_address]);
  if (evt.ip_address)     rows.push(["IP", evt.ip_address]);
  if (evt.vlan !== undefined) rows.push(["VLAN", String(evt.vlan)]);
  if (evt.reason)         rows.push(["Drop reason", evt.reason]);

  return (
    <div className="absolute right-0 top-0 z-20 w-64 rounded-lg border border-[#30363d] bg-[#161b22] shadow-xl text-xs font-mono">
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 border-b border-[#30363d]"
        style={{ borderLeftColor: step.color, borderLeftWidth: 3 }}
      >
        <span className="font-semibold" style={{ color: step.color }}>
          PDU — {step.label}
        </span>
        <button
          onClick={onClose}
          className="text-[#8b949e] hover:text-[#e6edf3] ml-2"
          aria-label="Close PDU inspector"
        >
          ✕
        </button>
      </div>
      {/* Fields */}
      <div className="p-3 space-y-1.5 max-h-72 overflow-y-auto">
        {rows.map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <span className="text-[#8b949e] shrink-0 w-24">{k}</span>
            <span className="text-[#e6edf3] break-all">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface TopologyCanvasProps {
  topology: TopologyDocument;
  trace: TraceEvent[];
  isPlaying: boolean;
  currentStep: number;
  speed: number;
  onStepChange: (step: number) => void;
  totalSteps: number;
  showSimulation: boolean;
}

export function TopologyCanvas({
  topology,
  trace,
  isPlaying,
  currentStep,
  speed,
  onStepChange,
  showSimulation,
}: TopologyCanvasProps) {
  const { nodeMap, links } = useMemo(() => buildLayout(topology), [topology]);
  const steps = useMemo(
    () => buildSteps(trace, nodeMap, links),
    [trace, nodeMap, links],
  );

  // ── Packet position interpolated via RAF ──────────────────────────────────

  const [pktPos, setPktPos] = useState<{ x: number; y: number } | null>(null);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);

  const animatePacket = useCallback(
    (step: AnimStep, duration: number) => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      startRef.current = null;

      const { fromX, fromY, toX, toY } = step;
      if (!step.isMove || (fromX === toX && fromY === toY)) {
        setPktPos({ x: toX, y: toY });
        return;
      }

      function tick(ts: number) {
        if (startRef.current === null) startRef.current = ts;
        const elapsed = ts - startRef.current;
        const t = Math.min(elapsed / duration, 1);
        // Ease in-out
        const ease = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
        setPktPos({ x: fromX + (toX - fromX) * ease, y: fromY + (toY - fromY) * ease });
        if (t < 1) {
          rafRef.current = requestAnimationFrame(tick);
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    },
    [],
  );

  // ── Auto-advance ──────────────────────────────────────────────────────────

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!isPlaying || !showSimulation) return;
    if (currentStep >= steps.length) return;

    const step = steps[currentStep];
    if (step) animatePacket(step, speed * 0.7);

    timerRef.current = setTimeout(() => {
      onStepChange(currentStep + 1);
    }, speed);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [isPlaying, currentStep, speed, steps, animatePacket, onStepChange, showSimulation]);

  // Animate immediately on manual step too
  useEffect(() => {
    if (!showSimulation) return;
    const step = steps[currentStep];
    if (step) animatePacket(step, speed * 0.7);
  }, [currentStep, steps, animatePacket, speed, showSimulation]);

  // Cleanup RAF on unmount
  useEffect(() => () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); }, []);

  // ── PDU inspector ─────────────────────────────────────────────────────────

  const [inspectedStep, setInspectedStep] = useState<AnimStep | null>(null);

  const currentAnimStep = steps[currentStep];
  const highlightedDevice = currentAnimStep?.highlight;

  const nodes = useMemo(() => Array.from(nodeMap.values()), [nodeMap]);

  return (
    <div className="relative rounded-lg overflow-hidden border border-[#30363d] bg-[#0d1117]">

      {/* Simulation mode badge */}
      {showSimulation && trace.length > 0 && (
        <div className="absolute top-2 left-2 z-10 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#1c2128] border border-[#30363d] text-[10px] font-mono text-[#3fb950]">
          <span className="w-1.5 h-1.5 rounded-full bg-[#3fb950] animate-pulse" />
          SIM {currentStep}/{steps.length}
        </div>
      )}

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ minHeight: 260, maxHeight: 340 }}
        aria-label="Network topology"
      >
        {/* Dot grid */}
        <defs>
          <pattern id="dots" x="0" y="0" width="24" height="24" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="#21262d" />
          </pattern>
        </defs>
        <rect width={W} height={H} fill="url(#dots)" />

        {/* ── Links ── */}
        {links.map((l) => {
          const isActive = showSimulation && (
            (currentAnimStep?.highlight === l.fromId || currentAnimStep?.highlight === l.toId) &&
            currentAnimStep?.isMove
          );
          return (
            <g key={l.id}>
              {/* Shadow line for depth */}
              <line x1={l.ax} y1={l.ay} x2={l.bx} y2={l.by}
                stroke="#0d1117" strokeWidth="5" />
              {/* Main cable */}
              <line x1={l.ax} y1={l.ay} x2={l.bx} y2={l.by}
                stroke={isActive ? "#58a6ff" : "#30363d"}
                strokeWidth="2.5"
                style={{ transition: "stroke 0.2s" }}
              />
              {/* Interface labels */}
              <text
                x={l.ax + (l.bx - l.ax) * 0.18}
                y={l.ay + (l.by - l.ay) * 0.18 - 7}
                fill="#6e7681"
                fontSize="8"
                fontFamily="ui-monospace,monospace"
                textAnchor="middle"
              >
                {l.fromIface}
              </text>
              <text
                x={l.bx + (l.ax - l.bx) * 0.18}
                y={l.by + (l.ay - l.by) * 0.18 - 7}
                fill="#6e7681"
                fontSize="8"
                fontFamily="ui-monospace,monospace"
                textAnchor="middle"
              >
                {l.toIface}
              </text>
            </g>
          );
        })}

        {/* ── Device nodes ── */}
        {nodes.map((node) => {
          const isHighlighted = showSimulation && highlightedDevice === node.id;
          const Icon = node.model === "switch" ? SwitchIconSVG
            : node.model === "host" ? PcIconSVG
            : PcIconSVG;

          return (
            <g key={node.id}>
              {/* Glow ring when active */}
              {isHighlighted && (
                <circle cx={node.x} cy={node.y} r={ICON_SIZE / 2 + 10}
                  fill="none" stroke="#58a6ff" strokeWidth="1.5" opacity="0.35">
                  <animate attributeName="r"
                    values={`${ICON_SIZE / 2 + 8};${ICON_SIZE / 2 + 14};${ICON_SIZE / 2 + 8}`}
                    dur="0.8s" repeatCount="indefinite" />
                  <animate attributeName="opacity"
                    values="0.35;0.15;0.35" dur="0.8s" repeatCount="indefinite" />
                </circle>
              )}
              {/* Device backing circle */}
              <circle cx={node.x} cy={node.y} r={ICON_SIZE / 2 + 4}
                fill="#161b22"
                stroke={isHighlighted ? "#58a6ff" : "#30363d"}
                strokeWidth={isHighlighted ? 2 : 1}
                style={{ transition: "stroke 0.2s, stroke-width 0.2s" }}
              />
              {/* Icon (native SVG, no foreignObject) */}
              <Icon x={node.x} y={node.y} size={ICON_SIZE} active={isHighlighted} />
              {/* Hostname */}
              <text x={node.x} y={node.y + ICON_SIZE / 2 + 16}
                fill="#e6edf3" fontSize="11"
                fontFamily="ui-monospace,monospace"
                fontWeight="bold" textAnchor="middle">
                {node.hostname}
              </text>
              {/* IP address if available */}
              {topology.nodes.find((n) => n.id === node.id)?.interfaces[0]?.ip && (
                <text x={node.x} y={node.y + ICON_SIZE / 2 + 28}
                  fill="#58a6ff" fontSize="9"
                  fontFamily="ui-monospace,monospace"
                  textAnchor="middle">
                  {topology.nodes.find((n) => n.id === node.id)!.interfaces[0].ip}
                </text>
              )}
            </g>
          );
        })}

        {/* ── Animated PDU ── */}
        {showSimulation && pktPos && currentAnimStep && (
          <g
            style={{ cursor: "pointer" }}
            onClick={() => setInspectedStep(
              inspectedStep?.event === currentAnimStep.event ? null : currentAnimStep
            )}
          >
            {/* Outer glow */}
            <circle cx={pktPos.x} cy={pktPos.y} r={14}
              fill={currentAnimStep.color}
              opacity="0.15" />
            {/* Body */}
            <circle cx={pktPos.x} cy={pktPos.y} r={9}
              fill={currentAnimStep.color}
              stroke="#0d1117"
              strokeWidth="1.5" />
            {/* Label inside the packet dot */}
            <text x={pktPos.x} y={pktPos.y + 3}
              fill="#0d1117"
              fontSize="6"
              fontFamily="ui-monospace,monospace"
              fontWeight="bold"
              textAnchor="middle">
              {currentAnimStep.label}
            </text>
            {/* Click hint */}
            <title>Click to inspect PDU</title>
          </g>
        )}

        {/* Drop X marker */}
        {showSimulation && currentAnimStep?.event.type === "FrameDropped" && pktPos && (
          <g>
            <line x1={pktPos.x - 8} y1={pktPos.y - 8}
              x2={pktPos.x + 8} y2={pktPos.y + 8}
              stroke="#f85149" strokeWidth="2.5" strokeLinecap="round" />
            <line x1={pktPos.x + 8} y1={pktPos.y - 8}
              x2={pktPos.x - 8} y2={pktPos.y + 8}
              stroke="#f85149" strokeWidth="2.5" strokeLinecap="round" />
          </g>
        )}
      </svg>

      {/* PDU Inspector overlay */}
      {inspectedStep && (
        <PDUInspector
          step={inspectedStep}
          onClose={() => setInspectedStep(null)}
        />
      )}

      {/* Event info strip at bottom */}
      {showSimulation && currentAnimStep && (
        <div className="px-3 py-1.5 border-t border-[#30363d] flex items-center gap-2 text-[11px] font-mono bg-[#161b22]">
          <span className="text-[#484f58]">
            t={String(currentAnimStep.event.time).padStart(3, "0")}
          </span>
          <span style={{ color: currentAnimStep.color }} className="font-semibold">
            {currentAnimStep.event.type}
          </span>
          {currentAnimStep.event.device_id && (
            <span className="text-[#8b949e]">{currentAnimStep.event.device_id}</span>
          )}
          {currentAnimStep.event.reason && (
            <span className="text-[#f85149]">{currentAnimStep.event.reason}</span>
          )}
          {!inspectedStep && pktPos && (
            <span className="ml-auto text-[#484f58]">click packet to inspect</span>
          )}
        </div>
      )}
    </div>
  );
}
