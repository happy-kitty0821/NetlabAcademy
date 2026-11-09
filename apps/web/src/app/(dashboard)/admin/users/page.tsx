import type { Metadata } from "next";
import { Card, CardBody } from "@/components/ui/Card";
import { Users } from "lucide-react";

export const metadata: Metadata = { title: "User Management" };

export default function UsersPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-5">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">User Management</h1>
      <Card>
        <CardBody>
          <div className="flex flex-col items-center gap-3 py-12 text-center">
            <div className="w-12 h-12 rounded-xl flex items-center justify-center" style={{ background: "var(--surface-overlay)" }} aria-hidden="true">
              <Users size={20} className="text-[var(--accent-primary)]" />
            </div>
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">User management coming soon</p>
              <p className="text-xs text-[var(--text-secondary)] mt-1 max-w-xs">
                Invite, manage roles and account status for administrators, instructors and students.
                This will be available once the auth-rbac feature spec is complete.
              </p>
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
