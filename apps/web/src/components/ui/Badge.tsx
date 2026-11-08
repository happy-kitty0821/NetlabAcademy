import { cn } from "@/lib/utils";

type BadgeVariant = "default" | "success" | "warning" | "error" | "info" | "admin" | "instructor" | "student";

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  default:     "bg-[var(--surface-overlay)] text-[var(--text-secondary)] border-[var(--surface-border)]",
  success:     "bg-[#1a3a1f] text-[var(--status-success)] border-[#2a5a2f]",
  warning:     "bg-[#3a2a10] text-[var(--status-warning)] border-[#5a4010]",
  error:       "bg-[#3a1a1a] text-[var(--status-error)] border-[#5a2a2a]",
  info:        "bg-[var(--accent-subtle)] text-[var(--accent-primary)] border-[#2d4f7a]",
  admin:       "bg-[#2d1f4a] text-[#bf96ff] border-[#4a3270]",
  instructor:  "bg-[var(--accent-subtle)] text-[var(--accent-primary)] border-[#1f4a7a]",
  student:     "bg-[var(--surface-overlay)] text-[var(--text-secondary)] border-[var(--surface-border)]",
};

export function Badge({ variant = "default", children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2 py-0.5",
        "text-xs font-medium rounded",
        "border",
        variantStyles[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
