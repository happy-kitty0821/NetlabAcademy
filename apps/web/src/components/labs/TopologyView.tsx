"use client";

/**
 * TopologyView — a visual representation of the network topology.
 *
 * For this first slice, it renders a simple diagram of nodes and links
 * using styled divs. A React Flow / XYFlow canvas will replace this in
 * the topology-editor spec, but this is sufficient for the lab
 * integration slice.
 */

import { TopologyDocument } from "@/lib/simulation-api";
import { cn } from "@/lib/utils";
import { Monitor, Network } from "lucide-react";

interface TopologyViewProps {
  topology: TopologyDocument;
}

export function TopologyView({ topology }: TopologyViewProps) {
  const hosts = topology.nodes.filter((n) => n.model === "host");
  const switches = topology.nodes.filter((n) => n.model === "switch");

  return (
    <div className="rounded-lg border border-[var(--surface-border)] bg-[var(--surface-raised)] p-5">
      <div className="flex items-center justify-center gap-8 flex-wrap">
        {/* Render hosts on the left and right, switches in the middle */}
        <div className="flex flex-col gap-4">
          {hosts.map((host) => (
            <NodeCard key={host.id} node={host} />
          ))}
        </div>

        {/* Links (visual) */}
        <div className="flex flex-col gap-4 px-2">
          {hosts.map((_, i) => (
            <div
              key={i}
              className="w-12 h-0.5 bg-[var(--canvas-link)] self-center"
              aria-hidden="true"
            />
          ))}
        </div>

        {/* Switches in the center */}
        <div className="flex flex-col gap-4">
          {switches.map((sw) => (
            <NodeCard key={sw.id} node={sw} />
          ))}
        </div>
      </div>

      {/* Link details */}
      <div className="mt-4 pt-4 border-t border-[var(--surface-border)]">
        <p className="text-xs text-[var(--text-muted)] mb-2">Links</p>
        <ul className="space-y-1">
          {topology.links.map((link) => (
            <li
              key={link.id}
              className="text-xs text-[var(--text-secondary)] font-mono"
            >
              {link.device_a}:{link.interface_a}
              <span className="text-[var(--text-muted)] mx-1.5">{"<->"}</span>
              {link.device_b}:{link.interface_b}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function NodeCard({
  node,
}: {
  node: TopologyDocument["nodes"][number];
}) {
  const isSwitch = node.model === "switch";
  const Icon = isSwitch ? Network : Monitor;

  return (
    <div
      className={cn(
        "rounded-lg border-2 p-3 min-w-[140px]",
        isSwitch
          ? "border-[var(--accent-primary)] bg-[var(--surface-overlay)]"
          : "border-[var(--surface-border)] bg-[var(--surface-raised)]"
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon
          size={14}
          className={isSwitch ? "text-[var(--accent-primary)]" : "text-[var(--text-secondary)]"}
          aria-hidden="true"
        />
        <span className="text-xs font-semibold text-[var(--text-primary)]">
          {node.hostname || node.id}
        </span>
      </div>
      <div className="text-[10px] text-[var(--text-muted)] font-mono">
        {node.id}
      </div>
      {node.interfaces.map((iface) => (
        <div key={iface.name} className="mt-1 text-[10px] text-[var(--text-secondary)] font-mono">
          {iface.name}
          {iface.ip && (
            <span className="text-[var(--accent-primary)]"> {iface.ip}</span>
          )}
        </div>
      ))}
    </div>
  );
}
