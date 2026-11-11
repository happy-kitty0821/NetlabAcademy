"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { DEFAULT_DEVICE_CATALOG } from "@/lib/deviceTypes";
import type { DeviceCatalogEntry } from "@/lib/deviceTypes";

function DeviceIcon({ entry }: { entry: DeviceCatalogEntry }) {
  const sw = "#1a7f37", rt = "#9a6700", host = "#0969da";
  const bg = "#f6f8fa", sc = "#0d1117";

  if (entry.icon === "switch-l2") return (
    <svg width="28" height="18" viewBox="0 0 52 30" fill="none" aria-hidden="true">
      <rect x="1" y="4" width="50" height="22" rx="3" fill={bg} stroke={sw} strokeWidth="1.5" />
      <line x1="6" y1="18" x2="13" y2="18" stroke={sw} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M10 15 L13 18 L10 21" stroke={sw} strokeWidth="1.5" fill="none" strokeLinecap="round" />
      <line x1="46" y1="18" x2="39" y2="18" stroke={sw} strokeWidth="1.5" strokeLinecap="round" />
      <path d="M42 15 L39 18 L42 21" stroke={sw} strokeWidth="1.5" fill="none" strokeLinecap="round" />
    </svg>
  );
  if (entry.icon === "router") return (
    <svg width="22" height="22" viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <circle cx="24" cy="24" r="21" fill={bg} stroke={rt} strokeWidth="1.5" />
      <line x1="24" y1="8" x2="24" y2="14" stroke={rt} strokeWidth="2" strokeLinecap="round" />
      <path d="M20 11 L24 8 L28 11" stroke={rt} strokeWidth="2" fill="none" strokeLinecap="round" />
      <line x1="40" y1="24" x2="34" y2="24" stroke={rt} strokeWidth="2" strokeLinecap="round" />
      <path d="M37 20 L40 24 L37 28" stroke={rt} strokeWidth="2" fill="none" strokeLinecap="round" />
      <line x1="8" y1="24" x2="14" y2="24" stroke={rt} strokeWidth="2" strokeLinecap="round" />
      <path d="M11 20 L8 24 L11 28" stroke={rt} strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );
  if (entry.icon === "laptop") return (
    <svg width="24" height="20" viewBox="0 0 44 36" fill="none" aria-hidden="true">
      <rect x="4" y="2" width="36" height="24" rx="2" fill={bg} stroke={host} strokeWidth="1.5" />
      <rect x="7" y="5" width="30" height="18" rx="1" fill={sc} />
      <rect x="1" y="26" width="42" height="6" rx="2" fill={bg} stroke={host} strokeWidth="1.5" />
    </svg>
  );
  if (entry.icon === "server") return (
    <svg width="20" height="26" viewBox="0 0 36 44" fill="none" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <rect key={i} x="2" y={2 + i * 14} width="32" height="12" rx="2" fill={bg} stroke={host} strokeWidth="1.5" />
      ))}
    </svg>
  );
  return (
    <svg width="26" height="22" viewBox="0 0 44 38" fill="none" aria-hidden="true">
      <rect x="2" y="1" width="40" height="26" rx="2.5" fill={bg} stroke={host} strokeWidth="1.5" />
      <rect x="5" y="4" width="34" height="20" rx="1" fill={sc} />
      <rect x="18" y="27" width="8" height="4" fill={bg} stroke={host} strokeWidth="1.2" />
      <rect x="11" y="31" width="22" height="4" rx="1.5" fill={bg} stroke={host} strokeWidth="1.2" />
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
    "End Devices": true, Switches: true, Routers: true,
  });
  const [dragging, setDragging] = useState<string | null>(null);

  if (collapsed) {
    return (
      <div style={{ width: 36, background: "#ffffff", borderRight: "1px solid #d0d7de",
        display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 8, flexShrink: 0 }}>
        <button onClick={() => setCollapsed(false)} title="Expand"
          style={{ padding: 6, borderRadius: 4, border: "none", background: "transparent", cursor: "pointer", color: "#656d76" }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#f0f2f4"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
          <ChevronRight size={13} />
        </button>
      </div>
    );
  }

  return (
    <div style={{ width: 192, background: "#ffffff", borderRight: "1px solid #d0d7de",
      display: "flex", flexDirection: "column", flexShrink: 0, userSelect: "none" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 12px", height: 36, borderBottom: "1px solid #d0d7de" }}>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em",
          textTransform: "uppercase", color: "#656d76" }}>Devices</span>
        <button onClick={() => setCollapsed(true)} title="Collapse"
          style={{ padding: 4, borderRadius: 4, border: "none", background: "transparent", cursor: "pointer", color: "#656d76" }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "#f0f2f4"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
          <ChevronLeft size={12} />
        </button>
      </div>

      {/* Hint */}
      <div style={{ padding: "6px 12px", borderBottom: "1px solid #d0d7de" }}>
        <p style={{ fontSize: 10, color: "#9198a1", fontFamily: "monospace", lineHeight: 1.5, margin: 0 }}>
          Drag onto canvas to place
        </p>
      </div>

      {/* Categories */}
      <div style={{ flex: 1, overflowY: "auto", paddingBottom: 8 }}>
        {CATEGORIES.map((cat) => {
          const devices = DEFAULT_DEVICE_CATALOG.filter((d) => cat.ids.includes(d.id));
          const open    = expanded[cat.label] !== false;
          return (
            <div key={cat.label}>
              <button
                onClick={() => setExpanded((p) => ({ ...p, [cat.label]: !open }))}
                style={{ width: "100%", display: "flex", alignItems: "center", gap: 5,
                  padding: "5px 12px", border: "none", background: "transparent", cursor: "pointer",
                  fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "#656d76" }}
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
                      display: "flex", alignItems: "center", gap: 10,
                      padding: "6px 16px",
                      cursor: device.simulated ? "grab" : "not-allowed",
                      opacity: device.simulated ? 1 : 0.4,
                      background: isDragging ? "#ddf4ff" : "transparent",
                      borderLeft: `2px solid ${isDragging ? "#0969da" : "transparent"}`,
                      transition: "background 0.1s",
                    }}
                    onMouseEnter={(e) => {
                      if (device.simulated && !isDragging) {
                        e.currentTarget.style.background = "#f6f8fa";
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!isDragging) e.currentTarget.style.background = "transparent";
                    }}
                  >
                    <DeviceIcon entry={device} />
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 600, color: "#1f2328", fontFamily: "monospace" }}>
                        {device.label}
                      </div>
                      {!device.simulated && (
                        <div style={{ fontSize: 9, color: "#d1242f", fontFamily: "monospace" }}>soon</div>
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
