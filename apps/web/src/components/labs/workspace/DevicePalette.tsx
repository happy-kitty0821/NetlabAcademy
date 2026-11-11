"use client";

/**
 * DevicePalette — left sidebar.
 *
 * Drag a device icon onto the canvas to place it.
 * No "Build topology" button. No extra steps.
 *
 * Uses HTML5 drag-and-drop: sets dataTransfer so the canvas can read the
 * catalog ID on drop.
 */

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { DEFAULT_DEVICE_CATALOG } from "@/lib/deviceTypes";
import type { DeviceCatalogEntry } from "@/lib/deviceTypes";

// SVG icons inline — no external deps
function DeviceIcon({ entry }: { entry: DeviceCatalogEntry }) {
  if (entry.icon === "switch-l2") return (
    <svg width="28" height="18" viewBox="0 0 52 30" fill="none" aria-hidden="true">
      <rect x="1" y="4" width="50" height="22" rx="3" fill="#1c2128" stroke="#30363d" strokeWidth="1.5" />
      <line x1="6" y1="18" x2="13" y2="18" stroke="#58a6ff" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M10 15 L13 18 L10 21" stroke="#58a6ff" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      <line x1="46" y1="18" x2="39" y2="18" stroke="#58a6ff" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M42 15 L39 18 L42 21" stroke="#58a6ff" strokeWidth="1.5" fill="none" strokeLinecap="round" />
      {[0,1,2,3].map((i) => (
        <rect key={i} x={18 + i * 5} y={21} width="3" height="4" rx="0.5" fill={i < 2 ? "#3fb950" : "#484f58"} />
      ))}
    </svg>
  );

  if (entry.icon === "router") return (
    <svg width="22" height="22" viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <circle cx="24" cy="24" r="21" fill="#1c2128" stroke="#30363d" strokeWidth="1.5" />
      <line x1="24" y1="8" x2="24" y2="14" stroke="#58a6ff" strokeWidth="2" strokeLinecap="round" />
      <path d="M20 11 L24 8 L28 11" stroke="#58a6ff" strokeWidth="2" fill="none" strokeLinecap="round" />
      <line x1="40" y1="24" x2="34" y2="24" stroke="#58a6ff" strokeWidth="2" strokeLinecap="round" />
      <path d="M37 20 L40 24 L37 28" stroke="#58a6ff" strokeWidth="2" fill="none" strokeLinecap="round" />
      <line x1="8" y1="24" x2="14" y2="24" stroke="#58a6ff" strokeWidth="2" strokeLinecap="round" />
      <path d="M11 20 L8 24 L11 28" stroke="#58a6ff" strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );

  if (entry.icon === "laptop") return (
    <svg width="22" height="20" viewBox="0 0 44 36" fill="none" aria-hidden="true">
      <rect x="4" y="2" width="36" height="24" rx="2" fill="#1c2128" stroke="#30363d" strokeWidth="1.5" />
      <rect x="7" y="5" width="30" height="18" rx="1" fill="#010409" />
      <rect x="1" y="26" width="42" height="6" rx="2" fill="#1c2128" stroke="#30363d" strokeWidth="1.5" />
    </svg>
  );

  if (entry.icon === "server") return (
    <svg width="20" height="26" viewBox="0 0 36 44" fill="none" aria-hidden="true">
      {[0,1,2].map((i) => (
        <rect key={i} x="2" y={2 + i * 14} width="32" height="12" rx="2" fill="#1c2128" stroke="#30363d" strokeWidth="1.5" />
      ))}
      <circle cx="8" cy="8" r="2" fill="#3fb950" />
      <circle cx="8" cy="22" r="2" fill="#58a6ff" />
    </svg>
  );

  // PC (default)
  return (
    <svg width="26" height="22" viewBox="0 0 44 38" fill="none" aria-hidden="true">
      <rect x="2" y="1" width="40" height="26" rx="2.5" fill="#1c2128" stroke="#30363d" strokeWidth="1.5" />
      <rect x="5" y="4" width="34" height="20" rx="1" fill="#010409" />
      <rect x="18" y="27" width="8" height="4" fill="#1c2128" stroke="#30363d" strokeWidth="1.2" />
      <rect x="11" y="31" width="22" height="4" rx="1.5" fill="#1c2128" stroke="#30363d" strokeWidth="1.2" />
    </svg>
  );
}

const CATEGORIES = [
  { label: "End Devices", ids: ["cisco-pc", "cisco-laptop", "cisco-server"] },
  { label: "Switches",    ids: ["cisco-2960"] },
  { label: "Routers",     ids: ["cisco-2911"] },
];

export function DevicePalette() {
  const [collapsed, setCollapsed]       = useState(false);
  const [expanded,  setExpanded]        = useState<Record<string, boolean>>({
    "End Devices": true, "Switches": true, "Routers": true,
  });
  const [dragging, setDragging]         = useState<string | null>(null);

  if (collapsed) {
    return (
      <div
        className="flex flex-col items-center pt-2 border-r border-[#21262d] shrink-0"
        style={{ width: 36, background: "#161b22" }}
      >
        <button
          onClick={() => setCollapsed(false)}
          className="p-1.5 rounded text-[#484f58] hover:text-[#8b949e] hover:bg-[#21262d] transition-colors"
          title="Show palette"
          aria-label="Expand device palette"
        >
          <ChevronRight size={13} />
        </button>
      </div>
    );
  }

  return (
    <div
      className="flex flex-col border-r border-[#21262d] shrink-0 select-none"
      style={{ width: 192, background: "#161b22" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 h-9 border-b border-[#21262d]">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-[#484f58]">
          Devices
        </span>
        <button
          onClick={() => setCollapsed(true)}
          className="p-1 rounded text-[#484f58] hover:text-[#8b949e] hover:bg-[#21262d] transition-colors"
          title="Collapse palette"
          aria-label="Collapse device palette"
        >
          <ChevronLeft size={12} />
        </button>
      </div>

      {/* Drag hint */}
      <div className="px-3 py-2 border-b border-[#21262d]">
        <p className="text-[10px] text-[#484f58] font-mono leading-relaxed">
          Drag a device onto the canvas to place it.
        </p>
      </div>

      {/* Categories */}
      <div className="flex-1 overflow-y-auto py-1">
        {CATEGORIES.map((cat) => {
          const devices = DEFAULT_DEVICE_CATALOG.filter((d) => cat.ids.includes(d.id));
          const open    = expanded[cat.label] !== false;

          return (
            <div key={cat.label}>
              {/* Category header */}
              <button
                onClick={() => setExpanded((p) => ({ ...p, [cat.label]: !open }))}
                className="w-full flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[#484f58] hover:text-[#8b949e] transition-colors"
              >
                <ChevronRight size={10} className={`transition-transform ${open ? "rotate-90" : ""}`} />
                {cat.label}
              </button>

              {/* Device items */}
              {open && devices.map((device) => (
                <div
                  key={device.id}
                  draggable={device.simulated}
                  onDragStart={(e) => {
                    e.dataTransfer.setData("application/netlab-device", device.id);
                    e.dataTransfer.effectAllowed = "copy";
                    setDragging(device.id);
                  }}
                  onDragEnd={() => setDragging(null)}
                  title={device.simulated ? `Drag to canvas: ${device.description}` : "Coming soon"}
                  className={`
                    flex items-center gap-3 px-4 py-2 cursor-grab active:cursor-grabbing
                    transition-colors border-l-2
                    ${device.simulated
                      ? dragging === device.id
                        ? "border-[#58a6ff] bg-[#1d3558] text-[#e6edf3]"
                        : "border-transparent text-[#8b949e] hover:text-[#e6edf3] hover:bg-[#1c2128] hover:border-[#30363d]"
                      : "border-transparent text-[#484f58] opacity-50 cursor-not-allowed"
                    }
                  `}
                >
                  <DeviceIcon entry={device} />
                  <div className="min-w-0">
                    <div className="text-[11px] font-mono font-medium leading-tight truncate">
                      {device.label}
                    </div>
                    {!device.simulated && (
                      <div className="text-[9px] text-[#f85149] font-mono">soon</div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
