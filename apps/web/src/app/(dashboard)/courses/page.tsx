import type { Metadata } from "next";
import { BookOpen } from "lucide-react";
import { Card, CardBody } from "@/components/ui/Card";

export const metadata: Metadata = { title: "Courses" };

export default function CoursesPage() {
  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">
          Courses
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          CCNA and CCNP learning paths, modules and assessments.
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
              <BookOpen size={20} className="text-[var(--accent-primary)]" />
            </div>
            <div>
              <p className="text-sm font-medium text-[var(--text-primary)]">
                Course catalogue coming soon
              </p>
              <p className="text-xs text-[var(--text-secondary)] mt-1 max-w-xs">
                This section is under active development. Courses, modules and
                question banks will appear here once the learning management
                feature spec is complete.
              </p>
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
