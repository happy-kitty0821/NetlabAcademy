"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/lib/auth-context";
import type { APIError } from "@/types/api";
import { Lock, Mail, ArrowRight } from "lucide-react";

export function LoginForm() {
  const router = useRouter();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err) {
      const apiErr = err as APIError;
      setError(apiErr?.error?.message ?? "Login failed. Check your credentials.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      {error && (
        <div
          role="alert"
          className="rounded-lg px-3 py-2.5 text-sm bg-[rgba(248,81,73,0.1)] border border-[#f85149] text-[#f85149]"
        >
          {error}
        </div>
      )}

      <div className="relative" style={{ animation: "fadeInLeft 0.3s ease-out" }}>
        <Mail
          size={15}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-[#484f58] pointer-events-none z-10"
          aria-hidden="true"
        />
        <Input
          label="Email"
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          required
          className="pl-9"
        />
      </div>

      <div className="flex flex-col gap-1 relative" style={{ animation: "fadeInLeft 0.4s ease-out" }}>
        <Lock
          size={15}
          className="absolute left-3 top-[2.1rem] text-[#484f58] pointer-events-none z-10"
          aria-hidden="true"
        />
        <Input
          label="Password"
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
          required
          className="pl-9"
        />
        <div className="flex justify-end">
          <Link
            href="/forgot-password"
            className="text-xs text-[#8b949e] hover:text-[#58a6ff] transition-colors"
          >
            Forgot password?
          </Link>
        </div>
      </div>

      <div style={{ animation: "fadeInLeft 0.5s ease-out" }}>
        <Button type="submit" loading={loading} className="w-full mt-1 group">
          Sign in
          <ArrowRight
            size={14}
            className="transition-transform group-hover:translate-x-0.5"
            aria-hidden="true"
          />
        </Button>
      </div>
    </form>
  );
}
