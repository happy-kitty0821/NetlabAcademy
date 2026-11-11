/**
 * Thin API client for the NetLab Academy backend.
 *
 * All requests go through `apiFetch`, which:
 * - Prefixes the base URL.
 * - Injects the Bearer token from localStorage.
 * - Throws a typed APIError on non-2xx responses.
 *
 * No third-party HTTP library is introduced here — this can be replaced
 * with a generated client once the OpenAPI spec is published.
 */

import type { APIError, AuthTokens, User } from "@/types/api";

// Always relative in production — requests go through the Next.js proxy
// rewrite (/api/* → http://backend/api/*).  NEXT_PUBLIC_API_URL can override
// this for local dev if needed, but the fallback must stay relative so the
// deployed build never hard-codes localhost.
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

// ── Token storage ────────────────────────────────────────────────────────────

const TOKEN_KEY = "netlab_access";
const REFRESH_KEY = "netlab_refresh";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setTokens(tokens: AuthTokens): void {
  localStorage.setItem(TOKEN_KEY, tokens.access);
  localStorage.setItem(REFRESH_KEY, tokens.refresh);
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

// ── Core fetch ───────────────────────────────────────────────────────────────

interface FetchOptions extends RequestInit {
  authenticated?: boolean;
}

export async function apiFetch<T>(
  path: string,
  options: FetchOptions = {}
): Promise<T> {
  const { authenticated = true, headers: extraHeaders, ...rest } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(extraHeaders as Record<string, string> | undefined),
  };

  if (authenticated) {
    const token = getAccessToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    ...rest,
    headers,
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => ({
      error: { code: "unknown", message: response.statusText },
    }))) as APIError;
    throw errorBody;
  }

  // 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

// ── Auth endpoints ───────────────────────────────────────────────────────────

export async function login(
  email: string,
  password: string
): Promise<AuthTokens> {
  return apiFetch<AuthTokens>("/auth/token/", {
    method: "POST",
    body: JSON.stringify({ email, password }),
    authenticated: false,
  });
}

export async function register(data: {
  email: string;
  first_name: string;
  last_name: string;
  password: string;
  password_confirm: string;
}): Promise<User> {
  return apiFetch<User>("/auth/register/", {
    method: "POST",
    body: JSON.stringify(data),
    authenticated: false,
  });
}

export async function getMe(): Promise<User> {
  return apiFetch<User>("/auth/me/");
}
