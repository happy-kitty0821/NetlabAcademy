"use client";

/**
 * DeviceTerminal
 * ──────────────
 * xterm.js terminal connected to the simulation CLI API.
 *
 * Features:
 *  - Tab completion (sends to API, replaces input if changed)
 *  - ? inline help (sends to API, displays help text, keeps input)
 *  - Command history (Up/Down arrow keys)
 *  - Ctrl+C clears the current input line
 *  - Cisco-style welcome banner on open
 *  - Coloured output: prompt in cyan, errors in red, success in green
 *  - Backspace, arrow keys for line editing
 */

import { useEffect, useRef, useState, useCallback } from "react";
import type { TopologyNode } from "@/lib/simulation-api";
import {
  sendCLICommand,
  completeCLICommand,
  getCLIHelp,
} from "@/lib/cli-api";
import { X } from "lucide-react";

// ── ANSI colours ────────────────────────────────────────────────────────────────

const C = {
  reset:   "\x1b[0m",
  cyan:    "\x1b[36m",
  green:   "\x1b[32m",
  red:     "\x1b[31m",
  yellow:  "\x1b[33m",
  bold:    "\x1b[1m",
  gray:    "\x1b[90m",
  dim:     "\x1b[2m",
};

function colorPrompt(prompt: string) {
  return `${C.bold}${C.cyan}${prompt}${C.reset} `;
}

function colorOutput(text: string): string {
  if (!text) return text;
  const lines = text.split("\n").map((line) => {
    if (line.trim().startsWith("% Ambiguous")) return `${C.yellow}${line}${C.reset}`;
    if (line.trim().startsWith("% Invalid")) return `${C.red}${line}${C.reset}`;
    if (line.trim().startsWith("% ")) return `${C.red}${line}${C.reset}`;
    if (line.includes("Success rate is 100")) return `${C.green}${line}${C.reset}`;
    if (line.includes("Success rate is 0")) return `${C.red}${line}${C.reset}`;
    if (line.match(/^[!.]+$/)) {
      return line
        .split("")
        .map((ch) => (ch === "!" ? `${C.green}!${C.reset}` : `${C.red}.${C.reset}`))
        .join("");
    }
    // Help lines: keyword + description
    if (line.match(/^\s{2}\S/) && line.includes("  ")) {
      // Don't colour general help lines — leave them default
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

  // Mutable state stored in refs so the key handler closure can access them
  const promptRef = useRef(`${device.hostname ?? device.id}>`);
  const inputRef = useRef<string>("");
  const historyRef = useRef<string[]>([]);
  const histIdxRef = useRef<number>(-1);
  const loadingRef = useRef<boolean>(false);

  // Also keep prompt in React state for the render side
  const [, setPromptState] = useState(promptRef.current);

  // ── Write helpers ─────────────────────────────────────────────────────────

  const write = useCallback((text: string) => {
    // xterm.js requires \r\n for line breaks; \n alone causes a staircase effect
    termRef.current?.write(text.replace(/\n/g, "\r\n"));
  }, []);

  const writeLine = useCallback((text: string) => {
    termRef.current?.write(text.replace(/\n/g, "\r\n") + "\r\n");
  }, []);

  const redrawLine = useCallback(() => {
    const term = termRef.current;
    if (!term) return;
    term.write("\r\x1b[K");  // CR + clear line
    term.write(colorPrompt(promptRef.current));
    term.write(inputRef.current);
  }, []);

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
        write(colorPrompt(promptRef.current));
        return;
      }

      loadingRef.current = true;
      try {
        const res = await sendCLICommand(sessionId, device.id, trimmed);
        if (res.output) {
          writeLine(colorOutput(res.output));
        }
        promptRef.current = res.prompt;
        setPromptState(res.prompt);
        write(colorPrompt(promptRef.current));
      } catch {
        writeLine(`${C.red}% Connection error — is the simulation server running?${C.reset}`);
        write(colorPrompt(promptRef.current));
      } finally {
        loadingRef.current = false;
      }
    },
    [device.id, sessionId, write, writeLine],
  );

  // ── Tab completion ──────────────────────────────────────────────────────────

  const doTabComplete = useCallback(async () => {
    if (loadingRef.current) return;
    const partial = inputRef.current;
    if (!partial.trim()) return;

    loadingRef.current = true;
    try {
      const res = await completeCLICommand(sessionId, device.id, partial);
      if (res.completed && res.completed !== partial) {
        // Replace the current input with the completed version
        inputRef.current = res.completed + " ";
        redrawLine();
      }
    } catch {
      // Silent — tab on error does nothing (IOS behaviour)
    } finally {
      loadingRef.current = false;
    }
  }, [sessionId, device.id, redrawLine]);

  // ── ? help ─────────────────────────────────────────────────────────────────

  const doHelp = useCallback(async () => {
    if (loadingRef.current) return;
    const partial = inputRef.current;

    loadingRef.current = true;
    try {
      const res = await getCLIHelp(sessionId, device.id, partial);
      // Print the help text on a new line, then re-display the prompt + input
      write("\r\n");
      if (res.help) {
        writeLine(colorOutput(res.help));
      }
      write(colorPrompt(promptRef.current));
      write(inputRef.current);
    } catch {
      write("\r\n");
      write(colorPrompt(promptRef.current));
      write(inputRef.current);
    } finally {
      loadingRef.current = false;
    }
  }, [sessionId, device.id, write, writeLine]);

  // ── Initialise xterm.js ───────────────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current) return;

    let term: import("@xterm/xterm").Terminal;

    (async () => {
      const { Terminal } = await import("@xterm/xterm");
      const { FitAddon } = await import("@xterm/addon-fit");

      term = new Terminal({
        fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
        fontSize: 13,
        lineHeight: 1.4,
        cursorBlink: true,
        cursorStyle: "block",
        theme: {
          background: "#010409",
          foreground: "#e6edf3",
          cursor: "#58a6ff",
          selectionBackground: "#1d3558",
          black: "#010409",
          brightBlack: "#484f58",
          cyan: "#39c5cf",
          brightCyan: "#58a6ff",
          green: "#3fb950",
          brightGreen: "#26a641",
          red: "#f85149",
          brightRed: "#da3633",
          white: "#e6edf3",
          brightWhite: "#ffffff",
          yellow: "#d29922",
        },
        scrollback: 1000,
      });

      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(containerRef.current!);
      fit.fit();

      termRef.current = term;

      // Welcome banner
      writeLine(`${C.bold}${C.cyan}NetLab Academy — Educational Network Simulator${C.reset}`);
      writeLine(`${C.gray}Connected to: ${device.hostname ?? device.id} (${device.model})${C.reset}`);
      writeLine(`${C.gray}Type ? for available commands. Tab to complete.${C.reset}`);
      writeLine("");
      write(colorPrompt(promptRef.current));

      // ── Key handler ─────────────────────────────────────────────────────────

      term.onKey(({ key, domEvent }) => {
        const ev = domEvent;

        // Enter — submit command
        if (ev.key === "Enter") {
          submitCommand(inputRef.current);
          return;
        }

        // Backspace
        if (ev.key === "Backspace") {
          if (inputRef.current.length > 0) {
            inputRef.current = inputRef.current.slice(0, -1);
            term.write("\b \b");
          }
          return;
        }

        // Tab — tab completion
        if (ev.key === "Tab") {
          ev.preventDefault();
          doTabComplete();
          return;
        }

        // ? — inline help (only when ? is the last character on the line)
        if (key === "?" && !ev.ctrlKey && !ev.altKey) {
          // Echo the ? then trigger help
          inputRef.current += "?";
          term.write("?");
          doHelp();
          return;
        }

        // Arrow Up — history previous
        if (ev.key === "ArrowUp") {
          const hist = historyRef.current;
          if (histIdxRef.current < hist.length - 1) {
            histIdxRef.current++;
            inputRef.current = hist[histIdxRef.current];
            redrawLine();
          }
          return;
        }

        // Arrow Down — history next
        if (ev.key === "ArrowDown") {
          if (histIdxRef.current > 0) {
            histIdxRef.current--;
            inputRef.current = historyRef.current[histIdxRef.current];
          } else {
            histIdxRef.current = -1;
            inputRef.current = "";
          }
          redrawLine();
          return;
        }

        // Ctrl+C — clear current line
        if (ev.ctrlKey && ev.key === "c") {
          inputRef.current = "";
          write("^C\r\n");
          write(colorPrompt(promptRef.current));
          return;
        }

        // Ctrl+Z — same as 'end'
        if (ev.ctrlKey && ev.key === "z") {
          inputRef.current = "";
          write("^Z\r\n");
          submitCommand("end");
          return;
        }

        // Printable characters
        if (key && key.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {
          // Remove trailing ? if present (user might have triggered help then continues typing)
          inputRef.current = inputRef.current.replace(/\?$/, "");
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
      <div ref={containerRef} style={{ height: 340, padding: "4px 2px" }} />
    </div>
  );
}
