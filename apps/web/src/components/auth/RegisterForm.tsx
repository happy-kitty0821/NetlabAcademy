"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/lib/auth-context";
import type { APIError } from "@/types/api";
import { ArrowRight } from "lucide-react";

const item = {
  hidden: { opacity: 0, x: -12 },
  show:   { opacity: 1, x: 0 },
};

export function RegisterForm() {
  const router = useRouter();
  const { register } = useAuth();
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
      router.push("/dashboard");
    } catch (err) {
      const apiErr = err as APIError;
      if (apiErr?.error?.detail) {
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
    <motion.form
      onSubmit={handleSubmit}
      noValidate
      className="flex flex-col gap-3.5"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }}
      initial="hidden"
      animate="show"
    >
      {globalError && (
        <motion.div
          role="alert"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="rounded-lg px-3 py-2.5 text-sm bg-[rgba(248,81,73,0.1)] border border-[#f85149] text-[#f85149]"
        >
          {globalError}
        </motion.div>
      )}

      <motion.div variants={item} className="grid grid-cols-2 gap-3">
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
      </motion.div>

      <motion.div variants={item}>
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
      </motion.div>

      <motion.div variants={item}>
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
      </motion.div>

      <motion.div variants={item}>
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
      </motion.div>

      <motion.div variants={item}>
        <Button type="submit" loading={loading} className="w-full mt-1 group">
          Create account
          <ArrowRight
            size={14}
            className="transition-transform group-hover:translate-x-0.5"
            aria-hidden="true"
          />
        </Button>
      </motion.div>
    </motion.form>
  );
}
