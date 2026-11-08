import { Network } from "lucide-react";
import Link from "next/link";

interface AuthShellProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

/**
 * Wrapper for login / register / password-reset pages.
 *
 * Layout: centered card on a dark background with a subtle grid pattern
 * that evokes a topology canvas — intentional reference to the product.
 */
export function AuthShell({ title, subtitle, children, footer }: AuthShellProps) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--surface-base)] px-4 py-12">
      {/* Background topology grid — purely decorative */}
      <div
        className="fixed inset-0 pointer-events-none select-none opacity-[0.035]"
        aria-hidden="true"
        style={{
          backgroundImage: `
            linear-gradient(var(--surface-border) 1px, transparent 1px),
            linear-gradient(90deg, var(--surface-border) 1px, transparent 1px)
          `,
          backgroundSize: "48px 48px",
        }}
      />

      {/* Logo */}
      <Link
        href="/"
        className="flex items-center gap-2.5 mb-8 font-semibold text-[var(--text-primary)] no-underline"
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: "var(--accent-subtle)", border: "1px solid var(--accent-primary)" }}
        >
          <Network size={16} className="text-[var(--accent-primary)]" aria-hidden="true" />
        </div>
        <span>
          NetLab<span className="text-[var(--accent-primary)]">Academy</span>
        </span>
      </Link>

      {/* Card */}
      <div
        className="w-full max-w-sm rounded-xl border border-[var(--surface-border)] bg-[var(--surface-raised)] p-6 relative z-10"
      >
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              {subtitle}
            </p>
          )}
        </div>

        {children}
      </div>

      {/* Below-card links */}
      {footer && (
        <div className="mt-4 text-sm text-[var(--text-secondary)] relative z-10">
          {footer}
        </div>
      )}
    </div>
  );
}
