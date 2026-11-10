"use client";

/**
 * /admin/devices — interactive device catalog management.
 *
 * Shows each device type with expandable details:
 * - Port types supported (FastEthernet, GigabitEthernet, etc.)
 * - Interface templates with editable speed/duplex/VLAN
 * - STP path cost per port type
 * - Capability matrix (L2 switching, L3 routing, trunk, PortFast)
 *
 * Click a device to expand its interface configuration.
 */

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import {
  DEFAULT_DEVICE_CATALOG,
  type DeviceCatalogEntry,
} from "@/lib/deviceTypes";
import {
  ChevronRight,
  CheckCircle2,
  Clock,
  Monitor,
  Network,
  Server,
  Laptop,
  Zap,
} from "lucide-react";

// ── Port type capabilities ────────────────────────────────────────────────────

interface PortTypeSpec {
  name: string;
  ciscoName: string;
  short: string;
  speed: string;
  stpCost: number;
  supportsL2: boolean;
  supportsL3: boolean;
  supportsTrunk: boolean;
}

const PORT_TYPES: PortTypeSpec[] = [
  {
    name: "fastethernet",
    ciscoName: "FastEthernet",
    short: "Fa",
    speed: "100 Mbps",
    stpCost: 19,
    supportsL2: true,
    supportsL3: true,
    supportsTrunk: true,
  },
  {
    name: "gigabitethernet",
    ciscoName: "GigabitEthernet",
    short: "Gi",
    speed: "1 Gbps",
    stpCost: 4,
    supportsL2: true,
    supportsL3: true,
    supportsTrunk: true,
  },
  {
    name: "tengigabitethernet",
    ciscoName: "TenGigabitEthernet",
    short: "Te",
    speed: "10 Gbps",
    stpCost: 2,
    supportsL2: true,
    supportsL3: true,
    supportsTrunk: true,
  },
  {
    name: "ethernet",
    ciscoName: "Ethernet",
    short: "Eth",
    speed: "10 Mbps",
    stpCost: 100,
    supportsL2: true,
    supportsL3: false,
    supportsTrunk: false,
  },
];

// ── Interface template for each device type ────────────────────────────────────

const DEVICE_INTERFACE_TEMPLATES: Record<
  string,
  { count: number; portType: string; defaultName: string }
> = {
  "cisco-pc":     { count: 1, portType: "gigabitethernet", defaultName: "eth0" },
  "cisco-laptop": { count: 1, portType: "gigabitethernet", defaultName: "eth0" },
  "cisco-server": { count: 1, portType: "gigabitethernet", defaultName: "eth0" },
  "cisco-2960":   { count: 24, portType: "fastethernet",    defaultName: "Fa0/{n}" },
  "cisco-2911":   { count: 3, portType: "gigabitethernet",  defaultName: "Gi0/{n}" },
};

// ── Capability matrix ──────────────────────────────────────────────────────────

const DEVICE_CAPABILITIES: Record<string, { label: string; enabled: boolean }[]> = {
  "cisco-2960": [
    { label: "L2 Switching",    enabled: true },
    { label: "VLANs",           enabled: true },
    { label: "802.1Q Trunk",     enabled: true },
    { label: "STP / RSTP",      enabled: true },
    { label: "EtherChannel",    enabled: true },
    { label: "Port Security",   enabled: true },
    { label: "L3 Routing",      enabled: false },
    { label: "SVI",             enabled: false },
    { label: "Routed Port",     enabled: false },
  ],
  "cisco-2911": [
    { label: "L3 Routing",      enabled: true },
    { label: "Static Routes",   enabled: true },
    { label: "Connected Routes",enabled: true },
    { label: "ARP",             enabled: true },
    { label: "ICMP",            enabled: true },
    { label: "L2 Switching",    enabled: false },
    { label: "VLANs",           enabled: false },
    { label: "STP",             enabled: false },
  ],
  "cisco-pc": [
    { label: "ARP",              enabled: true },
    { label: "ICMP Ping",       enabled: true },
    { label: "IPv4 Config",     enabled: true },
    { label: "Default Gateway", enabled: true },
  ],
  "cisco-laptop": [
    { label: "ARP",              enabled: true },
    { label: "ICMP Ping",       enabled: true },
    { label: "IPv4 Config",     enabled: true },
    { label: "Default Gateway", enabled: true },
  ],
  "cisco-server": [
    { label: "ARP",              enabled: true },
    { label: "ICMP Ping",       enabled: true },
    { label: "IPv4 Config",     enabled: true },
    { label: "Default Gateway", enabled: true },
  ],
};

// ── Icon map ──────────────────────────────────────────────────────────────────

const ICON_MAP: Record<string, React.ElementType> = {
  pc:        Monitor,
  laptop:    Laptop,
  server:    Server,
  "switch-l2": Network,
  router:    Network,
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function DevicesPage() {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Device Catalog</h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Simulated device types with full port-type support (FastEthernet, GigabitEthernet).
          Click a device to view its interface template and capabilities.
        </p>
      </div>

      {/* Port types reference */}
      <Card>
        <CardBody className="p-4">
          <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            Supported Port Types
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {PORT_TYPES.map((pt) => (
              <div
                key={pt.name}
                className="rounded-lg border border-[#30363d] bg-[#161b22] p-3"
              >
                <div className="flex items-center gap-2 mb-2">
                  <Zap size={13} className="text-[#58a6ff]" />
                  <span className="text-xs font-mono font-semibold text-[#e6edf3]">
                    {pt.ciscoName}
                  </span>
                </div>
                <div className="text-[10px] font-mono text-[#8b949e] space-y-0.5">
                  <div>Speed: <span className="text-[#58a6ff]">{pt.speed}</span></div>
                  <div>STP Cost: <span className="text-[#3fb950]">{pt.stpCost}</span></div>
                  <div>Trunk: <span className={pt.supportsTrunk ? "text-[#3fb950]" : "text-[#f85149]"}>
                    {pt.supportsTrunk ? "Yes" : "No"}
                  </span></div>
                  <div>L3: <span className={pt.supportsL3 ? "text-[#3fb950]" : "text-[#f85149]"}>
                    {pt.supportsL3 ? "Yes" : "No"}
                  </span></div>
                </div>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>

      {/* Device cards */}
      <div className="space-y-3">
        {DEFAULT_DEVICE_CATALOG.map((device) => (
          <DeviceCard
            key={device.id}
            device={device}
            expanded={expanded === device.id}
            onToggle={() =>
              setExpanded(expanded === device.id ? null : device.id)
            }
          />
        ))}
      </div>
    </div>
  );
}

// ── Device card with expandable details ───────────────────────────────────────

function DeviceCard({
  device,
  expanded,
  onToggle,
}: {
  device: DeviceCatalogEntry;
  expanded: boolean;
  onToggle: () => void;
}) {
  const Icon = ICON_MAP[device.icon] ?? Network;
  const template = DEVICE_INTERFACE_TEMPLATES[device.id];
  const capabilities = DEVICE_CAPABILITIES[device.id] ?? [];
  const portTypeSpec = PORT_TYPES.find((p) => p.name === template?.portType);

  return (
    <Card>
      {/* Header row */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 p-4 text-left hover:bg-[#1c2128] transition-colors rounded-t-lg"
      >
        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
          style={{
            background: device.simulated ? "rgba(29,53,88,0.5)" : "var(--surface-overlay)",
            border: `1px solid ${device.simulated ? "#58a6ff" : "#30363d"}`,
          }}
          aria-hidden="true"
        >
          <Icon
            size={16}
            className={device.simulated ? "text-[#58a6ff]" : "text-[var(--text-muted)]"}
          />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              {device.label}
            </span>
            {device.simulated ? (
              <Badge variant="success">
                <CheckCircle2 size={10} className="mr-1" />
                Simulated
              </Badge>
            ) : (
              <Badge variant="warning">
                <Clock size={10} className="mr-1" />
                Coming soon
              </Badge>
            )}
          </div>
          <p className="text-xs text-[var(--text-muted)] font-mono">{device.modelName}</p>
        </div>

        {/* Port summary */}
        {template && portTypeSpec && (
          <div className="hidden sm:flex items-center gap-3 text-[10px] font-mono text-[#8b949e]">
            <span>{template.count}× {portTypeSpec.short}</span>
            <span className="text-[#58a6ff]">{portTypeSpec.speed}</span>
          </div>
        )}

        <ChevronRight
          size={16}
          className={`text-[#484f58] transition-transform shrink-0 ${
            expanded ? "rotate-90" : ""
          }`}
        />
      </button>

      {/* Expandable details */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden border-t border-[#30363d]"
          >
            <div className="p-4 space-y-4">
              {/* Description */}
              <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                {device.description}
              </p>

              {/* Interface template */}
              {template && portTypeSpec && (
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-widest text-[#484f58] mb-2">
                    Interface Template
                  </h3>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
                    <DetailItem label="Port Count" value={String(template.count)} />
                    <DetailItem label="Port Type" value={portTypeSpec.ciscoName} />
                    <DetailItem label="Default Speed" value={portTypeSpec.speed} />
                    <DetailItem label="STP Cost" value={String(portTypeSpec.stpCost)} />
                  </div>

                  {/* Interface list */}
                  <div className="mt-3">
                    <table className="w-full text-[11px] font-mono">
                      <thead>
                        <tr className="text-[#484f58] text-[10px] border-b border-[#21262d]">
                          <th className="text-left py-1 pr-2">Interface</th>
                          <th className="text-left py-1 pr-2">Type</th>
                          <th className="text-left py-1 pr-2">Speed</th>
                          <th className="text-left py-1 pr-2">Duplex</th>
                          <th className="text-left py-1">STP Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Array.from({ length: Math.min(template.count, 8) }, (_, i) => (
                          <tr key={i} className="border-b border-[#21262d] last:border-0">
                            <td className="py-1.5 pr-2 text-[#8b949e]">
                              {template.defaultName.replace("{n}", String(i))}
                            </td>
                            <td className="py-1.5 pr-2 text-[#e6edf3]">{portTypeSpec.ciscoName}</td>
                            <td className="py-1.5 pr-2 text-[#58a6ff]">{portTypeSpec.speed}</td>
                            <td className="py-1.5 pr-2 text-[#8b949e]">auto</td>
                            <td className="py-1.5 text-[#3fb950]">{portTypeSpec.stpCost}</td>
                          </tr>
                        ))}
                        {template.count > 8 && (
                          <tr>
                            <td colSpan={5} className="py-1.5 text-[#484f58] text-center">
                              ... {template.count - 8} more ports
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Capabilities */}
              {capabilities.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-widest text-[#484f58] mb-2">
                    Capabilities
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {capabilities.map((cap) => (
                      <div
                        key={cap.label}
                        className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-mono"
                        style={{
                          background: cap.enabled ? "rgba(63,185,80,0.08)" : "rgba(72,79,88,0.1)",
                          border: `1px solid ${cap.enabled ? "rgba(63,185,80,0.2)" : "#30363d"}`,
                          color: cap.enabled ? "#3fb950" : "#484f58",
                        }}
                      >
                        {cap.enabled ? (
                          <CheckCircle2 size={11} />
                        ) : (
                          <span className="w-[11px] h-[11px] flex items-center justify-center">✕</span>
                        )}
                        {cap.label}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-[#30363d] px-2.5 py-1.5">
      <div className="text-[9px] text-[#484f58] uppercase tracking-wider">{label}</div>
      <div className="text-[#e6edf3] mt-0.5">{value}</div>
    </div>
  );
}
