"use client";

/**
 * AuthShell — animated login/register wrapper.
 *
 * Background: animated network topology with floating nodes and
 * connecting lines that pulse — evoking the product's core concept.
 * Card animates in with a smooth fade+slide on mount.
 */

import { useEffect, useRef } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { Network } from "lucide-react";

// ── Animated network canvas background ───────────────────────────────────────

interface Node {
  x: number; y: number;
  vx: number; vy: number;
  r: number;
}

function NetworkCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Create nodes
    const COUNT = 28;
    const nodes: Node[] = [];
    const resize = () => {
      canvas.width  = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener("resize", resize);

    for (let i = 0; i < COUNT; i++) {
      nodes.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        r: Math.random() * 2.5 + 1.5,
      });
    }

    const LINK_DIST = 160;

    function draw() {
      if (!ctx || !canvas) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Update positions
      for (const n of nodes) {
        n.x += n.vx;
        n.y += n.vy;
        if (n.x < 0 || n.x > canvas.width)  n.vx *= -1;
        if (n.y < 0 || n.y > canvas.height) n.vy *= -1;
      }

      // Draw links
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < LINK_DIST) {
            const alpha = (1 - dist / LINK_DIST) * 0.25;
            ctx.beginPath();
            ctx.strokeStyle = `rgba(88,166,255,${alpha})`;
            ctx.lineWidth = 1;
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      // Draw nodes
      for (const n of nodes) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(88,166,255,0.5)";
        ctx.fill();
      }

      rafRef.current = requestAnimationFrame(draw);
    }

    draw();
    return () => {
      window.removeEventListener("resize", resize);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none"
      aria-hidden="true"
    />
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

interface AuthShellProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function AuthShell({ title, subtitle, children, footer }: AuthShellProps) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#0a0d14] px-4 py-12 overflow-hidden">
      {/* Animated network background */}
      <NetworkCanvas />

      {/* Radial glow behind card */}
      <div
        className="fixed inset-0 pointer-events-none"
        aria-hidden="true"
        style={{
          background:
            "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(29,53,88,0.35) 0%, transparent 70%)",
        }}
      />

      {/* Logo */}
      <motion.div
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
      >
        <Link
          href="/"
          className="flex items-center gap-2.5 mb-8 font-semibold text-[#e6edf3] no-underline"
        >
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center"
            style={{
              background: "rgba(29,53,88,0.9)",
              border: "1px solid #58a6ff",
              boxShadow: "0 0 12px rgba(88,166,255,0.3)",
            }}
          >
            <Network size={17} className="text-[#58a6ff]" aria-hidden="true" />
          </div>
          <span className="text-base">
            NetLab<span className="text-[#58a6ff]">Academy</span>
          </span>
        </Link>
      </motion.div>

      {/* Card */}
      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-sm relative z-10"
        style={{
          background: "rgba(22,27,34,0.85)",
          backdropFilter: "blur(16px)",
          border: "1px solid rgba(48,54,61,0.8)",
          borderRadius: "14px",
          padding: "28px",
          boxShadow: "0 24px 64px rgba(0,0,0,0.5), 0 0 0 1px rgba(88,166,255,0.06)",
        }}
      >
        {/* Accent bar top */}
        <div
          className="absolute top-0 left-8 right-8 h-px"
          style={{
            background:
              "linear-gradient(90deg, transparent, rgba(88,166,255,0.6), transparent)",
          }}
        />

        <div className="mb-6">
          <h1 className="text-[1.1rem] font-semibold text-[#e6edf3] leading-tight">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1.5 text-sm text-[#8b949e]">{subtitle}</p>
          )}
        </div>

        {children}
      </motion.div>

      {/* Footer */}
      {footer && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3, duration: 0.4 }}
          className="mt-5 text-sm text-[#8b949e] relative z-10"
        >
          {footer}
        </motion.div>
      )}
    </div>
  );
}
