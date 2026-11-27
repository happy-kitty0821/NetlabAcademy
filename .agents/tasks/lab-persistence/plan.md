# Implementation Plan — Lab Persistence & Labs Listing Page

A full vertical slice: Django `Lab` model + CRUD API, then Next.js labs page +
workspace save/open + dashboard. Work backend-first, then frontend.

## Key design decisions (code-grounded, resolve these as stated — do not re-decide)

1. **Use DRF generics for Lab CRUD.** `DEFAULT_PERMISSION_CLASSES=[IsAuthenticated]`
   is already global (`netlab/settings/base.py`), and `netlab/api/exception_handler.py`
   already normalizes every DRF error into `{error:{code,message,detail?}}` — the
   exact shape `apiFetch` (apps/web/src/lib/api.ts) throws. So generics give clean
   list/create/retrieve/update/destroy with authorization enforced by the queryset
   and errors consistent with the existing frontend. `LabListCreateView` extends
   `generics.ListCreateAPIView`; `LabDetailView` extends
   `generics.RetrieveUpdateDestroyAPIView`. This mirrors `apps.accounts`' use of
   `generics.CreateAPIView` for `RegisterView`.

2. **Disable pagination on the list view.** REST_FRAMEWORK sets
   `PageNumberPagination` (PAGE_SIZE=20) globally, which would wrap the list in
   `{count,next,previous,results}`. The brief's `listLabs(): LabSummary[]` expects a
   plain array. Set `pagination_class = None` on `LabListCreateView`.

3. **Persist the React Flow canvas, not the simulator topology document.**
   `convertFlowToTopology` (apps/web/src/lib/convertFlowToTopology.ts) is one-way: it
   regenerates interface names from the device catalog template and **discards node
   `position`s**. There is no reverse converter. Storing the simulator document
   (`{nodes,links}`) would therefore lose canvas layout on reopen (every node would
   collapse to the origin). The canvas is the source of truth, and sessionStorage
   already persists it as `{nodes: DeviceNode[], edges: Edge[]}`. So the `Lab.topology`
   JSONField stores `{nodes, edges}` (the raw React Flow canvas). Save = serialize the
   live `nodes`/`edges`; Open = `setNodes`/`setEdges` directly — no conversion, lossless.
   The serializer derives `device_count = len(nodes)` and `link_count = len(edges)`.
   (The brief's `{nodes, links}` comment and `links` type field are a suggestion; the
   `any[]` latitude and the lossy-reverse-conversion problem make `{nodes, edges}` the
   correct, code-grounded choice. The exposed field names `device_count`/`link_count`
   stay brief-faithful.)

4. **Keep `page.tsx` server, move API-driven UI into client components.** Next.js
   forbids `metadata` exports from `"use client"` components, and the auth token lives
   in `localStorage` (client-only). So for `labs/page.tsx` and `dashboard/page.tsx`,
   keep `page.tsx` as a thin server component that exports `metadata` and renders a new
   client component; the client component does the `useEffect` fetching.

5. **Read `?lab=` via `window.location.search` in `useEffect`**, not `useSearchParams`
   (which would force a Suspense boundary and complicate the build).

6. **`owner_name`** comes from the `User.full_name` property
   (`apps/accounts/models.py` — `@property full_name`), via
   `serializers.CharField(source='owner.full_name', read_only=True)`.

---

## Backend (FEAT-001)

- [ ] 1. Create the `Lab` model and its migration.
      Replace the placeholder in `services/api/apps/labs/models.py` with a `Lab` model:
      `id = UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`;
      `owner = ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE, related_name='labs')`
      (import `settings` from `django.conf`, matching the accounts `0001_initial`
      migration pattern `to=settings.AUTH_USER_MODEL`); `name = CharField(max_length=200)`;
      `description = TextField(blank=True, default='')`;
      `topology = JSONField(default=dict)` (comment: `# React Flow canvas: {nodes: [...], edges: [...]}`);
      `created_at = DateTimeField(auto_now_add=True)`; `updated_at = DateTimeField(auto_now=True)`;
      `class Meta: ordering = ['-updated_at']`; `__str__` returns `self.name`. Keep the
      existing file header. Then run makemigrations + migrate.
      Files: services/api/apps/labs/models.py; services/api/apps/labs/migrations/0001_initial.py (generated)
      Verify: `cd services/api && python manage.py makemigrations labs --settings=netlab.settings.dev`
      creates `apps/labs/migrations/0001_initial.py` (depends on accounts), and
      `python manage.py migrate --settings=netlab.settings.dev` applies it cleanly.

- [ ] 2. Add `LabSerializer` and `LabListSerializer` to the labs serializers.
      Append after `PingRequestSerializer` in `services/api/apps/labs/serializers.py`:
      `LabSerializer(serializers.ModelSerializer)` with `Meta.model = Lab`, `fields =
      ['id','name','description','topology','created_at','updated_at','owner_name']`,
      `read_only_fields = ['id','created_at','updated_at','owner_name']`, and
      `owner_name = serializers.CharField(source='owner.full_name', read_only=True)`.
      `LabListSerializer(serializers.ModelSerializer)` with `fields =
      ['id','name','description','created_at','updated_at','device_count','link_count']`,
      `read_only_fields = ['id','created_at','updated_at','device_count','link_count']`,
      `device_count = serializers.SerializerMethodField()`,
      `link_count = serializers.SerializerMethodField()`,
      `get_device_count` returns `len(obj.topology.get('nodes', []))` and
      `get_link_count` returns `len(obj.topology.get('edges', []))` (tolerate a
      non-dict topology with `getattr(obj.topology, 'get', lambda *a: [])`).
      Files: services/api/apps/labs/serializers.py
      Verify: `cd services/api && python -c "import django; django.setup()" ` is not
      needed; instead `python manage.py check --settings=netlab.settings.dev` passes
      (import path resolves).

- [ ] 3. Add `LabListCreateView` and `LabDetailView` to the labs views.
      Append to `services/api/apps/labs/views.py`: import
      `from rest_framework import generics` and `from .models import Lab` and the two
      new serializers. `LabListCreateView(generics.ListCreateAPIView)`:
      `permission_classes = [IsAuthenticated]`, `pagination_class = None`,
      `get_queryset` returns `Lab.objects.filter(owner=self.request.user)`,
      `get_serializer_class` returns `LabListSerializer` for GET else `LabSerializer`,
      `perform_create(self, serializer)` calls `serializer.save(owner=self.request.user)`.
      `LabDetailView(generics.RetrieveUpdateDestroyAPIView)`: `permission_classes =
      [IsAuthenticated]`, `get_queryset` returns `Lab.objects.filter(owner=self.request.user)`
      (so a non-owner's UUID yields a 404 via the custom exception handler),
      `serializer_class = LabSerializer`, `lookup_url_kwarg = 'lab_id'`,
      `lookup_field = 'id'`. DRF gives PATCH (partial) and DELETE (204) for free.
      Files: services/api/apps/labs/views.py
      Verify: `cd services/api && python manage.py check --settings=netlab.settings.dev` passes.

- [ ] 4. Register the lab routes in the labs urls.
      Add to `urlpatterns` in `services/api/apps/labs/urls.py`, importing the two new
      views: `path("labs/", LabListCreateView.as_view(), name="lab-list-create")` and
      `path("labs/<uuid:lab_id>/", LabDetailView.as_view(), name="lab-detail")`. The
      parent `netlab/api/urls.py` already includes `apps.labs.urls` under `"labs/"`, so
      the full paths are `/api/v1/labs/labs/` and `/api/v1/labs/labs/<id>/` (accepted).
      Files: services/api/apps/labs/urls.py
      Verify: `cd services/api && python manage.py check --settings=netlab.settings.dev` passes.

- [ ] 5. Add Lab CRUD + authorization tests.
      Create `services/api/apps/labs/tests/test_lab_crud.py` using Django's `TestCase`
      (needs DB; pytest.ini already sets `DJANGO_SETTINGS_MODULE=netlab.settings.dev`)
      and `rest_framework.test.APIClient`. Cover, each authenticating with
      `client.force_authenticate(user=...)`:
      create returns 201 and is owned by the user; list returns only the caller's labs
      (two users, isolation); retrieve returns the full topology + `owner_name` ==
      `user.full_name`; PATCH updates name and topology; DELETE returns 204 and the lab
      is gone; list response items have `device_count`/`link_count` and no `topology`;
      unauthenticated request returns 401 (do not `force_authenticate`); a non-owner
      GET/PATCH/DELETE on another user's lab returns 404. Use `uuid.uuid4()` ids when
      building topology payloads. Follow the assertion style of the existing
      `test_simulation_adapter_catalog.py`.
      Files: services/api/apps/labs/tests/test_lab_crud.py
      Verify: `cd services/api && python -m pytest apps/labs/tests/ -q` passes (new +
      existing 15 adapter tests). Regression: `cd packages/simulator-core && python -m
      pytest tests/ -q -p no:django` still passes (438 tests, untouched).

## Frontend (FEAT-002)

- [ ] 6. Create the lab API client and types.
      Create `apps/web/src/lib/lab-api.ts` importing `apiFetch` from `./api`,
      `DeviceNode` from `@/lib/deviceTypes`, `Edge` from `@xyflow/react`. Export
      `LabSummary { id; name; description; created_at; updated_at; device_count; link_count }`,
      `LabTopology { nodes: DeviceNode[]; edges: Edge[] }`, `Lab extends LabSummary {
      topology: LabTopology }`. Functions: `listLabs()` GET `/labs/labs/` →
      `LabSummary[]`; `createLab({name, description?, topology})` POST `/labs/labs/` →
      `Lab`; `getLab(id)` GET `/labs/labs/${id}/` → `Lab`; `updateLab(id, partial)`
      PATCH `/labs/labs/${id}/` → `Lab`; `deleteLab(id)` DELETE `/labs/labs/${id}/` →
      `void`. Use the same `apiFetch<T>(path, {method, body: JSON.stringify(...)})`
      pattern as `simulation-api.ts`. No trailing-slash handling needed beyond the paths
      above (next.config.ts already proxies with/without slash).
      Files: apps/web/src/lib/lab-api.ts
      Verify: `cd apps/web && npm run build` type-checks (gate run after FEAT-002).

- [ ] 7. Add the "My Labs" client section to the labs listing page.
      Convert `apps/web/src/app/(dashboard)/labs/page.tsx` to a thin server component:
      keep `export const metadata`, the static `LABS` catalog, `LabCard`,
      `DIFFICULTY_BADGE`, `TOPIC_ICON` helpers, and the Curated Labs sections ("Available
      now" / "Coming soon") exactly as today (this satisfies "keep the existing static
      lab catalog as Curated Labs"). Insert `<MyLabsSection />` near the top (after the
      page header). Create `apps/web/src/app/(dashboard)/labs/MyLabsSection.tsx` as a
      `"use client"` component: `useEffect` calls `listLabs()`, tracks
      `loading`/`error`/`labs`; renders a "My Labs" header with a "Create New Lab" button
      (`<Link href="/labs/workspace"><Button>Create New Lab</Button></Link>`); a grid of
      cards (name, description, device_count, last updated formatted from `updated_at`)
      each with Open (`<Link href={`/labs/workspace?lab=${lab.id}`}>Open</Link>`) and
      Delete (calls `deleteLab(id)`, then refetches) buttons; loading skeleton; error
      message; empty state "You haven't saved any labs yet. Build a topology in the
      workspace and click Save." Use the existing `Card`/`Button`/`Badge` UI components
      and the light-theme CSS vars (`var(--text-primary)`, `#d0d7de`, `#0969da`). Do NOT
      use framer-motion. Do not change the curated catalog behavior.
      Files: apps/web/src/app/(dashboard)/labs/page.tsx; apps/web/src/app/(dashboard)/labs/MyLabsSection.tsx
      Verify: `cd apps/web && npm run build` passes.

- [ ] 8. Create the Save Lab dialog component.
      Create `apps/web/src/components/labs/workspace/SaveLabDialog.tsx` (`"use client"`)
      modeled on `NodeConfigPopup.tsx`: absolute inset-0 overlay + centered 320px modal,
      Name field (required, autofocus) and Description textarea, Save (green, disabled
      when name empty) and Cancel, Enter to save / Esc to close. Props:
      `{ mode: 'save' | 'saveAs'; initialName?: string; initialDescription?: string;
      onSubmit: (name: string, description: string) => void; onClose: () => void; }`.
      Same inline-style light theme as `NodeConfigPopup` (white card, `#d0d7de` borders).
      Files: apps/web/src/components/labs/workspace/SaveLabDialog.tsx
      Verify: `cd apps/web && npm run build` passes.

- [ ] 9. Add Save / Save As / Open / New + lab loading to the workspace.
      Modify `apps/web/src/app/(dashboard)/labs/workspace/page.tsx`: add state
      `currentLabId: string | null`, `currentLabName: string | null`,
      `saveDialog: { open: boolean; mode: 'save' | 'saveAs' }`. On mount, read
      `new URLSearchParams(window.location.search).get('lab')`; if it looks like a UUID
      (`/^[0-9a-f-]{36}$/i`), call `getLab(id)`, `setNodes(lab.topology.nodes)`,
      `setEdges(lab.topology.edges)`, `bumpCounter`, set `currentLabId`/`currentLabName`,
      and skip the sessionStorage load for that render; on fetch error fall back to the
      existing sessionStorage load (so curated non-UUID ids still open a blank canvas).
      `handleSave({name, description})`: build `topology = { nodes, edges }`; if
      `saveDialog.mode==='save' && currentLabId`, `updateLab(currentLabId, {name,
      description, topology})` else `createLab({name, description, topology})`; on
      success set `currentLabId`/`currentLabName` from the response, close the dialog,
      store `currentLabId` in sessionStorage under a new key (e.g.
      `netlab_current_lab`) so a refresh keeps the association. `handleSaveAs`: open the
      dialog with `mode:'saveAs'` (always creates new). `handleOpen`: `router.push('/labs')`.
      `handleNew`: clear canvas (`setNodes([])`, `setEdges([])`), clear
      `currentLabId`/`currentLabName`, remove both sessionStorage keys, and `handleWipe`.
      Render `<SaveLabDialog>` when `saveDialog.open`. Import `useRouter` from
      `next/navigation`.
      Modify `apps/web/src/components/labs/workspace/WorkspaceToolbar.tsx`: add props
      `currentLabName: string | null`, `onSave`, `onSaveAs`, `onOpen`, `onNew`, `saving?: boolean`;
      render the lab name (currentLabName ?? 'Untitled Lab') instead of the hardcoded
      "Untitled Lab"; add a divider + Save / Save As / Open / New buttons (lucide
      `Save`, `FolderOpen`, `FilePlus2`, `Trash2`-reuse) using the existing `Btn` helper
      style (Save green, others neutral). Keep all existing Start/Stop/Wipe/Clear controls
      unchanged. Do not break the toolbar for the curated-lab path (currentLabName null).
      Files: apps/web/src/app/(dashboard)/labs/workspace/page.tsx; apps/web/src/components/labs/workspace/WorkspaceToolbar.tsx
      Verify: `cd apps/web && npm run build` passes.

- [ ] 10. Update the dashboard with lab count + recent labs.
       Convert `apps/web/src/app/(dashboard)/dashboard/page.tsx` to a thin server
       component: keep `export const metadata`, render `<DashboardClient />`. Create
       `apps/web/src/app/(dashboard)/dashboard/DashboardClient.tsx` (`"use client"`):
       `useEffect` calls `listLabs()`; render the 4-stat row with the "Labs completed"
       stat replaced by "My Labs" showing the fetched count (other three stay "—"
       placeholders); replace the empty "Recent activity" card with a "Recent Labs"
       card listing the 3 most-recently-updated labs (`labs.slice(0,3)`) each as a
       `<Link href={`/labs/workspace?lab=${lab.id}`}>` row (name + relative/absolute
       updated time), with an empty state "No saved labs yet." when the list is empty;
       add a "Create New Lab" quick link (`<Link href="/labs/workspace">`) to the
       "Jump to" card. Move the existing `EmptyState`/`QuickLink` helpers into this
       client file (they are pure JSX + lucide + Link and work client-side). Keep the
       light theme and existing layout grid. No framer-motion.
       Files: apps/web/src/app/(dashboard)/dashboard/page.tsx; apps/web/src/app/(dashboard)/dashboard/DashboardClient.tsx
       Verify: `cd apps/web && npm run build` passes.

## Final validation gates (run before commit)

- [ ] 11. Backend regression + new tests green.
      `cd services/api && python -m pytest apps/labs/tests/ -q` (new CRUD tests + 15
      adapter tests pass) and `cd packages/simulator-core && python -m pytest tests/ -q
      -p no:django` (438 tests, untouched) still green.
- [ ] 12. Frontend build green.
      `cd apps/web && npm run build` passes type-checking and the production build.
- [ ] 13. Commit (do not push — the workflow's push step handles that).
      Stage the new/changed files and commit as
      `feat(labs): lab persistence model, CRUD API, labs listing page, workspace save/open`.

## Contract checklist (the convergence review verifies these cross-FEAT seams)

- Backend list returns a plain array (no pagination envelope); frontend `listLabs` reads it as `LabSummary[]`.
- `LabListSerializer` omits `topology` and includes `device_count`/`link_count`; the frontend `LabSummary` type matches exactly.
- `LabSerializer` includes `topology: {nodes, edges}` and `owner_name`; `getLab` returns it and the workspace loads `nodes`/`edges` directly.
- DELETE returns 204; `apiFetch` maps 204 → `undefined`; `deleteLab` returns `void`.
- All lab endpoints require auth and scope to `owner=request.user` (non-owner → 404).
- Curated static labs and the simulation endpoints are untouched.

---

## Digest

For each file: the block to change, the test that covers it, and what passes today.

### Backend

**services/api/apps/labs/models.py** — currently a 3-line placeholder comment.
Replace it with `import uuid`, `from django.conf import settings`, `from django.db import models`,
and the `Lab` class (see item 1). The FK uses `settings.AUTH_USER_MODEL`.
Test: `apps/labs/tests/test_lab_crud.py` (new, item 5).
Verified today: `python -m pytest apps/labs/tests/ -q` passes — 15 adapter tests
(`test_simulation_adapter_catalog.py`, `SimpleTestCase`, no DB).

**services/api/apps/labs/serializers.py** — ends with `PingRequestSerializer` (lines ~50-54).
Append `LabSerializer` and `LabListSerializer` (item 2).
Test: `test_lab_crud.py`.
Verified today: `python -m pytest apps/labs/tests/ -q` (import succeeds in adapter tests).

**services/api/apps/labs/views.py** — ends with `SimulationCLIView`.
Append `LabListCreateView`, `LabDetailView` + imports `generics`, `Lab`, the serializers (item 3).
Test: `test_lab_crud.py`.
Verified today: `python manage.py check --settings=netlab.settings.dev` passes; adapter tests pass.

**services/api/apps/labs/urls.py** — `urlpatterns` lists the 7 simulation routes.
Add the 2 lab routes + import the new views (item 4). Parent include (`netlab/api/urls.py`
line `path("labs/", include("apps.labs.urls"))`) stays unchanged.
Test: `test_lab_crud.py` exercises the routes via `APIClient`.
Verified today: `python manage.py check --settings=netlab.settings.dev` passes.

**services/api/apps/labs/tests/test_lab_crud.py** — new file (item 5).
Pattern: `from django.test import TestCase`, `from rest_framework.test import APIClient`,
`from apps.accounts.models import User`, `from apps.labs.models import Lab`; use
`client.force_authenticate(user=...)`.
Verified today: the directory `apps/labs/tests/` exists with `__init__.py`.

### Frontend

**apps/web/src/lib/lab-api.ts** — new (item 6). Mirrors `apps/web/src/lib/simulation-api.ts`
(import `apiFetch` from `./api`; paths under `/labs/...`).
Test: none (no frontend test runner); gate is `npm run build`.
Verified today: `simulation-api.ts` compiles; `npm run build` succeeds on the current tree.

**apps/web/src/app/(dashboard)/labs/page.tsx** — server component exporting `metadata`,
defines `LABS`/`LabCard`/helpers, renders header + stats + Available + Coming soon (item 7).
Insert `<MyLabsSection />` after the header; keep the rest verbatim.
Test: `npm run build`.
Verified today: `npm run build` passes (static page compiles).

**apps/web/src/app/(dashboard)/labs/MyLabsSection.tsx** — new `"use client"` (item 7).
Uses `listLabs`/`deleteLab` from `@/lib/lab-api`, `Card`/`Button` from `@/components/ui`,
`Link` from `next/link`.
Test: `npm run build`.
Verified today: UI components exist at `apps/web/src/components/ui/`.

**apps/web/src/components/labs/workspace/SaveLabDialog.tsx** — new (item 8).
Pattern: `apps/web/src/components/labs/workspace/NodeConfigPopup.tsx` (overlay + modal +
fields + Enter/Esc). Same inline-style light theme.
Test: `npm run build`.
Verified today: `NodeConfigPopup.tsx` compiles.

**apps/web/src/components/labs/workspace/WorkspaceToolbar.tsx** — `WorkspaceToolbarProps`
interface + `Btn` helper (item 9). Add the new props and 4 buttons; replace the hardcoded
"Untitled Lab" with `currentLabName ?? 'Untitled Lab'`.
Test: `npm run build`.
Verified today: compiles; used by the workspace page.

**apps/web/src/app/(dashboard)/labs/workspace/page.tsx** — `"use client"` workspace (item 9).
Add `currentLabId`/`currentLabName`/`saveDialog` state, `?lab=` load via `getLab`, Save/SaveAs/
Open/New handlers, render `<SaveLabDialog>`. Keep all existing sim/canvas logic.
Test: `npm run build`.
Verified today: compiles; `convertFlowToTopology` + sessionStorage logic intact.

**apps/web/src/app/(dashboard)/dashboard/page.tsx** — server component exporting `metadata`
(item 10). Replace the body with `<DashboardClient />`.
**apps/web/src/app/(dashboard)/dashboard/DashboardClient.tsx** — new `"use client"` (item 10).
Uses `listLabs`, the existing `Card`/`Badge` components, lucide icons, `Link`.
Test: `npm run build`.
Verified today: dashboard compiles; `npm run build` passes.
