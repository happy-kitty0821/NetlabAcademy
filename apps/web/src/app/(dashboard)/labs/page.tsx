import type { Metadata } from "next";
import { FlaskConical } from "lucide-react";
import { Card, CardBody } from "@/components/ui/Card";

export const metadata: Metadata = { title: "Labs" };

export default function LabsPage() {
  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
          Labs
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Assigned and personal network topology labs.
        </p>
      </div>

      <Card>
        <CardBody>
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center"
              style={{ background: "var(--surface-overlay)" }}
              aria-hidden="true"
            >
              <FlaskConical size={20} className="text-[var(--status-success)]" />
            </div>
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">
                Lab workspace coming soon
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-1 max-w-xs">
                The topology editor, device CLI and simulation controls will
                appear here once the lab-lifecycle feature spec is complete.
                The simulator core (packages/simulator-core) is already
                implemented and tested.
              </p>
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
