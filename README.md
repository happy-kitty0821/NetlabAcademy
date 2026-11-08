# NetLab Academy

An independent, browser-based networking education platform for CCNA and CCNP
learners. Combines a software network simulator, visual topology labs and a
structured examination engine.

> This is not affiliated with Cisco Systems. The simulator is an original
> software model; it does not execute Cisco IOS or claim to be Cisco Packet Tracer.

---

## Repository layout

```
netlab-academy/
├── apps/
│   └── web/                  # Next.js 15 + TypeScript frontend
├── services/
│   └── api/                  # Django 5.1 + DRF backend
├── packages/
│   └── simulator-core/       # Standalone Python simulation engine
├── docs/
│   ├── adr/                  # Architecture decision records
│   └── protocols/            # Protocol behaviour notes
├── .kiro/
│   ├── specs/                # Feature specs (requirements / design / tasks)
│   └── steering/             # Project-wide constraints for Kiro
└── backend/                  # Legacy Django scaffold (to be removed)
```

---

## Getting started

### Prerequisites

| Tool | Version |
|------|---------|
| Python | ≥ 3.12 |
| Node.js | ≥ 20 |
| PostgreSQL | ≥ 15 |

### Simulator core (no database needed)

```sh
cd packages/simulator-core
pip install -e ".[test]"
python -m pytest tests/ -v --cov=simulator_core
```

### Backend API

```sh
cd services/api
python -m venv venv
# Windows: venv\Scripts\activate  |  macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DB credentials and SECRET_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

API available at: `http://localhost:8000/`
Admin panel: `http://localhost:8000/admin/`
Health check: `http://localhost:8000/health/`

### Frontend

```sh
cd apps/web
npm install
cp .env.local.example .env.local
npm run dev
```

App available at: `http://localhost:3000/`

---

## Development status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 — Simulator PoC | ✅ Complete | Two-host topology, ARP, ICMP, deterministic replay |
| Phase 1 — Platform scaffold | 🔄 In progress | Django API, Next.js frontend, auth skeleton |
| Phase 1 — Auth & RBAC | ⏳ Pending | Custom user model wired, JWT endpoints ready |
| Phase 2 — Exam engine | ⏳ Pending | |
| Phase 3 — Simulator UI | ⏳ Pending | |

---

## Key decisions

- **Modular monolith**: one Django project with domain apps (`accounts`,
  `courses`, `labs`). No microservices without a measured need.
- **Simulator independence**: `packages/simulator-core` has zero runtime
  dependencies outside the Python stdlib. It is importable and testable
  without Django, PostgreSQL, or the web frontend.
- **PostgreSQL from day one**: SQLite is not used in `services/api/`.
- **JWT authentication**: access + refresh token pair via `djangorestframework-simplejwt`.
- **Dark, technical UI**: the frontend uses a purpose-built dark palette that
  reflects a networking tool, not a generic SaaS template.

See `docs/adr/` for formal architecture decision records as they are written.
