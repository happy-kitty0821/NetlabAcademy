"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Eye, EyeOff, Lock, Mail } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import type { APIError } from "@/types/api";

const fieldClass =
  "w-full h-10 pl-9 pr-3 text-sm rounded-md bg-[var(--surface-raised)] text-[var(--text-primary)] " +
  "border border-[var(--surface-border)] placeholder:text-[var(--text-muted)] " +
  "transition-[border-color,box-shadow] duration-150 " +
  "focus:outline-none focus:border-[var(--accent-primary)] focus:shadow-[0_0_0_3px_rgba(9,105,218,0.15)]";

const labelClass = "block mb-1.5 text-sm font-medium text-[var(--text-primary)]";

export function LoginForm() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      await login(email.trim(), password);
      router.push("/dashboard");
    } catch (err) {
      const apiErr = err as APIError;
      setError(
        apiErr?.error?.code === "authentication_required" || apiErr?.error?.message
          ? "Incorrect email or password, or the account is not active."
          : "Could not reach the server. Try again in a moment.",
      );
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      {error && (
        <div
          role="alert"
          className="auth-alert rounded-md border border-[#ffcecb] bg-[#ffebe9] px-3 py-2.5 text-sm text-[var(--status-error)]"
        >
          {error}
        </div>
      )}

      <div>
        <label htmlFor="email" className={labelClass}>Email</label>
        <div className="relative">
          <Mail size={15} aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            id="email" type="email" autoComplete="email" inputMode="email" required
            value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com" className={fieldClass}
          />
        </div>
      </div>

      <div>
        <label htmlFor="password" className={labelClass}>Password</label>
        <div className="relative">
          <Lock size={15} aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)}
            className={fieldClass + " pr-10"}
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            aria-pressed={showPassword}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1.5 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
          </button>
        </div>
        <p className="mt-1.5 text-xs text-[var(--text-muted)]">
          Forgot your password? Ask an administrator to reset it.
        </p>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="group w-full h-10 inline-flex items-center justify-center gap-2 rounded-md text-sm font-semibold text-white
          bg-[var(--accent-primary)] hover:bg-[var(--accent-strong)] active:translate-y-px
          transition-[background-color,transform] duration-150 disabled:opacity-70 disabled:cursor-wait"
      >
        {loading ? (
          <>
            <span aria-hidden="true" className="w-3.5 h-3.5 border-2 border-white/80 border-t-transparent rounded-full animate-spin" />
            Signing in…
          </>
        ) : (
          <>
            Sign in
            <ArrowRight size={15} aria-hidden="true" className="transition-transform duration-150 group-hover:translate-x-0.5" />
          </>
        )}
      </button>
    </form>
  );
}
