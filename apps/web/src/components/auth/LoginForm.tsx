"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { login, setTokens } from "@/lib/api";
import type { APIError } from "@/types/api";

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const tokens = await login(email, password);
      setTokens(tokens);
      router.push("/dashboard");
    } catch (err) {
      const apiErr = err as APIError;
      setError(
        apiErr?.error?.message ?? "Login failed. Check your credentials."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      {error && (
        <div
          role="alert"
          className="rounded-md px-3 py-2.5 text-sm bg-[#3a1a1a] border border-[var(--status-error)] text-[var(--status-error)]"
        >
          {error}
        </div>
      )}

      <Input
        label="Email"
        id="email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        required
      />

      <div className="flex flex-col gap-1">
        <Input
          label="Password"
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
          required
        />
        <div className="flex justify-end">
          <Link
            href="/forgot-password"
            className="text-xs text-[var(--text-secondary)] hover:text-[var(--accent-primary)]"
          >
            Forgot password?
          </Link>
        </div>
      </div>

      <Button type="submit" loading={loading} className="w-full mt-2">
        Sign in
      </Button>
    </form>
  );
}
