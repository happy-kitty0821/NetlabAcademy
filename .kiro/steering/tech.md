---
inclusion: always
---
# Technology steering — NetLab Academy

## Approved baseline
- Frontend: Next.js + TypeScript.
- Backend: Django + Django REST Framework.
- Database: PostgreSQL.
- Background jobs: Celery + Redis.
- Topology editor: React Flow / XYFlow.
- Terminal UI: xterm.js.
- Simulation core: Python package, separated from Django ORM and UI code.
- Realtime transport: choose Django Channels or a dedicated gateway through an ADR after a proof of concept.

## Rules
- Pin dependencies and use lockfiles. Verify current compatibility before adding/upgrading packages.
- Prefer a modular monolith for the education platform; do not create microservices without a measured need.
- Keep simulator core deterministic, typed, independently testable and free of web-framework dependencies.
- Never execute arbitrary user code, shell commands or `eval` input in the simulator.
- Do not connect simulated networks to host interfaces or real external networks in the initial release.
- All API authorization must be enforced server-side.
- Write automated tests for domain logic, permissions and simulator behaviour.
- Record material architectural changes as ADRs before implementation.
- Do not silently introduce alternative frameworks or infrastructure products.
