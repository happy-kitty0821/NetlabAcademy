import { clsx, type ClassValue } from "clsx";

/** Merge Tailwind class strings conditionally. */
export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}

/** Format a UTC ISO date string for display. */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** Capitalise the first letter of a string. */
export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
