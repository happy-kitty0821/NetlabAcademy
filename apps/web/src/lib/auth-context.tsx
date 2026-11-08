"use client";

/**
 * Auth context — the single source of truth for the authenticated user
 * on the client side.
 *
 * Lifecycle:
 *   1. On mount, checks localStorage for an existing access token.
 *   2. If a token exists, calls GET /auth/me/ to fetch the user object.
 *   3. While checking, `isLoading` is true — callers should render a
 *      loading state rather than redirecting (avoids auth-check flash).
 *   4. If the token is invalid/expired, the user is set to null and
 *      tokens are cleared.
 *
 * Security note: the frontend guard is UX only. The real authorization
 * boundary is the Django API — every endpoint validates the JWT server-side.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  apiFetch,
  clearTokens,
  getAccessToken,
  login as apiLogin,
  register as apiRegister,
  setTokens,
} from "./api";
import type { User } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: {
    email: string;
    first_name: string;
    last_name: string;
    password: string;
    password_confirm: string;
  }) => Promise<void>;
  logout: () => void;
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isLoading: true, // start loading until the initial token check completes
  });

  // ── Initial auth check ─────────────────────────────────────────────────────
  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      setState({ user: null, isLoading: false });
      return;
    }

    // Token exists — verify it by fetching the user.
    apiFetch<User>("/auth/me/")
      .then((user) => {
        setState({ user, isLoading: false });
      })
      .catch(() => {
        // Token is invalid or expired — clean up.
        clearTokens();
        setState({ user: null, isLoading: false });
      });
  }, []);

  // ── Actions ─────────────────────────────────────────────────────────────────

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await apiLogin(email, password);
    setTokens(tokens);
    // Fetch the user object so the context has it immediately.
    const user = await apiFetch<User>("/auth/me/");
    setState({ user, isLoading: false });
  }, []);

  const register = useCallback(
    async (data: {
      email: string;
      first_name: string;
      last_name: string;
      password: string;
      password_confirm: string;
    }) => {
      // Registration returns the user object but does not auto-login.
      // We auto-login so the user lands on the dashboard without a second step.
      await apiRegister(data);
      const tokens = await apiLogin(data.email, data.password);
      setTokens(tokens);
      const user = await apiFetch<User>("/auth/me/");
      setState({ user, isLoading: false });
    },
    []
  );

  const logout = useCallback(() => {
    clearTokens();
    setState({ user: null, isLoading: false });
  }, []);

  const value: AuthContextValue = {
    user: state.user,
    isLoading: state.isLoading,
    isAuthenticated: state.user !== null,
    login,
    register,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
