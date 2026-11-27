"use client";

/**
 * "My Labs": the signed-in user's saved workspace labs (private to them).
 * Open loads a lab into the workspace; Delete removes it after confirmation.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { FolderOpen, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { deleteLab, labErrorText, listLabs, type LabSummary } from "@/lib/lab-api";

function formatUpdated(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function MyLabsSection() {
  const [labs, setLabs] = useState<LabSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setLabs(await listLabs());
    } catch (err) {
      setError(labErrorText(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function remove(lab: LabSummary) {
    if (!window.confirm(`Delete "${lab.name}"? This cannot be undone.`)) return;
    setDeletingId(lab.id);
    try {
      await deleteLab(lab.id);
      setLabs((list) => list.filter((l) => l.id !== lab.id));
    } catch (err) {
      setError(`Could not delete "${lab.name}": ${labErrorText(err)}`);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <section aria-labelledby="my-labs-heading" className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 id="my-labs-heading" className="text-sm font-semibold text-[var(--text-primary)]">
            My Labs
          </h2>
          <p className="text-xs text-[var(--text-secondary)]">
            Topologies you saved from the workspace. Only you can see them.
          </p>
        </div>
        <Link href="/labs/workspace?new=1">
          <Button size="sm">
            <Plus size={12} aria-hidden="true" />
            Create New Lab
          </Button>
        </Link>
      </div>

      {error && (
        <p role="alert" className="text-xs text-[var(--status-error)]">
          {error}{" "}
          <button className="underline" onClick={() => void load()}>Retry</button>
        </p>
      )}

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-28 rounded-lg border border-[var(--surface-border)] bg-[var(--surface-overlay)] animate-pulse" />
          ))}
        </div>
      ) : labs.length === 0 && !error ? (
        <Card>
          <CardBody>
            <p className="py-4 text-center text-sm text-[var(--text-secondary)]">
              You haven&apos;t saved any labs yet. Build a topology in the workspace and click Save.
            </p>
          </CardBody>
        </Card>
      ) : (
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {labs.map((lab) => (
            <li key={lab.id}>
              <Card className="h-full">
                <CardBody className="flex flex-col gap-2 h-full">
                  <div className="min-w-0">
                    <h3 className="text-sm font-semibold text-[var(--text-primary)] truncate" title={lab.name}>
                      {lab.name}
                    </h3>
                    {lab.description && (
                      <p className="mt-0.5 text-xs text-[var(--text-secondary)] line-clamp-2">{lab.description}</p>
                    )}
                  </div>
                  <p className="text-xs text-[var(--text-muted)]">
                    {lab.device_count} {lab.device_count === 1 ? "device" : "devices"} ·{" "}
                    {lab.link_count} {lab.link_count === 1 ? "link" : "links"} · Updated {formatUpdated(lab.updated_at)}
                  </p>
                  <div className="mt-auto flex gap-2 pt-1">
                    <Link href={`/labs/workspace?lab=${lab.id}`}>
                      <Button size="sm" variant="secondary">
                        <FolderOpen size={12} aria-hidden="true" />
                        Open
                      </Button>
                    </Link>
                    <Button
                      size="sm" variant="ghost" onClick={() => void remove(lab)}
                      disabled={deletingId === lab.id} aria-label={`Delete ${lab.name}`}
                    >
                      <Trash2 size={12} aria-hidden="true" />
                      {deletingId === lab.id ? "Deleting…" : "Delete"}
                    </Button>
                  </div>
                </CardBody>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
