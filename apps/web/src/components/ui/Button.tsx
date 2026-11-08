import { cn } from "@/lib/utils";
import { type ButtonHTMLAttributes, type AnchorHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

// Polymorphic: button or anchor
type ButtonAsButton = {
  as?: "button";
  href?: never;
} & ButtonHTMLAttributes<HTMLButtonElement>;

type ButtonAsAnchor = {
  as: "a";
  href: string;
} & AnchorHTMLAttributes<HTMLAnchorElement>;

type ButtonProps = (ButtonAsButton | ButtonAsAnchor) & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
};

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    "bg-[var(--accent-primary)] text-[var(--text-inverse)] hover:bg-[var(--accent-strong)] " +
    "font-semibold border border-transparent",
  secondary:
    "bg-transparent text-[var(--text-primary)] border border-[var(--surface-border)] " +
    "hover:bg-[var(--surface-overlay)] hover:border-[var(--accent-primary)]",
  ghost:
    "bg-transparent text-[var(--text-secondary)] border border-transparent " +
    "hover:text-[var(--text-primary)] hover:bg-[var(--surface-overlay)]",
  danger:
    "bg-transparent text-[var(--status-error)] border border-[var(--status-error)] " +
    "hover:bg-[var(--status-error)] hover:text-white",
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-xs rounded",
  md: "px-4 py-2 text-sm rounded-md",
  lg: "px-5 py-2.5 text-sm rounded-md",
};

const baseStyles = [
  "inline-flex items-center justify-center gap-2",
  "transition-colors duration-150",
  "cursor-pointer select-none no-underline",
  "disabled:opacity-50 disabled:cursor-not-allowed",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]",
].join(" ");

export function Button(props: ButtonProps) {
  const {
    as,
    variant = "primary",
    size = "md",
    loading,
    className,
    children,
    ...rest
  } = props;

  const classes = cn(
    baseStyles,
    variantStyles[variant],
    sizeStyles[size],
    className
  );

  const content = (
    <>
      {loading && (
        <span
          className="inline-block w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin"
          aria-hidden="true"
        />
      )}
      {children}
    </>
  );

  if (as === "a") {
    const { href, ...anchorRest } = rest as ButtonAsAnchor;
    return (
      <a href={href} className={classes} {...anchorRest}>
        {content}
      </a>
    );
  }

  const { disabled, ...btnRest } = rest as ButtonAsButton;
  return (
    <button
      disabled={disabled || loading}
      className={classes}
      {...btnRest}
    >
      {content}
    </button>
  );
}
