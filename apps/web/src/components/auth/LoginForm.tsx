"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { useAuth } from "@/lib/auth-context";
import type { APIError } from "@/types/api";
import { Lock, Mail, ArrowRight } from "lucide-react";

const item = {
  hidden: { opacity: 0, x: -12 },
  show:   { opacity: 1, x: 0 },
};

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
    <motion.form
      onSubmit={handleSubmit}
      noValidate
      className="flex flex-col gap-4"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.07 } } }}
      initial="hidden"
      animate="show"
    >
      {error && (
        <motion.div
          role="alert"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="rounded-lg px-3 py-2.5 text-sm bg-[rgba(248,81,73,0.1)] border border-[#f85149] text-[#f85149]"
        >
          {error}
        </motion.div>
      )}

      <motion.div variants={item} className="relative">
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
      </motion.div>

      <motion.div variants={item} className="flex flex-col gap-1 relative">
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
      </motion.div>

      <motion.div variants={item}>
        <Button type="submit" loading={loading} className="w-full mt-1 group">
          Sign in
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
