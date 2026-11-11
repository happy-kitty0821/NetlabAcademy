"use client";

import { useState, useEffect, useRef } from "react";
import type { DeviceNode, DeviceNodeData } from "@/lib/deviceTypes";
import { X, CheckCircle2 } from "lucide-react";

function validateIp(ip: string): string {
  if (!ip) return "";
  const parts = ip.trim().split("/");
  if (parts.length !== 2) return "Use CIDR: 192.168.1.1/24";
  const prefix = parseInt(parts[1]);
  if (isNaN(prefix) || prefix < 0 || prefix > 32) return "Prefix must be 0–32";
  const octets = parts[0].split(".");
  if (octets.length !== 4 || octets.some((o) => isNaN(Number(o)) || Number(o) > 255)) return "Invalid IP";
  return "";
}

export function NodeConfigPopup({ node, onSave, onClose }: {
  node: DeviceNode;
  onSave: (id: string, patch: Partial<DeviceNodeData>) => void;
  onClose: () => void;
}) {
  const [hostname, setHostname] = useState(String(node.data.hostname ?? ""));
  const [ip,       setIp]       = useState(String(node.data.ip ?? ""));
  const [gateway,  setGateway]  = useState(String(node.data.gateway ?? ""));
  const [ipErr,    setIpErr]    = useState("");
  const isHost = node.data.model === "host";
  const ref    = useRef<HTMLInputElement>(null);

  useEffect(() => { ref.current?.focus(); }, []);
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  function save() {
    if (isHost && ip && ipErr) return;
    onSave(node.id, {
      hostname: hostname.trim() || String(node.data.hostname),
      ip:      isHost ? (ip.trim() || undefined) : undefined,
      gateway: isHost ? (gateway.trim() || undefined) : undefined,
    });
  }

  const model = node.data.model === "host" ? "PC / Host" : node.data.model === "switch" ? "Switch" : "Router";

  return (
    <div
      style={{ position: "absolute", inset: 0, zIndex: 50, display: "flex", alignItems: "center",
        justifyContent: "center", background: "rgba(31,35,40,0.4)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{ width: 320, background: "#ffffff", border: "1px solid #d0d7de",
        borderRadius: 12, boxShadow: "0 8px 24px rgba(0,0,0,0.12)" }}
        onKeyDown={(e) => { if (e.key === "Enter") save(); }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px", borderBottom: "1px solid #d0d7de" }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#1f2328" }}>Configure device</div>
            <div style={{ fontSize: 11, color: "#656d76", marginTop: 2 }}>{model}</div>
          </div>
          <button onClick={onClose}
            style={{ padding: 5, borderRadius: 6, border: "none", background: "transparent", cursor: "pointer", color: "#656d76" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "#f0f2f4"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Hostname">
            <input ref={ref} type="text" value={hostname} onChange={(e) => setHostname(e.target.value)}
              placeholder="SW1" style={inp()} />
          </Field>
          {isHost && (
            <>
              <Field label="IP Address (CIDR)" hint={!ipErr ? "e.g. 192.168.1.1/24" : undefined} error={ipErr}>
                <input type="text" value={ip}
                  onChange={(e) => { setIp(e.target.value); setIpErr(validateIp(e.target.value)); }}
                  placeholder="192.168.1.1/24" style={inp(!!ipErr)} />
              </Field>
              <Field label="Default Gateway" hint="Optional">
                <input type="text" value={gateway} onChange={(e) => setGateway(e.target.value)}
                  placeholder="192.168.1.254" style={inp()} />
              </Field>
            </>
          )}
        </div>

        {/* Footer */}
        <div style={{ display: "flex", gap: 8, padding: "0 16px 16px" }}>
          <button onClick={save} disabled={!!(isHost && ip && ipErr)}
            style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
              padding: "8px 0", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer",
              color: "#ffffff", background: "#1a7f37", border: "1px solid #1a7f37",
              opacity: (isHost && ip && ipErr) ? 0.4 : 1 }}>
            <CheckCircle2 size={13} />
            Save
          </button>
          <button onClick={onClose}
            style={{ padding: "8px 16px", borderRadius: 6, fontSize: 13, cursor: "pointer",
              color: "#656d76", background: "transparent", border: "1px solid #d0d7de" }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "#f6f8fa"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
            Skip
          </button>
        </div>
      </div>
    </div>
  );
}

function inp(hasError = false): React.CSSProperties {
  return {
    width: "100%", padding: "7px 10px", borderRadius: 6, fontSize: 13,
    color: "#1f2328", outline: "none", background: "#ffffff", boxSizing: "border-box",
    border: `1px solid ${hasError ? "#d1242f" : "#d0d7de"}`,
    fontFamily: "monospace",
  };
}

function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ fontSize: 11, fontWeight: 600, color: "#1f2328" }}>{label}</label>
      {children}
      {error && <span style={{ fontSize: 11, color: "#d1242f" }}>{error}</span>}
      {hint && !error && <span style={{ fontSize: 11, color: "#9198a1" }}>{hint}</span>}
    </div>
  );
}
