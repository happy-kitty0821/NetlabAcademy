"use client";

/**
 * Auth route group layout.
 *
 * Redirects already-authenticated users from /login and /register to
 * /dashboard so they don't see the auth pages after logging in.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isLoading, isAuthenticated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [isLoading, isAuthenticated, router]);

  // If already authenticated, render nothing (redirect is in progress).
  if (!isLoading && isAuthenticated) {
    return null;
  }

  return <>{children}</>;
}
