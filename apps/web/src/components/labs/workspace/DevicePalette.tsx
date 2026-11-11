"use client";

/**
 * DevicePalette — left sidebar, CML style.
 * Drag a device onto the canvas to place it.
 */

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { DEFAULT_DEVICE_CATALOG } from "@/lib/deviceTypes";
import type { DeviceCatalogEntry } from "@/lib/deviceTypes";

// CML palette
const P = {
  bg:       "#16213e",
  border:   "#0f3460",
  label:    "#cdd6f4",
  muted:    "#7c7f93",
  hover:    "#0f3460",
  active:   "#00b4d8",
  error:    "#e94560",
  host:     "#48cae4",
  sw:       "#00b4d8",
  rt:       "#e94560",
  iconFill: "#0f3460",
  screen:   "#020510",
};

function DeviceIcon({ entry }: { entry: DeviceCatalogEntry }) {
  if (entry.icon === "switch-l2") return (
    <svg width="30" height="19" viewBox="0 0 64 36" fill="none" aria-hidden="true">
      <rect x="1" y="4" width="62" height="28" rx="4" fill={P.iconFill} stroke={P.sw} strokeWidth="1.5" />
      <line x1="5" y1="22" x2="14" y2="22" stroke={P.sw} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M11 19 L14 22 L11 25" stroke={P.sw} strokeWidth="1.5" fill="none" strokeLinecap="round" />
      <line x1="59" y1="22" x2="50" y2="22" stroke={P.sw} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M53 19 L50 22 L53 25" stroke={P.sw} strokeWidth="1.5" fill="none" strokeLinecap="round" />
    </svg>
  );
  if (entry.icon === "router") return (
    <svg width="22" height="22" viewBox="0 0 52 52" fill="none" aria-hidden="true">
      <circle cx="26" cy="26" r="23" fill={P.iconFill} stroke={P.rt} strokeWidth="1.5" />
      <line x1="26" y1="7" x2="26" y2="14" stroke={P.rt} strokeWidth="2" strokeLinecap="round" />
      <path d="M22 11 L26 7 L30 11" stroke={P.rt} strokeWidth="2" fill="none" strokeLinecap="round" />
      <line x1="45" y1="26" x2="38" y2="26" stroke={P.rt} strokeWidth="2" strokeLinecap="round" />
      <path d="M41 22 L45 26 L41 30" stroke={P.rt} strokeWidth="2" fill="none" strokeLinecap="round" />
      <line x1="7" y1="26" x2="14" y2="26" stroke={P.rt} strokeWidth="2" strokeLinecap="round" />
      <path d="M11 22 L7 26 L11 30" stroke={P.rt} strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );
  if (entry.icon === "laptop") return (
    <svg width="24" height="20" viewBox="0 0 54 40" fill="none" aria-hidden="true">
      <rect x="4" y="1" width="46" height="29" rx="3" fill={P.iconFill} stroke={P.host} strokeWidth="1.5" />
      <rect x="8" y="5" width="38" height="21" rx="1.5" fill={P.screen} />
      <rect x="1" y="30" width="52" height="8" rx="2.5" fill={P.iconFill} stroke={P.host} strokeWidth="1.5" />
    </svg>
  );
  if (entry.icon === "server") return (
    <svg width="20" height="28" viewBox="0 0 44 52" fill="none" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <rect key={i} x="2" y={2 + i * 17} width="40" height="14" rx="2.5"
          fill={P.iconFill} stroke={P.host} strokeWidth="1.5" />
      ))}
    </svg>
  );
  // PC default
  return (
    <svg width="26" height="24" viewBox="0 0 52 46" fill="none" aria-hidden="true">
      <rect x="2" y="1" width="48" height="32" rx="3" fill={P.iconFill} stroke={P.host} strokeWidth="1.5" />
      <rect x="6" y="5" width="40" height="24" rx="1.5" fill={P.screen} />
      <rect x="22" y="33" width="8" height="5" fill={P.iconFill} stroke={P.host} strokeWidth="1.2" />
      <rect x="15" y="38" width="22" height="5" rx="2" fill={P.iconFill} stroke={P.host} strokeWidth="1.2" />
    </svg>
  );
}

const CATEGORIES = [
  { label: "End Devices", ids: ["cisco-pc", "cisco-laptop", "cisco-server"] },
  { label: "Switches",    ids: ["cisco-2960"] },
  { label: "Routers",     ids: ["cisco-2911"] },
];

export function DevicePalette() {
  const [collapsed, setCollapsed] = useState(false);
  const [expanded,  setExpanded]  = useState<Record<string, boolean>>({
    "End Devices": true, "Switches": true, "Routers": true,
  });
  const [dragging, setDragging] = useState<string | null>(null);

  if (collapsed) {
    return (
      <div
        className="flex flex-col items-center pt-2 shrink-0"
        style={{ width: 36, background: P.bg, borderRight: `1px solid ${P.border}` }}
      >
        <button
          onClick={() => setCollapsed(false)}
          className="p-1.5 rounded transition-colors"
          style={{ color: P.muted }}
          onMouseEnter={(e) => { e.currentTarget.style.color = P.active; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = P.muted; }}
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
      className="flex flex-col shrink-0 select-none"
      style={{ width: 188, background: P.bg, borderRight: `1px solid ${P.border}` }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 h-9"
        style={{ borderBottom: `1px solid ${P.border}` }}
      >
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: P.muted }}>
          Devices
        </span>
        <button
          onClick={() => setCollapsed(true)}
          className="p-1 rounded transition-colors"
          style={{ color: P.muted }}
          onMouseEnter={(e) => { e.currentTarget.style.color = P.active; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = P.muted; }}
          title="Collapse"
        >
          <ChevronLeft size={12} />
        </button>
      </div>

      {/* Hint */}
      <div className="px-3 py-2" style={{ borderBottom: `1px solid ${P.border}` }}>
        <p style={{ fontSize: 10, color: P.muted, fontFamily: "monospace", lineHeight: 1.5 }}>
          Drag onto canvas to place
        </p>
      </div>

      {/* Categories */}
      <div className="flex-1 overflow-y-auto py-1">
        {CATEGORIES.map((cat) => {
          const devices = DEFAULT_DEVICE_CATALOG.filter((d) => cat.ids.includes(d.id));
          const open    = expanded[cat.label] !== false;
          return (
            <div key={cat.label}>
              <button
                onClick={() => setExpanded((p) => ({ ...p, [cat.label]: !open }))}
                className="w-full flex items-center gap-1.5 px-3 py-1.5 transition-colors"
                style={{ color: P.muted, fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase" }}
              >
                <ChevronRight size={10} style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform 0.15s" }} />
                {cat.label}
              </button>

              {open && devices.map((device) => {
                const isDragging = dragging === device.id;
                return (
                  <div
                    key={device.id}
                    draggable={device.simulated}
                    onDragStart={(e) => {
                      e.dataTransfer.setData("application/netlab-device", device.id);
                      e.dataTransfer.effectAllowed = "copy";
                      setDragging(device.id);
                    }}
                    onDragEnd={() => setDragging(null)}
                    title={device.simulated ? device.description : "Coming soon"}
                    style={{
                      display:       "flex",
                      alignItems:    "center",
                      gap:           10,
                      padding:       "7px 16px",
                      cursor:        device.simulated ? "grab" : "not-allowed",
                      opacity:       device.simulated ? 1 : 0.4,
                      borderLeft:    `2px solid ${isDragging ? P.active : "transparent"}`,
                      background:    isDragging ? P.hover : "transparent",
                      transition:    "background 0.1s, border-color 0.1s",
                    }}
                    onMouseEnter={(e) => {
                      if (device.simulated && !isDragging) {
                        e.currentTarget.style.background = P.hover;
                        e.currentTarget.style.borderLeftColor = P.border;
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!isDragging) {
                        e.currentTarget.style.background = "transparent";
                        e.currentTarget.style.borderLeftColor = "transparent";
                      }
                    }}
                  >
                    <DeviceIcon entry={device} />
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 600, color: P.label, fontFamily: "monospace" }}>
                        {device.label}
                      </div>
                      {!device.simulated && (
                        <div style={{ fontSize: 9, color: P.error, fontFamily: "monospace" }}>soon</div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
