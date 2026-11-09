"use client";

/**
 * DeviceTerminal
 * ──────────────
 * xterm.js-based terminal that connects to the simulation CLI API.
 *
 * Renders a dark Cisco-style terminal with the device hostname as the
 * window title. The user types commands; each Enter dispatches to
 * POST /api/v1/labs/simulations/<id>/cli/ and the response is written
 * back to the terminal with the new prompt.
 *
 * Features:
 *  - Command history (Up/Down arrow keys)
 *  - Local echo of typed characters
 *  - Ctrl+C clears the current input line (does NOT kill the session)
 *  - Cisco-style welcome banner on open
 *  - Coloured output: prompt in cyan, errors in red, success in green
 */

import { useEffect, useRef, useState, useCallback } from "react";
import type { TopologyNode } from "@/lib/simulation-api";
import { sendCLICommand } from "@/lib/cli-api";
import { X } from "lucide-react";

// ── ANSI colour helpers ────────────────────────────────────────────────────────

const C = {
  reset:   "\x1b[0m",
  cyan:    "\x1b[36m",
  green:   "\x1b[32m",
  red:     "\x1b[31m",
  yellow:  "\x1b[33m",
  bold:    "\x1b[1m",
  gray:    "\x1b[90m",
};

function colorPrompt(prompt: string) {
  return `${C.bold}${C.cyan}${prompt} ${C.reset}`;
}

function colorOutput(text: string): string {
  if (!text) return text;
  // Colour success/failure indicators
  const lines = text.split("\n").map((line) => {
    if (line.trim().startsWith("%")) return `${C.red}${line}${C.reset}`;
    if (line.includes("Success rate is 100")) return `${C.green}${line}${C.reset}`;
    if (line.includes("Success rate is 0")) return `${C.red}${line}${C.reset}`;
    if (line.match(/^[!.]+$/)) {
      return line
        .split("")
        .map((ch) => (ch === "!" ? `${C.green}!${C.reset}` : `${C.red}.${C.reset}`))
        .join("");
    }
    return line;
  });
  return lines.join("\n");
}

// ── Component ─────────────────────────────────────────────────────────────────

interface DeviceTerminalProps {
  sessionId: string;
  device: TopologyNode;
  onClose: () => void;
}

export function DeviceTerminal({
  sessionId,
  device,
  onClose,
}: DeviceTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<import("@xterm/xterm").Terminal | null>(null);
  const fitRef = useRef<import("@xterm/addon-fit").FitAddon | null>(null);

  const [prompt, setPrompt] = useState(`${device.hostname ?? device.id}>`);
  const inputRef = useRef<string>("");
  const historyRef = useRef<string[]>([]);
  const histIdxRef = useRef<number>(-1);
  const loadingRef = useRef<boolean>(false);

  // ── Write helpers ─────────────────────────────────────────────────────────

  const write = useCallback((text: string) => {
    termRef.current?.write(text);
  }, []);

  const writeLine = useCallback((text: string) => {
    termRef.current?.write(text + "\r\n");
  }, []);

  const clearLine = useCallback(() => {
    const term = termRef.current;
    if (!term) return;
    // Move to beginning of line, clear to end
    term.write("\r\x1b[K");
    term.write(colorPrompt(prompt));
    term.write(inputRef.current);
  }, [prompt]);

  // ── Submit command ────────────────────────────────────────────────────────

  const submitCommand = useCallback(
    async (cmd: string) => {
      if (loadingRef.current) return;
      const trimmed = cmd.trim();

      write("\r\n");

      if (trimmed) {
        historyRef.current.unshift(trimmed);
        if (historyRef.current.length > 50) historyRef.current.pop();
      }
      histIdxRef.current = -1;
      inputRef.current = "";

      if (!trimmed) {
        write(colorPrompt(prompt));
        return;
      }

      loadingRef.current = true;
      try {
        const res = await sendCLICommand(sessionId, device.id, trimmed);
        if (res.output) {
          writeLine(colorOutput(res.output));
        }
        setPrompt(res.prompt);
        write(colorPrompt(res.prompt));
      } catch {
        writeLine(`${C.red}% Connection error — is the simulation server running?${C.reset}`);
        write(colorPrompt(prompt));
      } finally {
        loadingRef.current = false;
      }
    },
    [device.id, prompt, sessionId, write, writeLine],
  );

  // ── Initialise xterm.js ───────────────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current) return;

    let term: import("@xterm/xterm").Terminal;
    let fit: import("@xterm/addon-fit").FitAddon;

    (async () => {
      const { Terminal }  = await import("@xterm/xterm");
      const { FitAddon }  = await import("@xterm/addon-fit");

      term = new Terminal({
        fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
        fontSize: 13,
        lineHeight: 1.4,
        cursorBlink: true,
        cursorStyle: "block",
        theme: {
          background: "#010409",
          foreground: "#e6edf3",
          cursor:     "#58a6ff",
          selectionBackground: "#1d3558",
          black:   "#010409",
          brightBlack: "#484f58",
          cyan:    "#39c5cf",
          brightCyan: "#58a6ff",
          green:   "#3fb950",
          brightGreen: "#26a641",
          red:     "#f85149",
          brightRed:   "#da3633",
          white:   "#e6edf3",
          brightWhite: "#ffffff",
        },
        scrollback: 1000,
      });

      fit = new FitAddon();
      term.loadAddon(fit);
      term.open(containerRef.current!);
      fit.fit();

      termRef.current = term;
      fitRef.current  = fit;

      // Welcome banner
      writeLine(`${C.bold}${C.cyan}NetLab Academy — Educational Network Simulator${C.reset}`);
      writeLine(`${C.gray}Connected to: ${device.hostname ?? device.id} (${device.model})${C.reset}`);
      writeLine(`${C.gray}Type ? for available commands.${C.reset}`);
      writeLine("");
      write(colorPrompt(prompt));

      // Key handler
      term.onKey(({ key, domEvent }) => {
        const ev = domEvent;

        if (ev.key === "Enter") {
          submitCommand(inputRef.current);
          return;
        }

        if (ev.key === "Backspace") {
          if (inputRef.current.length > 0) {
            inputRef.current = inputRef.current.slice(0, -1);
            term.write("\b \b");
          }
          return;
        }

        if (ev.key === "ArrowUp") {
          const hist = historyRef.current;
          if (histIdxRef.current < hist.length - 1) {
            histIdxRef.current++;
            inputRef.current = hist[histIdxRef.current];
            clearLine();
          }
          return;
        }

        if (ev.key === "ArrowDown") {
          if (histIdxRef.current > 0) {
            histIdxRef.current--;
            inputRef.current = historyRef.current[histIdxRef.current];
          } else {
            histIdxRef.current = -1;
            inputRef.current = "";
          }
          clearLine();
          return;
        }

        // Ctrl+C — clear current line
        if (ev.ctrlKey && ev.key === "c") {
          inputRef.current = "";
          write("^C\r\n");
          write(colorPrompt(prompt));
          return;
        }

        // Tab — minimal: just echo a tab char
        if (ev.key === "Tab") {
          ev.preventDefault();
          return;
        }

        // Printable characters
        if (key && key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
          inputRef.current += key;
          term.write(key);
        }
      });

      // Resize observer
      const ro = new ResizeObserver(() => fit.fit());
      ro.observe(containerRef.current!);
      return () => ro.disconnect();
    })();

    return () => {
      termRef.current?.dispose();
      termRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update prompt in write calls when it changes
  useEffect(() => {
    // Nothing — prompt state is read inside submitCommand via closure
  }, [prompt]);

  return (
    <div
      className="flex flex-col rounded-lg overflow-hidden border border-[#30363d]"
      style={{ background: "#010409" }}
    >
      {/* Title bar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#161b22] border-b border-[#30363d]">
        <div className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-full bg-[#f85149]" />
          <span className="w-3 h-3 rounded-full bg-[#d29922]" />
          <span className="w-3 h-3 rounded-full bg-[#3fb950]" />
          <span className="ml-2 text-xs font-mono text-[#8b949e]">
            {device.hostname ?? device.id} — {device.model}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-[#8b949e] hover:text-[#e6edf3] transition-colors"
          aria-label="Close terminal"
        >
          <X size={14} />
        </button>
      </div>
      {/* Terminal canvas */}
      <div ref={containerRef} style={{ height: 320, padding: "4px 2px" }} />
    </div>
  );
}
