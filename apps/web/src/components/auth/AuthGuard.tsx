"use client";

/**
 * Client-side route guard.
 *
 * Wraps authenticated page content. If the user is not authenticated
 * (and the initial auth check has completed), redirects to /login.
 * While the auth check is in progress, shows a loading spinner.
 *
 * This is a UX guard, not a security boundary. The Django API enforces
 * authorization on every request via JWT validation.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isLoading, isAuthenticated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  // While the initial token check is running, show a loading state
  // so we don't flash the login page for an already-authenticated user.
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-[var(--surface-base)]">
        <div
          className="inline-block w-5 h-5 border-2 border-[var(--accent-primary)] border-t-transparent rounded-full animate-spin"
          aria-label="Loading"
          role="status"
        />
      </div>
    );
  }

  if (!isAuthenticated) {
    // Redirect is in progress — render nothing to avoid flashing protected content.
    return null;
  }

  return <>{children}</>;
}
