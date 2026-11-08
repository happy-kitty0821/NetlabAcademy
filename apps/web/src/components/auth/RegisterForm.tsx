"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { register } from "@/lib/api";
import type { APIError } from "@/types/api";

export function RegisterForm() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    password: "",
    password_confirm: "",
  });

  function set(field: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
      setFieldErrors((prev) => ({ ...prev, [field]: "" }));
    };
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setGlobalError(null);
    setFieldErrors({});
    setLoading(true);

    try {
      await register(form);
      router.push("/login?registered=1");
    } catch (err) {
      const apiErr = err as APIError;
      if (apiErr?.error?.detail) {
        // Field-level errors from DRF
        const normalized: Record<string, string> = {};
        for (const [k, v] of Object.entries(apiErr.error.detail)) {
          normalized[k] = Array.isArray(v) ? v[0] : String(v);
        }
        setFieldErrors(normalized);
      } else {
        setGlobalError(apiErr?.error?.message ?? "Registration failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      {globalError && (
        <div
          role="alert"
          className="rounded-md px-3 py-2.5 text-sm bg-[#3a1a1a] border border-[var(--status-error)] text-[var(--status-error)]"
        >
          {globalError}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Input
          label="First name"
          id="first_name"
          type="text"
          autoComplete="given-name"
          value={form.first_name}
          onChange={set("first_name")}
          error={fieldErrors.first_name}
          required
        />
        <Input
          label="Last name"
          id="last_name"
          type="text"
          autoComplete="family-name"
          value={form.last_name}
          onChange={set("last_name")}
          error={fieldErrors.last_name}
          required
        />
      </div>

      <Input
        label="Email"
        id="email"
        type="email"
        autoComplete="email"
        value={form.email}
        onChange={set("email")}
        error={fieldErrors.email}
        placeholder="you@example.com"
        required
      />

      <Input
        label="Password"
        id="password"
        type="password"
        autoComplete="new-password"
        value={form.password}
        onChange={set("password")}
        error={fieldErrors.password}
        hint="Minimum 8 characters."
        required
      />

      <Input
        label="Confirm password"
        id="password_confirm"
        type="password"
        autoComplete="new-password"
        value={form.password_confirm}
        onChange={set("password_confirm")}
        error={fieldErrors.password_confirm}
        required
      />

      <Button type="submit" loading={loading} className="w-full mt-2">
        Create account
      </Button>
    </form>
  );
}
