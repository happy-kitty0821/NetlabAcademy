/**
 * Administrator user-management client for /api/v1/users/.
 *
 * Every endpoint requires an administrator; the API returns 403 otherwise.
 */

import { apiFetch } from "./api";
import type {
  AccountStatus,
  AdminUser,
  APIError,
  PaginatedResponse,
  Role,
} from "@/types/api";

export interface UserFilters {
  search?: string;
  role?: Role | "";
  status?: AccountStatus | "";
  page?: number;
}

export async function listUsers(filters: UserFilters = {}): Promise<PaginatedResponse<AdminUser>> {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.role) params.set("role", filters.role);
  if (filters.status) params.set("status", filters.status);
  if (filters.page && filters.page > 1) params.set("page", String(filters.page));
  const query = params.toString();
  return apiFetch<PaginatedResponse<AdminUser>>(`/users/${query ? `?${query}` : ""}`);
}

export async function updateUser(
  id: string,
  changes: Partial<Pick<AdminUser, "first_name" | "last_name" | "role" | "status">>,
): Promise<AdminUser> {
  return apiFetch<AdminUser>(`/users/${id}/`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export async function createUser(data: {
  email: string;
  first_name: string;
  last_name: string;
  role: Role;
  password: string;
}): Promise<AdminUser> {
  return apiFetch<AdminUser>("/users/", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

/** Human-readable message from an API error (field errors included). */
export function errorText(err: unknown): string {
  const body = err as Partial<APIError> | undefined;
  const error = body?.error;
  if (!error) return "Something went wrong. Is the API server running?";
  if (error.detail) {
    const messages = Object.values(error.detail).flat().map(String);
    if (messages.length) return messages.join(" ");
  }
  return error.message;
}

/** Field → first message, for showing errors next to form inputs. */
export function fieldErrors(err: unknown): Record<string, string> {
  const detail = (err as Partial<APIError> | undefined)?.error?.detail ?? {};
  return Object.fromEntries(
    Object.entries(detail).map(([field, msgs]) => [field, String([msgs].flat()[0])]),
  );
}
