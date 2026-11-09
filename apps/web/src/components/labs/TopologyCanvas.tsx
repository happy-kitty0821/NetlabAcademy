"use client";

/**
 * TopologyCanvas — SVG-based animated network topology.
 *
 * Renders devices as positioned nodes with GNS3-style icons and draws
 * links between them.  When a trace is replayed, packets animate as
 * coloured dots moving along the links between devices.
 *
 * Layout: devices are placed at fixed coordinates for this PoC.  A
 * drag-and-drop layout engine will replace this in the topology-editor
 * spec.
 */

import { useEffect, useMemo, useRef } from "react";
import { DeviceIcon } from "./icons";
import { TopologyDocument, TraceEvent } from "@/lib/simulation-api";

// ── Layout types ──────────────────────────────────────────────────────────────

interface NodePosition {
  id: string;
  x: number;
  y: number;
  model: "host" | "switch";
  hostname: string;
}

interface LinkPath {
  id: string;
  from: NodePosition;
  to: NodePosition;
  fromInterface: string;
  toInterface: string;
}

interface ActivePacket {
  id: number;
  x: number;
  y: number;
  color: string;
  label: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const NODE_Y = 130;
const CANVAS_WIDTH = 560;
const CANVAS_HEIGHT = 260;
const PACKET_RADIUS = 6;

// Packet colors by event type
const PACKET_COLORS: Record<string, string> = {
  ARPRequestSent:      "#d29922",
  ARPReplySent:        "#d29922",
  ARPCacheUpdated:      "#d4a72c",
  MACTableLearned:      "#bf96ff",
  ICMPEchoRequestSent:  "#3fb950",
  ICMPEchoReplySent:    "#3fb950",
  FrameTransmit:       "#58a6ff",
  FrameArrival:        "#8b949e",
  FrameDropped:        "#f85149",
};

const PACKET_LABELS: Record<string, string> = {
  ARPRequestSent:      "ARP Request",
  ARPReplySent:        "ARP Reply",
  ICMPEchoRequestSent: "ICMP Echo Req",
  ICMPEchoReplySent:   "ICMP Echo Rep",
  FrameDropped:        "Dropped",
};

// ── Build layout from topology ────────────────────────────────────────────────

function buildLayout(topology: TopologyDocument): {
  nodes: NodePosition[];
  links: LinkPath[];
  nodeMap: Map<string, NodePosition>;
} {
  const hosts = topology.nodes.filter((n) => n.model === "host");
  const switches = topology.nodes.filter((n) => n.model === "switch");

  const nodes: NodePosition[] = [];
  // Place hosts: first on left, second on right
  hosts.forEach((host, i) => {
    const x = i === 0 ? 60 : CANVAS_WIDTH - 60;
    nodes.push({
      id: host.id,
      x,
      y: NODE_Y,
      model: "host" as const,
      hostname: host.hostname || host.id,
    });
  });
  // Place switches in the center
  switches.forEach((sw, i) => {
    const offset = switches.length > 1 ? (i - (switches.length - 1) / 2) * 120 : 0;
    nodes.push({
      id: sw.id,
      x: CANVAS_WIDTH / 2 + offset,
      y: NODE_Y,
      model: "switch" as const,
      hostname: sw.hostname || sw.id,
    });
  });

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  // Build link paths
  const links: LinkPath[] = topology.links.map((link) => {
    const from = nodeMap.get(link.device_a)!;
    const to = nodeMap.get(link.device_b)!;
    return {
      id: link.id,
      from,
      to,
      fromInterface: link.interface_a,
      toInterface: link.interface_b,
    };
  });

  return { nodes, links, nodeMap };
}

// ── Parse trace into animation steps ──────────────────────────────────────────

interface AnimStep {
  eventIndex: number;
  event: TraceEvent;
  // Packet animation: source and destination coordinates
  fromX?: number;
  fromY?: number;
  toX?: number;
  toY?: number;
  color: string;
  label: string;
  // Device to highlight
  highlightDevice?: string;
  // Whether this step moves a packet (vs just highlighting)
  isPacketMove: boolean;
}

function parseTraceToSteps(
  trace: TraceEvent[],
  nodeMap: Map<string, NodePosition>,
  links: LinkPath[]
): AnimStep[] {
  const steps: AnimStep[] = [];

  // Build a lookup: (deviceId, interfaceName) → peer position
  const peerLookup = new Map<string, { x: number; y: number; deviceId: string } >();
  for (const link of links) {
    peerLookup.set(`${link.from.id}:${link.fromInterface}`, {
      x: link.to.x,
      y: link.to.y,
      deviceId: link.to.id,
    });
    peerLookup.set(`${link.to.id}:${link.toInterface}`, {
      x: link.from.x,
      y: link.from.y,
      deviceId: link.from.id,
    });
  }

  // Track the current packet type (set by ARP*/ICMP* events, used by FrameTransmit)
  let currentPacketType = "FrameTransmit";
  let currentLabel = "Frame";

  for (let i = 0; i < trace.length; i++) {
    const evt = trace[i];
    const color = PACKET_COLORS[evt.type] || "#58a6ff";
    const label = PACKET_LABELS[evt.type] || evt.type;

    if (evt.type.startsWith("ARP") || evt.type.startsWith("ICMP")) {
      // Origin event — sets the packet type for subsequent FrameTransmit
      currentPacketType = evt.type;
      currentLabel = label;
      steps.push({
        eventIndex: i,
        event: evt,
        color,
        label,
        highlightDevice: evt.device_id || evt.src_device_id,
        isPacketMove: false,
      });
    } else if (evt.type === "FrameTransmit") {
      // Packet leaving a device — animate from source to peer
      const deviceId = evt.device_id!;
      const iface = evt.interface_name || "";
      const sourceNode = nodeMap.get(deviceId);
      const peer = peerLookup.get(`${deviceId}:${iface}`);
      if (sourceNode && peer) {
        steps.push({
          eventIndex: i,
          event: evt,
          fromX: sourceNode.x,
          fromY: sourceNode.y,
          toX: peer.x,
          toY: peer.y,
          color: PACKET_COLORS[currentPacketType] || color,
          label: currentLabel,
          highlightDevice: deviceId,
          isPacketMove: true,
        });
      } else {
        steps.push({
          eventIndex: i,
          event: evt,
          color,
          label,
          highlightDevice: deviceId,
          isPacketMove: false,
        });
      }
    } else if (evt.type === "FrameArrival") {
      // Packet arriving at a device
      const deviceId = evt.device_id!;
      const node = nodeMap.get(deviceId);
      steps.push({
        eventIndex: i,
        event: evt,
        toX: node?.x,
        toY: node?.y,
        color: PACKET_COLORS[currentPacketType] || color,
        label: currentLabel,
        highlightDevice: deviceId,
        isPacketMove: false,
      });
    } else if (evt.type === "FrameDropped") {
      steps.push({
        eventIndex: i,
        event: evt,
        color: "#f85149",
        label: "Dropped",
        highlightDevice: evt.device_id,
        isPacketMove: false,
      });
    } else {
      // MACTableLearned, ARPCacheUpdated, etc.
      steps.push({
        eventIndex: i,
        event: evt,
        color,
        label,
        highlightDevice: evt.switch_id || evt.device_id,
        isPacketMove: false,
      });
    }
  }

  return steps;
}

// ── Component ─────────────────────────────────────────────────────────────────

interface TopologyCanvasProps {
  topology: TopologyDocument;
  trace: TraceEvent[];
  isPlaying: boolean;
  currentStep: number;
  speed: number; // ms per step
  onStepChange: (step: number) => void;
  totalSteps: number;
}

export function TopologyCanvas({
  topology,
  trace,
  isPlaying,
  currentStep,
  speed,
  onStepChange,
}: TopologyCanvasProps) {
  const { nodes, links, nodeMap } = useMemo(() => buildLayout(topology), [topology]);
  const steps = useMemo(() => parseTraceToSteps(trace, nodeMap, links), [trace, nodeMap, links]);

  // Auto-advance when playing
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isPlaying && currentStep < steps.length) {
      timerRef.current = setTimeout(() => {
        onStepChange(currentStep + 1);
      }, speed);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [isPlaying, currentStep, speed, steps.length, onStepChange]);

  // Current active packet (if the current step is a packet move)
  const currentAnimStep = steps[currentStep];
  const activePacket: ActivePacket | null = useMemo(() => {
    if (!currentAnimStep || !currentAnimStep.isPacketMove) return null;
    return {
      id: currentStep,
      x: currentAnimStep.toX || 0,
      y: currentAnimStep.toY || 0,
      color: currentAnimStep.color,
      label: currentAnimStep.label,
    };
  }, [currentAnimStep, currentStep]);

  const highlightedDevice = currentAnimStep?.highlightDevice;

  return (
    <div className="relative w-full">
      <svg
        viewBox={`0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}`}
        className="w-full h-auto"
        style={{ maxHeight: "320px" }}
        role="img"
        aria-label="Network topology with packet animation"
      >
        {/* Background grid */}
        <defs>
          <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="var(--canvas-grid)" strokeWidth="0.5" opacity="0.3" />
          </pattern>
        </defs>
        <rect width={CANVAS_WIDTH} height={CANVAS_HEIGHT} fill="url(#grid)" />

        {/* Links */}
        {links.map((link) => (
          <g key={link.id}>
            <line
              x1={link.from.x}
              y1={link.from.y}
              x2={link.to.x}
              y2={link.to.y}
              stroke="var(--canvas-link)"
              strokeWidth="2"
              strokeDasharray="4 3"
            />
            {/* Interface labels at link endpoints */}
            <text
              x={link.from.x + (link.to.x - link.from.x) * 0.15}
              y={link.from.y - 8}
              fill="var(--text-muted)"
              fontSize="8"
              fontFamily="monospace"
              textAnchor="middle"
            >
              {link.fromInterface}
            </text>
            <text
              x={link.to.x + (link.from.x - link.to.x) * 0.15}
              y={link.to.y - 8}
              fill="var(--text-muted)"
              fontSize="8"
              fontFamily="monospace"
              textAnchor="middle"
            >
              {link.toInterface}
            </text>
          </g>
        ))}

        {/* Nodes */}
        {nodes.map((node) => (
          <g
            key={node.id}
            transform={`translate(${node.x - 24}, ${node.y - 24})`}
            style={{
              filter: highlightedDevice === node.id
                ? "drop-shadow(0 0 6px var(--accent-primary))"
                : "none",
              transition: "filter 0.2s ease",
            }}
          >
            {/* Icon background circle */}
            <circle
              cx="24"
              cy="24"
              r="26"
              fill="var(--surface-raised)"
              stroke={highlightedDevice === node.id ? "var(--accent-primary)" : "var(--surface-border)"}
              strokeWidth={highlightedDevice === node.id ? "2" : "1"}
              style={{ transition: "stroke 0.2s ease, stroke-width 0.2s ease" }}
            />
            {/* Icon */}
            <foreignObject x="0" y="0" width="48" height="48">
              <DeviceIcon model={node.model} size={48} />
            </foreignObject>
            {/* Hostname label below */}
            <text
              x="24"
              y="60"
              fill="var(--text-primary)"
              fontSize="10"
              fontFamily="var(--font-sans)"
              fontWeight="600"
              textAnchor="middle"
            >
              {node.hostname}
            </text>
            {/* Device ID (smaller, muted) */}
            <text
              x="24"
              y="72"
              fill="var(--text-muted)"
              fontSize="8"
              fontFamily="monospace"
              textAnchor="middle"
            >
              {node.id}
            </text>
          </g>
        ))}

        {/* Active packet animation */}
        {activePacket && (
          <g key={activePacket.id}>
            {/* Packet dot */}
            <circle
              cx={activePacket.x}
              cy={activePacket.y}
              r={PACKET_RADIUS}
              fill={activePacket.color}
              style={{
                transition: `cx ${speed * 0.8}ms ease-in-out, cy ${speed * 0.8}ms ease-in-out`,
              }}
            >
              <animate attributeName="r" values="6;8;6" dur="0.5s" repeatCount="indefinite" />
            </circle>
            {/* Packet glow */}
            <circle
              cx={activePacket.x}
              cy={activePacket.y}
              r={PACKET_RADIUS + 4}
              fill="none"
              stroke={activePacket.color}
              strokeWidth="1"
              opacity="0.3"
              style={{
                transition: `cx ${speed * 0.8}ms ease-in-out, cy ${speed * 0.8}ms ease-in-out`,
              }}
            />
            {/* Packet label */}
            <text
              x={activePacket.x}
              y={activePacket.y - 14}
              fill={activePacket.color}
              fontSize="8"
              fontFamily="monospace"
              textAnchor="middle"
              style={{
                transition: `x ${speed * 0.8}ms ease-in-out, y ${speed * 0.8}ms ease-in-out`,
              }}
            >
              {activePacket.label}
            </text>
          </g>
        )}

        {/* Drop indicator */}
        {currentAnimStep?.event.type === "FrameDropped" && (
          <g>
            {currentAnimStep.highlightDevice && nodeMap.get(currentAnimStep.highlightDevice) && (
              <text
                x={nodeMap.get(currentAnimStep.highlightDevice)!.x}
                y={nodeMap.get(currentAnimStep.highlightDevice)!.y - 34}
                fill="#f85149"
                fontSize="10"
                fontFamily="monospace"
                textAnchor="middle"
              >
                X DROP
              </text>
            )}
          </g>
        )}
      </svg>

      {/* Current event info bar */}
      {currentAnimStep && (
        <div className="mt-2 px-3 py-1.5 rounded-md bg-[var(--surface-overlay)] border border-[var(--surface-border)] text-xs font-mono">
          <span className="text-[var(--text-muted)]">
            [{String(currentAnimStep.event.time).padStart(3, " ")}]{" "}
          </span>
          <span style={{ color: currentAnimStep.color }}>
            {currentAnimStep.event.type}
          </span>
          {currentAnimStep.event.device_id && (
            <span className="text-[var(--text-secondary)] ml-2">
              {currentAnimStep.event.device_id}
            </span>
          )}
          {currentAnimStep.event.reason && (
            <span className="text-[var(--status-error)] ml-2">
              {currentAnimStep.event.reason}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
