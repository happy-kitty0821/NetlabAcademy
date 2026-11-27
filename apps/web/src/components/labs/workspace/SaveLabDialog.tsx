"use client";

/**
 * Name/description dialog for saving the workspace as a lab.
 * Enter saves, Escape cancels. Styled like NodeConfigPopup.
 */

import { useEffect, useRef, useState } from "react";
import { Save, X } from "lucide-react";

export function SaveLabDialog({
  title, initialName = "", initialDescription = "", saving = false, error,
  onSubmit, onClose,
}: {
  title: string;
  initialName?: string;
  initialDescription?: string;
  saving?: boolean;
  error?: string | null;
  onSubmit: (name: string, description: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);
  const nameRef = useRef<HTMLInputElement>(null);
  const trimmed = name.trim();

  useEffect(() => { nameRef.current?.select(); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (trimmed && !saving) onSubmit(trimmed, description.trim());
  };

  const field: React.CSSProperties = {
    width: "100%", padding: "7px 9px", fontSize: 13, borderRadius: 6,
    border: "1px solid #d0d7de", color: "#1f2328", background: "#ffffff", outline: "none",
  };
  const label: React.CSSProperties = {
    fontSize: 11, fontWeight: 600, color: "#656d76", textTransform: "uppercase", letterSpacing: 0.4,
  };

  return (
    <div
      role="presentation"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ position: "fixed", inset: 0, background: "rgba(31,35,40,0.35)", zIndex: 50,
        display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <form
        role="dialog" aria-modal="true" aria-labelledby="save-lab-title" onSubmit={submit}
        style={{ width: 360, background: "#ffffff", border: "1px solid #d0d7de", borderRadius: 10,
          boxShadow: "0 8px 24px rgba(140,149,159,0.3)", padding: 18, display: "flex",
          flexDirection: "column", gap: 12 }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h2 id="save-lab-title" style={{ fontSize: 14, fontWeight: 700, color: "#1f2328" }}>{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close"
            style={{ background: "none", border: "none", cursor: "pointer", color: "#656d76" }}>
            <X size={14} />
          </button>
        </div>

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={label}>Name</span>
          <input ref={nameRef} value={name} maxLength={200} required
            onChange={(e) => setName(e.target.value)} placeholder="e.g. VLAN trunking practice" style={field} />
        </label>

        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={label}>Description <span style={{ textTransform: "none", fontWeight: 400 }}>(optional)</span></span>
          <textarea value={description} rows={3} onChange={(e) => setDescription(e.target.value)}
            placeholder="What is this lab for?" style={{ ...field, resize: "vertical" }} />
        </label>

        {error && <p role="alert" style={{ fontSize: 12, color: "#d1242f" }}>{error}</p>}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button type="button" onClick={onClose}
            style={{ padding: "6px 12px", fontSize: 12, borderRadius: 6, border: "1px solid #d0d7de",
              background: "#f6f8fa", color: "#1f2328", cursor: "pointer" }}>
            Cancel
          </button>
          <button type="submit" disabled={!trimmed || saving}
            style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px", fontSize: 12,
              fontWeight: 600, borderRadius: 6, border: "1px solid #1a7f37", background: "#1f883d",
              color: "#ffffff", cursor: !trimmed || saving ? "not-allowed" : "pointer",
              opacity: !trimmed || saving ? 0.6 : 1 }}>
            <Save size={12} /> {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
