"use client";

/**
 * NodePalette — left sidebar.
 * CML-style collapsible palette showing device categories.
 * Also houses the topology editor toggle.
 */

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronRight, PenLine } from "lucide-react";
import { DEFAULT_DEVICE_CATALOG } from "@/lib/deviceTypes";
import type { TopologyDocument } from "@/lib/simulation-api";
import { TopologyEditor } from "@/components/labs/TopologyEditor";

const CATEGORIES = [
  { label: "End Devices",    ids: ["cisco-pc", "cisco-laptop", "cisco-server"] },
  { label: "Switches",       ids: ["cisco-2960"] },
  { label: "Routers",        ids: ["cisco-2911"] },
];

interface NodePaletteProps {
  onApplyTopology: (topo: TopologyDocument) => void;
}

export function NodePalette({ onApplyTopology }: NodePaletteProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    "End Devices": true, "Switches": true, "Routers": true,
  });
  const [editorOpen, setEditorOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const toggleCat = (label: string) =>
    setExpanded((p) => ({ ...p, [label]: !p[label] }));

  if (editorOpen) {
    return (
      <div
        className="flex flex-col border-r border-[#21262d] overflow-hidden"
        style={{ width: 480, background: "#161b22" }}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b border-[#21262d]">
          <span className="text-xs font-semibold text-[#e6edf3] font-mono">
            TOPOLOGY EDITOR
          </span>
          <button
            onClick={() => setEditorOpen(false)}
            className="text-[#8b949e] hover:text-[#e6edf3] text-xs px-2 py-0.5 rounded hover:bg-[#21262d]"
          >
            Close
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          <TopologyEditor
            onApply={(topo) => {
              onApplyTopology(topo);
              setEditorOpen(false);
            }}
          />
        </div>
      </div>
    );
  }

  if (collapsed) {
    return (
      <div
        className="flex flex-col items-center py-2 gap-2 border-r border-[#21262d]"
        style={{ width: 40, background: "#161b22" }}
      >
        <button
          onClick={() => setCollapsed(false)}
          className="p-1.5 rounded hover:bg-[#21262d] text-[#8b949e] hover:text-[#e6edf3]"
          title="Expand palette"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    );
  }

  return (
    <div
      className="flex flex-col border-r border-[#21262d] shrink-0"
      style={{ width: 200, background: "#161b22" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#21262d]">
        <span className="text-[11px] font-semibold text-[#8b949e] uppercase tracking-widest">
          Nodes
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setEditorOpen(true)}
            className="p-1 rounded hover:bg-[#21262d] text-[#8b949e] hover:text-[#58a6ff]"
            title="Open topology editor"
          >
            <PenLine size={13} />
          </button>
          <button
            onClick={() => setCollapsed(true)}
            className="p-1 rounded hover:bg-[#21262d] text-[#484f58] hover:text-[#8b949e]"
            title="Collapse"
          >
            <ChevronRight size={13} className="rotate-180" />
          </button>
        </div>
      </div>

      {/* Categories */}
      <div className="flex-1 overflow-y-auto py-1">
        {CATEGORIES.map((cat) => {
          const devices = DEFAULT_DEVICE_CATALOG.filter((d) =>
            cat.ids.includes(d.id),
          );
          const open = expanded[cat.label] ?? true;
          return (
            <div key={cat.label}>
              <button
                onClick={() => toggleCat(cat.label)}
                className="w-full flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[#8b949e] hover:text-[#e6edf3] transition-colors"
              >
                <ChevronRight
                  size={11}
                  className={`transition-transform ${open ? "rotate-90" : ""}`}
                />
                <span className="font-semibold uppercase tracking-wider">
                  {cat.label}
                </span>
              </button>
              <AnimatePresence>
                {open && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.15 }}
                    className="overflow-hidden"
                  >
                    {devices.map((device) => (
                      <div
                        key={device.id}
                        draggable
                        className="flex items-center gap-2.5 px-5 py-1.5 cursor-grab active:cursor-grabbing text-[12px] text-[#8b949e] hover:text-[#e6edf3] hover:bg-[#1c2128] transition-colors"
                        title={device.description}
                      >
                        <span className="font-mono">{device.label}</span>
                        {!device.simulated && (
                          <span className="text-[9px] text-[#f85149] ml-auto">soon</span>
                        )}
                      </div>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-[#21262d]">
        <button
          onClick={() => setEditorOpen(true)}
          className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded text-[11px] font-mono text-[#58a6ff] hover:bg-[#1d3558] transition-colors"
          style={{ border: "1px solid rgba(88,166,255,0.2)" }}
        >
          <PenLine size={11} />
          Build topology
        </button>
      </div>
    </div>
  );
}
