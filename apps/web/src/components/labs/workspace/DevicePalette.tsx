"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { DEFAULT_DEVICE_CATALOG } from "@/lib/deviceTypes";
import type { DeviceCatalogEntry } from "@/lib/deviceTypes";
import { DeviceTile, type DeviceKind } from "@/components/labs/FlowNodes";

function DeviceIcon({ entry }: { entry: DeviceCatalogEntry }) {
  // Same tile as on the canvas, smaller.
  return <DeviceTile kind={entry.icon as DeviceKind} size={26} />;
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
