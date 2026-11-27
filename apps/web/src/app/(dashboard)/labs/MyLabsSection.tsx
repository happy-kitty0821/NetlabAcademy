"use client";

/**
 * Lab dashboard: the signed-in user's saved labs (private to them), shown
 * as tiles or as a table, with a name/description filter.
 *
 * Open loads a lab into the workspace; Delete removes it after confirmation.
 * The chosen view is remembered per browser.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { FolderOpen, LayoutGrid, List, Plus, Search, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { deleteLab, labErrorText, listLabs, type LabSummary } from "@/lib/lab-api";

type View = "tiles" | "list";
const VIEW_KEY = "netlab_labs_view";

function formatUpdated(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function plural(n: number, word: string) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function MyLabsSection() {
  const [labs, setLabs] = useState<LabSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [view, setView] = useState<View>("tiles");

  // Restore the remembered view after mount (avoids an SSR mismatch).
  useEffect(() => {
    try {
      const v = localStorage.getItem(VIEW_KEY);
      if (v === "tiles" || v === "list") setView(v);
    } catch { /* storage unavailable: keep the default */ }
  }, []);

  function changeView(v: View) {
    setView(v);
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* ignore */ }
  }

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

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? labs.filter((l) => l.name.toLowerCase().includes(q) || l.description.toLowerCase().includes(q))
      : labs;
    return [...list].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }, [labs, query]);

  return (
    <section aria-labelledby="my-labs-heading" className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="my-labs-heading" className="mr-2 text-sm font-semibold text-[var(--text-primary)]">
          My labs
          {!loading && <span className="ml-1.5 font-normal text-[var(--text-muted)]">{labs.length}</span>}
        </h2>
        <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
          <Search size={13} aria-hidden="true"
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="search" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter labs" aria-label="Filter labs by name or description"
            className="h-8 w-full rounded-md border border-[var(--surface-border)] bg-[var(--surface-raised)] pl-8 pr-2 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:border-[var(--accent-primary)] focus:outline-none"
          />
        </div>
        <div className="ml-auto flex rounded-md border border-[var(--surface-border)] p-0.5" role="group" aria-label="View">
          <ViewButton active={view === "tiles"} onClick={() => changeView("tiles")} icon={LayoutGrid} label="Tiles" />
          <ViewButton active={view === "list"} onClick={() => changeView("list")} icon={List} label="List" />
        </div>
      </div>

      {error && (
        <p role="alert" className="text-xs text-[var(--status-error)]">
          {error}{" "}
          <button className="underline" onClick={() => void load()}>Retry</button>
        </p>
      )}

      {loading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-32 animate-pulse rounded-md border border-[var(--surface-border)] bg-[var(--surface-overlay)]" />
          ))}
        </div>
      ) : labs.length === 0 && !error ? (
        <div className="rounded-md border border-dashed border-[var(--surface-border)] px-6 py-10 text-center">
          <p className="text-sm text-[var(--text-primary)]">No labs yet</p>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            Create a lab, add devices, cable them and click Save. It will appear here.
          </p>
          <Link href="/labs/workspace?new=1" className="mt-4 inline-block">
            <Button size="sm"><Plus size={12} aria-hidden="true" /> New lab</Button>
          </Link>
        </div>
      ) : shown.length === 0 ? (
        <p className="py-6 text-center text-xs text-[var(--text-secondary)]">
          No labs match &ldquo;{query}&rdquo;.
        </p>
      ) : view === "tiles" ? (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {shown.map((lab) => (
            <li key={lab.id}>
              <LabTile lab={lab} deleting={deletingId === lab.id} onDelete={() => void remove(lab)} />
            </li>
          ))}
        </ul>
      ) : (
        <LabTable labs={shown} deletingId={deletingId} onDelete={(l) => void remove(l)} />
      )}
    </section>
  );
}

function ViewButton({ active, onClick, icon: Icon, label }: {
  active: boolean; onClick: () => void; icon: React.ElementType; label: string;
}) {
  return (
    <button onClick={onClick} aria-pressed={active} title={label}
      className={"flex h-7 items-center gap-1 rounded px-2 text-xs " +
        (active ? "bg-[var(--surface-overlay)] font-medium text-[var(--text-primary)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-primary)]")}>
      <Icon size={13} aria-hidden="true" />
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

function LabTile({ lab, deleting, onDelete }: { lab: LabSummary; deleting: boolean; onDelete: () => void }) {
  return (
    <article className="group flex h-full flex-col rounded-md border border-[var(--surface-border)] bg-[var(--surface-raised)] transition-colors hover:border-[var(--accent-primary)]">
      <Link href={`/labs/workspace?lab=${lab.id}`} className="block flex-1 px-4 pb-2 pt-3">
        <h3 className="truncate text-sm font-semibold text-[var(--text-primary)]" title={lab.name}>{lab.name}</h3>
        <p className="mt-1 line-clamp-2 min-h-[2rem] text-xs text-[var(--text-secondary)]">
          {lab.description || <span className="text-[var(--text-muted)]">No description</span>}
        </p>
        <dl className="mt-3 grid grid-cols-2 gap-x-3 text-xs">
          <div>
            <dt className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Nodes</dt>
            <dd className="font-mono text-[var(--text-primary)]">{lab.device_count}</dd>
          </div>
          <div>
            <dt className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">Links</dt>
            <dd className="font-mono text-[var(--text-primary)]">{lab.link_count}</dd>
          </div>
        </dl>
      </Link>
      <div className="flex items-center gap-1 border-t border-[var(--surface-border)] px-2 py-1.5">
        <span className="ml-2 mr-auto truncate text-[11px] text-[var(--text-muted)]">
          Modified {formatUpdated(lab.updated_at)}
        </span>
        <Link href={`/labs/workspace?lab=${lab.id}`}>
          <Button size="sm" variant="ghost"><FolderOpen size={12} aria-hidden="true" /> Open</Button>
        </Link>
        <Button size="sm" variant="ghost" onClick={onDelete} disabled={deleting} aria-label={`Delete ${lab.name}`}>
          <Trash2 size={12} aria-hidden="true" />
          <span className="sr-only sm:not-sr-only">{deleting ? "Deleting…" : "Delete"}</span>
        </Button>
      </div>
    </article>
  );
}

function LabTable({ labs, deletingId, onDelete }: {
  labs: LabSummary[]; deletingId: string | null; onDelete: (l: LabSummary) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-[var(--surface-border)] bg-[var(--surface-raised)]">
      <table className="w-full min-w-[36rem] text-left text-xs">
        <thead className="bg-[var(--surface-overlay)] text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
          <tr>
            <th className="px-4 py-2 font-semibold">Name</th>
            <th className="px-4 py-2 font-semibold">Description</th>
            <th className="px-3 py-2 text-right font-semibold">Nodes</th>
            <th className="px-3 py-2 text-right font-semibold">Links</th>
            <th className="px-4 py-2 font-semibold">Modified</th>
            <th className="px-2 py-2"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {labs.map((lab) => (
            <tr key={lab.id} className="border-t border-[var(--surface-border)] hover:bg-[var(--surface-overlay)]">
              <td className="max-w-[14rem] px-4 py-2">
                <Link href={`/labs/workspace?lab=${lab.id}`}
                  className="block truncate font-medium text-[var(--text-primary)] hover:text-[var(--accent-primary)] hover:underline">
                  {lab.name}
                </Link>
              </td>
              <td className="max-w-[18rem] truncate px-4 py-2 text-[var(--text-secondary)]">{lab.description || "—"}</td>
              <td className="px-3 py-2 text-right font-mono">{lab.device_count}</td>
              <td className="px-3 py-2 text-right font-mono">{lab.link_count}</td>
              <td className="whitespace-nowrap px-4 py-2 text-[var(--text-muted)]">{formatUpdated(lab.updated_at)}</td>
              <td className="whitespace-nowrap px-2 py-1 text-right">
                <Link href={`/labs/workspace?lab=${lab.id}`}>
                  <Button size="sm" variant="ghost" aria-label={`Open ${lab.name}`}><FolderOpen size={12} aria-hidden="true" /></Button>
                </Link>
                <Button size="sm" variant="ghost" onClick={() => onDelete(lab)} disabled={deletingId === lab.id}
                  aria-label={`Delete ${lab.name}`}>
                  <Trash2 size={12} aria-hidden="true" />
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="border-t border-[var(--surface-border)] px-4 py-1.5 text-[11px] text-[var(--text-muted)]">
        {plural(labs.length, "lab")}
      </p>
    </div>
  );
}
