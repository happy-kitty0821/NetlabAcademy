"use client";

/**
 * NodeConfigPopup — modal overlay for configuring a device.
 *
 * Opens automatically when a device is dropped onto the canvas.
 * Also opens on double-click when simulation is stopped.
 *
 * Fields:
 *  - Hostname (all devices)
 *  - IP Address / CIDR (hosts only)
 *  - Gateway (hosts only, optional)
 */

import { useState, useEffect, useRef } from "react";
import type { DeviceNode, DeviceNodeData } from "@/lib/deviceTypes";
import { X, CheckCircle2 } from "lucide-react";

interface NodeConfigPopupProps {
  node:    DeviceNode;
  onSave:  (id: string, patch: Partial<DeviceNodeData>) => void;
  onClose: () => void;
}

function validate(ip: string): string {
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

  const isHost    = node.data.model === "host";
  const hostnameRef = useRef<HTMLInputElement>(null);

  // Focus hostname on open
  useEffect(() => { hostnameRef.current?.focus(); }, []);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  function handleIpChange(v: string) {
    setIp(v);
    setIpErr(validate(v));
  }

  function handleSave() {
    if (isHost && ip && ipErr) return;
    onSave(node.id, {
      hostname: hostname.trim() || String(node.data.hostname),
      ip:       isHost ? (ip.trim() || undefined) : undefined,
      gateway:  isHost ? (gateway.trim() || undefined) : undefined,
    });
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleSave();
  }

  const modelLabel =
    node.data.model === "host"   ? "PC / Host" :
    node.data.model === "switch" ? "Switch"    :
    node.data.model === "router" ? "Router"    : "Device";

  return (
    /* Backdrop */
    <div
      className="absolute inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(1,4,9,0.7)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="rounded-xl border border-[#30363d] shadow-2xl"
        style={{ width: 320, background: "#161b22" }}
        onKeyDown={handleKeyDown}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#21262d]">
          <div>
            <div className="text-[13px] font-semibold text-[#e6edf3]">Configure device</div>
            <div className="text-[10px] font-mono text-[#484f58] mt-0.5">{modelLabel}</div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-[#484f58] hover:text-[#8b949e] hover:bg-[#21262d] transition-colors"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="p-4 space-y-3">
          {/* Hostname */}
          <Field label="Hostname">
            <input
              ref={hostnameRef}
              type="text"
              value={hostname}
              onChange={(e) => setHostname(e.target.value)}
              placeholder="SW1"
              className="w-full px-2.5 py-1.5 rounded text-[12px] font-mono text-[#e6edf3] outline-none focus:ring-1 focus:ring-[#58a6ff] transition-shadow"
              style={{ background: "#0d1117", border: "1px solid #30363d" }}
            />
          </Field>

          {/* IP (hosts only) */}
          {isHost && (
            <>
              <Field
                label="IP Address (CIDR)"
                hint="e.g. 192.168.1.1/24"
                error={ipErr}
              >
                <input
                  type="text"
                  value={ip}
                  onChange={(e) => handleIpChange(e.target.value)}
                  placeholder="192.168.1.1/24"
                  className="w-full px-2.5 py-1.5 rounded text-[12px] font-mono text-[#e6edf3] outline-none focus:ring-1 transition-shadow"
                  style={{
                    background:  "#0d1117",
                    border:      `1px solid ${ipErr ? "#f85149" : "#30363d"}`,
                  }}
                />
              </Field>

              <Field label="Default Gateway" hint="Optional — leave blank for same-subnet">
                <input
                  type="text"
                  value={gateway}
                  onChange={(e) => setGateway(e.target.value)}
                  placeholder="192.168.1.254"
                  className="w-full px-2.5 py-1.5 rounded text-[12px] font-mono text-[#e6edf3] outline-none focus:ring-1 focus:ring-[#58a6ff] transition-shadow"
                  style={{ background: "#0d1117", border: "1px solid #30363d" }}
                />
              </Field>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 px-4 pb-4">
          <button
            onClick={handleSave}
            disabled={!!(isHost && ip && ipErr)}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded text-[12px] font-semibold font-mono transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: "rgba(63,185,80,0.15)",
              border:     "1px solid rgba(63,185,80,0.35)",
              color:      "#3fb950",
            }}
          >
            <CheckCircle2 size={12} />
            Save
          </button>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded text-[12px] font-mono text-[#8b949e] hover:text-[#e6edf3] hover:bg-[#21262d] transition-colors"
            style={{ border: "1px solid #30363d" }}
          >
            Skip
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label, hint, error, children,
}: {
  label:    string;
  hint?:    string;
  error?:   string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="block text-[10px] font-semibold uppercase tracking-wider text-[#8b949e]">
        {label}
      </label>
      {children}
      {error  && <p className="text-[10px] text-[#f85149] font-mono">{error}</p>}
      {hint && !error && <p className="text-[10px] text-[#484f58] font-mono">{hint}</p>}
    </div>
  );
}
