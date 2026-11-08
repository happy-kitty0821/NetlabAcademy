# NetLab Academy — API Service (`services/api/`)

Django 5.1 + Django REST Framework backend for the NetLab Academy platform.

## Setup

```sh
cd services/api

# Create and activate a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set DB credentials and SECRET_KEY

# Run migrations (requires PostgreSQL running)
python manage.py migrate

# Create a superuser
python manage.py createsuperuser

# Start the development server
python manage.py runserver
```

## Running tests

```sh
pytest
```

## API prefix

All routes: `/api/v1/`

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/auth/token/` | Obtain JWT access + refresh tokens |
| `POST /api/v1/auth/token/refresh/` | Refresh access token |
| `POST /api/v1/auth/register/` | Create a student account |
| `GET/PATCH /api/v1/auth/me/` | Get or update own profile |
| `GET /health/` | Liveness probe |

## Project layout

```
services/api/
├── manage.py
├── requirements.txt
├── .env.example
├── pytest.ini
├── netlab/                  # Django project package
│   ├── settings/
│   │   ├── base.py          # Shared settings
│   │   ├── dev.py           # Development overrides
│   │   └── prod.py          # Production overrides
│   ├── api/
│   │   ├── urls.py          # API v1 router
│   │   └── exception_handler.py
│   ├── urls.py              # Root URL conf
│   ├── wsgi.py
│   └── asgi.py
└── apps/
    ├── accounts/            # Custom user model, registration, profile
    ├── courses/             # Stub — see 02-courses-enrolment spec
    └── labs/                # Stub — see 07-lab-lifecycle spec
```
