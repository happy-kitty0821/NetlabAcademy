---
inclusion: always
---
# Repository structure steering — NetLab Academy

- Follow the repository layout in `PROJECT_SPEC.md` section 14.
- Keep Next.js UI in `apps/web/`.
- Keep Django API and domain modules in `services/api/`.
- Keep the simulation runtime in `services/simulator/` and reusable simulation logic in `packages/simulator-core/`.
- Keep versioned topology/lab schemas in `packages/lab-schema/`.
- Keep architecture decision records in `docs/adr/` and protocol behaviour notes in `docs/protocols/`.
- Keep business logic out of oversized views, serializers and React components.
- Use explicit types, clear names, small modules and documented public interfaces.
- Add tests beside the relevant package/app test suite; do not create one unstructured global test directory.
- Do not create all target folders in advance. Add directories when an approved feature needs them.
