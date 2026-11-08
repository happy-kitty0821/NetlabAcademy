import type { Metadata } from "next";
import Link from "next/link";
import { AuthShell } from "@/components/auth/AuthShell";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata: Metadata = {
  title: "Sign in",
};

export default function LoginPage() {
  return (
    <AuthShell
      title="Sign in to NetLab Academy"
      subtitle="Access your courses, labs and exam results."
      footer={
        <>
          Don&apos;t have an account?{" "}
          <Link href="/register" className="text-[var(--accent-primary)] hover:underline">
            Register
          </Link>
        </>
      }
    >
      <LoginForm />
    </AuthShell>
  );
}
