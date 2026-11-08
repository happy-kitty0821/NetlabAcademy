/**
 * Shared API response types.
 * These mirror the Django API contract defined in services/api/.
 */

export type Role = "admin" | "instructor" | "student";
export type AccountStatus = "invited" | "active" | "suspended" | "archived";

export interface UserProfile {
  timezone: string;
  bio: string;
  avatar: string | null;
}

export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  role: Role;
  status: AccountStatus;
  date_joined: string;
  profile: UserProfile | null;
}

export interface AuthTokens {
  access: string;
  refresh: string;
}

export interface APIError {
  error: {
    code: string;
    message: string;
    detail?: Record<string, string[]>;
  };
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
