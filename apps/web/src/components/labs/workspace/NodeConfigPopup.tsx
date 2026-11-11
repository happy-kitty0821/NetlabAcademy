"use client";

/**
 * NodeConfigPopup — device configuration modal (CML style).
 * Opens automatically on drop, or on double-click when stopped.
 */

import { useState, useEffect, useRef } from "react";
import type { DeviceNode, DeviceNodeData } from "@/lib/deviceTypes";
import { X, CheckCircle2 } from "lucide-react";

const P = {
  bg:      "#16213e",
  border:  "#0f3460",
  input:   "#0d1b2a",
  label:   "#cdd6f4",
  muted:   "#7c7f93",
  active:  "#00b4d8",
  error:   "#e94560",
  green:   "#a6e3a1",
  hover:   "#0f3460",
};

interface NodeConfigPopupProps {
  node:    DeviceNode;
  onSave:  (id: string, patch: Partial<DeviceNodeData>) => void;
  onClose: () => void;
}

function validateIp(ip: string): string {
  if (!ip) return "";
  const parts = ip.trim().split("/");
  if (parts.length !== 2) return "Use CIDR: 192.168.1.1/24";
  const prefix = parseInt(parts[1]);
  if (isNaN(prefix) || prefix < 0 || prefix > 32) return "Prefix must be 0–32";
  const octets = parts[0].split(".");
  if (octets.length !== 4 || octets.some((o) => isNaN(Number(o)) || Number(o) > 255))
    return "Invalid IP address";
  return "";
}

export function NodeConfigPopup({ node, onSave, onClose }: NodeConfigPopupProps) {
  const [hostname, setHostname] = useState(String(node.data.hostname ?? ""));
  const [ip,       setIp]       = useState(String(node.data.ip ?? ""));
  const [gateway,  setGateway]  = useState(String(node.data.gateway ?? ""));
  const [ipErr,    setIpErr]    = useState("");
  const isHost = node.data.model === "host";
  const hostnameRef = useRef<HTMLInputElement>(null);

  useEffect(() => { hostnameRef.current?.focus(); }, []);
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  function handleIpChange(v: string) { setIp(v); setIpErr(validateIp(v)); }

  function handleSave() {
    if (isHost && ip && ipErr) return;
    onSave(node.id, {
      hostname: hostname.trim() || String(node.data.hostname),
      ip:       isHost ? (ip.trim() || undefined) : undefined,
      gateway:  isHost ? (gateway.trim() || undefined) : undefined,
    });
  }

  const modelLabel = node.data.model === "host" ? "PC / Host" : node.data.model === "switch" ? "Switch" : "Router";

  return (
    <div
      style={{ position: "absolute", inset: 0, zIndex: 50, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(13,27,42,0.75)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{ width: 320, background: P.bg, border: `1px solid ${P.border}`, borderRadius: 10, boxShadow: "0 8px 40px rgba(0,0,0,0.6)" }}
        onKeyDown={(e) => { if (e.key === "Enter") handleSave(); }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 16px", borderBottom: `1px solid ${P.border}` }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: P.label }}>Configure device</div>
            <div style={{ fontSize: 10, fontFamily: "monospace", color: P.muted, marginTop: 2 }}>{modelLabel}</div>
          </div>
          <button
            onClick={onClose}
            style={{ padding: 5, borderRadius: 4, color: P.muted, background: "transparent", border: "none", cursor: "pointer" }}
            onMouseEnter={(e) => { e.currentTarget.style.color = P.label; e.currentTarget.style.background = P.hover; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = P.muted; e.currentTarget.style.background = "transparent"; }}
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Hostname">
            <input
              ref={hostnameRef}
              type="text"
              value={hostname}
              onChange={(e) => setHostname(e.target.value)}
              placeholder="SW1"
              style={inputStyle()}
            />
          </Field>

          {isHost && (
            <>
              <Field label="IP Address (CIDR)" hint={!ipErr ? "e.g. 192.168.1.1/24" : undefined} error={ipErr}>
                <input
                  type="text"
                  value={ip}
                  onChange={(e) => handleIpChange(e.target.value)}
                  placeholder="192.168.1.1/24"
                  style={inputStyle(!!ipErr)}
                />
              </Field>
              <Field label="Default Gateway" hint="Optional">
                <input
                  type="text"
                  value={gateway}
                  onChange={(e) => setGateway(e.target.value)}
                  placeholder="192.168.1.254"
                  style={inputStyle()}
                />
              </Field>
            </>
          )}
        </div>

        {/* Footer */}
        <div style={{ display: "flex", gap: 8, padding: "0 16px 16px" }}>
          <button
            onClick={handleSave}
            disabled={!!(isHost && ip && ipErr)}
            style={{
              flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
              padding: "7px 0", borderRadius: 6, fontSize: 12, fontFamily: "monospace", fontWeight: 700,
              color: P.green, background: "rgba(166,227,161,0.1)", border: `1px solid rgba(166,227,161,0.3)`,
              cursor: "pointer", opacity: (isHost && ip && ipErr) ? 0.4 : 1,
            }}
          >
            <CheckCircle2 size={12} />
            Save
          </button>
          <button
            onClick={onClose}
            style={{
              padding: "7px 16px", borderRadius: 6, fontSize: 12, fontFamily: "monospace",
              color: P.muted, background: "transparent", border: `1px solid ${P.border}`, cursor: "pointer",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = P.label; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = P.muted; }}
          >
            Skip
          </button>
        </div>
      </div>
    </div>
  );
}

function inputStyle(hasError = false): React.CSSProperties {
  return {
    width: "100%", padding: "7px 10px", borderRadius: 5, fontSize: 12,
    fontFamily: "monospace", color: "#cdd6f4", outline: "none",
    background: "#0d1b2a",
    border: `1px solid ${hasError ? "#e94560" : "#0f3460"}`,
    boxSizing: "border-box",
  };
}

function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "#7c7f93" }}>
        {label}
      </label>
      {children}
      {error && <span style={{ fontSize: 10, color: "#e94560", fontFamily: "monospace" }}>{error}</span>}
      {hint && !error && <span style={{ fontSize: 10, color: "#7c7f93", fontFamily: "monospace" }}>{hint}</span>}
    </div>
  );
}
