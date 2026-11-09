import type { Metadata } from "next";
import { Card, CardBody } from "@/components/ui/Card";
import { Settings } from "lucide-react";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">Settings</h1>
      <Card>
        <CardBody>
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <div className="w-12 h-12 rounded-xl flex items-center justify-center" style={{ background: "var(--surface-overlay)" }} aria-hidden="true">
              <Settings size={20} className="text-[var(--accent-primary)]" />
            </div>
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">Settings coming soon</p>
              <p className="text-xs text-[var(--text-secondary)] mt-1 max-w-xs">
                Profile, timezone, notification preferences and account management will appear here.
              </p>
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
