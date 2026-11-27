"use client";

/**
 * Administrator user management backed by /api/v1/users/.
 *
 * - Search and filter by role / status, paginated (20 per page).
 * - Change a user's role or status inline (saved immediately).
 * - Create accounts with any role (e.g. instructors).
 *
 * The API enforces everything (admin-only, no self-demotion, last-admin
 * protection); this component mirrors those rules only to explain them.
 */

import { useCallback, useEffect, useState } from "react";
import { Plus, Search, ShieldAlert, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { useAuth } from "@/lib/auth-context";
import {
  createUser,
  errorText,
  fieldErrors,
  listUsers,
  updateUser,
  type UserFilters,
} from "@/lib/users-api";
import type { AccountStatus, AdminUser, Role } from "@/types/api";

const PAGE_SIZE = 20;

const ROLES: { value: Role; label: string }[] = [
  { value: "student", label: "Student" },
  { value: "instructor", label: "Instructor" },
  { value: "admin", label: "Administrator" },
];

const STATUSES: { value: AccountStatus; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "invited", label: "Invited" },
  { value: "suspended", label: "Suspended" },
  { value: "archived", label: "Archived" },
];

const selectClass =
  "px-2 py-1.5 text-sm rounded-md bg-[var(--surface-raised)] text-[var(--text-primary)] " +
  "border border-[var(--surface-border)] focus:outline-none focus:border-[var(--accent-primary)] " +
  "disabled:opacity-60 disabled:cursor-not-allowed";

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
}

export function UsersAdmin() {
  const { user: me, isLoading: authLoading } = useAuth();

  const [filters, setFilters] = useState<UserFilters>({ search: "", role: "", status: "", page: 1 });
  const [searchInput, setSearchInput] = useState("");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const isAdmin = me?.role === "admin";

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const page = await listUsers(filters);
      setUsers(page.results);
      setCount(page.count);
    } catch (err) {
      setLoadError(errorText(err));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    if (isAdmin) void load();
  }, [isAdmin, load]);

  // Debounce the search box into the filters.
  useEffect(() => {
    const t = setTimeout(() => {
      setFilters((f) => (f.search === searchInput ? f : { ...f, search: searchInput, page: 1 }));
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  async function changeUser(target: AdminUser, changes: Partial<Pick<AdminUser, "role" | "status">>) {
    setSavingId(target.id);
    setNotice(null);
    try {
      const updated = await updateUser(target.id, changes);
      setUsers((list) => list.map((u) => (u.id === updated.id ? updated : u)));
      setNotice({ kind: "ok", text: `Updated ${updated.email}.` });
    } catch (err) {
      setNotice({ kind: "error", text: `Could not update ${target.email}: ${errorText(err)}` });
    } finally {
      setSavingId(null);
    }
  }

  if (authLoading) return null;

  if (!isAdmin) {
    return (
      <Card>
        <CardBody>
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <ShieldAlert size={20} className="text-[var(--status-warning)]" aria-hidden="true" />
            <p className="text-sm font-medium text-[var(--text-primary)]">Administrator access required</p>
            <p className="text-xs text-[var(--text-secondary)]">
              Only platform administrators can manage user accounts.
            </p>
          </div>
        </CardBody>
      </Card>
    );
  }

  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE));
  const page = filters.page ?? 1;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">User Management</h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            {loading ? "Loading users…" : `${count} ${count === 1 ? "user" : "users"}`}
          </p>
        </div>
        <Button onClick={() => setShowCreate((v) => !v)} variant={showCreate ? "secondary" : "primary"}>
          {showCreate ? <X size={14} aria-hidden="true" /> : <Plus size={14} aria-hidden="true" />}
          {showCreate ? "Cancel" : "Add user"}
        </Button>
      </div>

      {showCreate && (
        <CreateUserForm
          onCreated={(created) => {
            setShowCreate(false);
            setNotice({ kind: "ok", text: `Created ${created.email} (${created.role}).` });
            void load();
          }}
        />
      )}

      {notice && (
        <div
          role={notice.kind === "error" ? "alert" : "status"}
          className={
            "text-sm rounded-md px-3 py-2 border " +
            (notice.kind === "error"
              ? "text-[var(--status-error)] border-[var(--status-error)] bg-[#fff5f5]"
              : "text-[var(--status-success)] border-[var(--status-success)] bg-[#f0fff4]")
          }
        >
          {notice.text}
        </div>
      )}

      <Card>
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative flex-1 min-w-[200px]">
              <span className="sr-only">Search users</span>
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" aria-hidden="true" />
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Search name or email"
                className={selectClass + " w-full pl-8"}
              />
            </label>
            <label>
              <span className="sr-only">Filter by role</span>
              <select
                value={filters.role}
                onChange={(e) => setFilters((f) => ({ ...f, role: e.target.value as Role | "", page: 1 }))}
                className={selectClass}
              >
                <option value="">All roles</option>
                {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </label>
            <label>
              <span className="sr-only">Filter by status</span>
              <select
                value={filters.status}
                onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value as AccountStatus | "", page: 1 }))}
                className={selectClass}
              >
                <option value="">All statuses</option>
                {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </label>
          </div>

          {loadError ? (
            <div role="alert" className="text-sm text-[var(--status-error)] py-6 text-center">
              {loadError}{" "}
              <button className="underline" onClick={() => void load()}>Retry</button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-[var(--text-secondary)] border-b border-[var(--surface-border)]">
                    <th className="py-2 pr-3 font-medium">User</th>
                    <th className="py-2 pr-3 font-medium">Role</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium whitespace-nowrap">Joined</th>
                    <th className="py-2 font-medium whitespace-nowrap">Last sign-in</th>
                  </tr>
                </thead>
                <tbody>
                  {!loading && users.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-[var(--text-secondary)]">
                        No users match these filters.
                      </td>
                    </tr>
                  )}
                  {users.map((u) => {
                    const self = u.id === me?.id;
                    const busy = savingId === u.id;
                    const lockHint = self ? "You cannot change your own role or status" : undefined;
                    return (
                      <tr key={u.id} className="border-b border-[var(--surface-border)] last:border-0">
                        <td className="py-2.5 pr-3">
                          <div className="font-medium text-[var(--text-primary)]">
                            {u.full_name || "—"}
                            {self && <span className="ml-1.5 text-xs text-[var(--text-muted)]">(you)</span>}
                          </div>
                          <div className="text-xs text-[var(--text-secondary)]">{u.email}</div>
                        </td>
                        <td className="py-2.5 pr-3">
                          <select
                            aria-label={`Role for ${u.email}`}
                            value={u.role}
                            disabled={self || busy}
                            title={lockHint}
                            onChange={(e) => void changeUser(u, { role: e.target.value as Role })}
                            className={selectClass}
                          >
                            {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                          </select>
                        </td>
                        <td className="py-2.5 pr-3">
                          <select
                            aria-label={`Status for ${u.email}`}
                            value={u.status}
                            disabled={self || busy}
                            title={lockHint}
                            onChange={(e) => void changeUser(u, { status: e.target.value as AccountStatus })}
                            className={selectClass}
                          >
                            {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                          </select>
                        </td>
                        <td className="py-2.5 pr-3 whitespace-nowrap text-[var(--text-secondary)]">{formatDate(u.date_joined)}</td>
                        <td className="py-2.5 whitespace-nowrap text-[var(--text-secondary)]">{formatDate(u.last_login)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {pages > 1 && (
            <div className="flex items-center justify-between pt-1 text-xs text-[var(--text-secondary)]">
              <span>Page {page} of {pages}</span>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" disabled={page <= 1 || loading}
                  onClick={() => setFilters((f) => ({ ...f, page: page - 1 }))}>
                  Previous
                </Button>
                <Button size="sm" variant="secondary" disabled={page >= pages || loading}
                  onClick={() => setFilters((f) => ({ ...f, page: page + 1 }))}>
                  Next
                </Button>
              </div>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function CreateUserForm({ onCreated }: { onCreated: (user: AdminUser) => void }) {
  const [form, setForm] = useState({ email: "", first_name: "", last_name: "", role: "instructor" as Role, password: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const set = (field: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [field]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErrors({});
    setFormError(null);
    try {
      onCreated(await createUser(form));
    } catch (err) {
      const fields = fieldErrors(err);
      setErrors(fields);
      if (!Object.keys(fields).length) setFormError(errorText(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardBody>
        <form onSubmit={submit} className="space-y-3" noValidate>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">New account</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Input label="First name" id="new-first-name" value={form.first_name} onChange={set("first_name")} error={errors.first_name} />
            <Input label="Last name" id="new-last-name" value={form.last_name} onChange={set("last_name")} error={errors.last_name} />
            <Input label="Email" id="new-email" type="email" required value={form.email} onChange={set("email")} error={errors.email} />
            <div className="flex flex-col gap-1">
              <label htmlFor="new-role" className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wide">Role</label>
              <select id="new-role" value={form.role} onChange={set("role")} className={selectClass + " py-2"}>
                {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
            <Input
              label="Temporary password" id="new-password" type="password" autoComplete="new-password"
              required value={form.password} onChange={set("password")} error={errors.password}
              hint="Share it with the user privately; at least 8 characters, not too common."
            />
          </div>
          {formError && <p role="alert" className="text-xs text-[var(--status-error)]">{formError}</p>}
          <div className="flex justify-end">
            <Button type="submit" loading={submitting} disabled={submitting}>Create account</Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
