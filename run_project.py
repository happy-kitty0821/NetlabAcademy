#!/usr/bin/env python3
"""
run_project.py — NetLab Academy development launcher
======================================================

Platform-independent startup script. Run from the repository root:

    python run_project.py [--skip-pull] [--skip-frontend-build] [--skip-migrate]

What it does, in order:
  1. Checks for a Python venv under services/api/venv and installs/updates deps.
  2. Checks for Node.js and installs frontend npm deps if node_modules is missing.
  3. Pulls the latest changes from git (unless --skip-pull).
  4. Runs Django makemigrations + migrate (unless --skip-migrate).
  5. Builds the Next.js production bundle (unless --skip-frontend-build).
  6. Starts the Django dev server (port 8000) in a background process.
  7. Starts the Next.js server (port 3000) in a background process.
  8. Waits — Ctrl+C shuts both servers down cleanly.

Requirements:
  - Python 3.12+
  - Node.js 20+
  - git

No external Python packages are needed to run this script itself.
"""

import argparse
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
API_DIR = ROOT / "services" / "api"
WEB_DIR = ROOT / "apps" / "web"

# Virtual-environment paths differ between Windows and Unix.
IS_WINDOWS = platform.system() == "Windows"
VENV_DIR = API_DIR / "venv"
VENV_PYTHON = VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / (
    "python.exe" if IS_WINDOWS else "python"
)
VENV_PIP = VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / (
    "pip.exe" if IS_WINDOWS else "pip"
)

# ── ANSI colours (disabled on Windows unless the terminal supports them) ──────

USE_COLOR = not IS_WINDOWS or os.environ.get("WT_SESSION")  # Windows Terminal


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def info(msg: str) -> None:
    print(_c("36", f"[netlab] {msg}"))


def ok(msg: str) -> None:
    print(_c("32", f"[  OK  ] {msg}"))


def warn(msg: str) -> None:
    print(_c("33", f"[ WARN ] {msg}"))


def err(msg: str) -> None:
    print(_c("31", f"[ ERR  ] {msg}"), file=sys.stderr)


def header(msg: str) -> None:
    width = 60
    print()
    print(_c("1;34", "─" * width))
    print(_c("1;34", f"  {msg}"))
    print(_c("1;34", "─" * width))


# ── Subprocess helpers ─────────────────────────────────────────────────────────

def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> int:
    """Run a command, stream output, and return the exit code."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(cmd, cwd=cwd, env=merged_env)
    return result.returncode


def run_or_die(cmd: list[str], cwd: Path | None = None, env: dict | None = None,
               label: str = "") -> None:
    """Run a command; exit the script if it fails."""
    code = run(cmd, cwd=cwd, env=env)
    if code != 0:
        err(f"Command failed (exit {code}): {' '.join(cmd)}")
        if label:
            err(f"Step: {label}")
        sys.exit(code)


def spawn(cmd: list[str], cwd: Path | None = None,
          env: dict | None = None) -> subprocess.Popen:
    """Launch a long-running process in the background."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.Popen(cmd, cwd=cwd, env=merged_env)


# ── Prerequisite checks ────────────────────────────────────────────────────────

def check_git() -> None:
    info("Checking git ...")
    if run(["git", "--version"], cwd=ROOT) != 0:
        err("git is not installed or not on PATH.")
        sys.exit(1)
    ok("git found")


def check_node() -> None:
    info("Checking Node.js ...")
    result = subprocess.run(
        ["node", "--version"], capture_output=True, text=True
    )
    if result.returncode != 0:
        err("Node.js is not installed or not on PATH. Install from https://nodejs.org/")
        sys.exit(1)
    ok(f"Node.js {result.stdout.strip()} found")


def check_python_version() -> None:
    if sys.version_info < (3, 12):
        err(f"Python 3.12+ required. Found {sys.version}")
        sys.exit(1)
    ok(f"Python {sys.version.split()[0]} OK")


# ── Virtual environment ────────────────────────────────────────────────────────

def ensure_venv() -> None:
    """Create the venv if it does not exist, then install/sync requirements."""
    header("Python virtual environment")

    if not VENV_DIR.exists():
        info(f"Creating venv at {VENV_DIR} ...")
        run_or_die([sys.executable, "-m", "venv", str(VENV_DIR)],
                   label="create venv")
        ok("venv created")
    else:
        ok("venv already exists")

    info("Installing / updating Python dependencies ...")
    run_or_die(
        [str(VENV_PIP), "install", "-r", str(API_DIR / "requirements.txt"), "-q"],
        label="pip install",
    )
    ok("Python dependencies up to date")


# ── Git pull ───────────────────────────────────────────────────────────────────

def git_pull() -> None:
    header("Git — pulling latest changes")

    # Check for a remote first.
    result = subprocess.run(
        ["git", "remote"],
        capture_output=True, text=True, cwd=ROOT
    )
    if not result.stdout.strip():
        warn("No git remote configured — skipping pull.")
        return

    # Stash any local uncommitted changes so pull doesn't fail.
    stash_result = subprocess.run(
        ["git", "stash"],
        capture_output=True, text=True, cwd=ROOT
    )
    stashed = "No local changes" not in stash_result.stdout

    code = run(["git", "pull", "--ff-only", "origin", "main"], cwd=ROOT)
    if code != 0:
        warn("git pull failed or nothing to pull — continuing with local state.")
    else:
        ok("Repository is up to date")

    if stashed:
        info("Restoring stashed changes ...")
        run(["git", "stash", "pop"], cwd=ROOT)


# ── Django migrations ──────────────────────────────────────────────────────────

def run_migrations() -> None:
    header("Django — migrations")

    django_env = {"DJANGO_SETTINGS_MODULE": "netlab.settings.dev"}

    info("Running makemigrations ...")
    run_or_die(
        [str(VENV_PYTHON), "manage.py", "makemigrations", "--no-input"],
        cwd=API_DIR,
        env=django_env,
        label="makemigrations",
    )

    info("Running migrate ...")
    run_or_die(
        [str(VENV_PYTHON), "manage.py", "migrate", "--no-input"],
        cwd=API_DIR,
        env=django_env,
        label="migrate",
    )
    ok("Database schema is up to date")


# ── Frontend ───────────────────────────────────────────────────────────────────

def ensure_node_modules() -> None:
    """Install npm deps if node_modules is missing or package.json changed."""
    node_modules = WEB_DIR / "node_modules"
    if not node_modules.exists():
        info("node_modules not found — running npm install ...")
        run_or_die(["npm", "install"], cwd=WEB_DIR, label="npm install")
        ok("npm packages installed")
    else:
        ok("node_modules present — skipping install")


def build_frontend() -> None:
    header("Next.js — production build")

    ensure_node_modules()

    info("Building Next.js production bundle ...")
    run_or_die(["npm", "run", "build"], cwd=WEB_DIR, label="next build")
    ok("Frontend build complete")


# ── Start servers ──────────────────────────────────────────────────────────────

def start_servers() -> None:
    header("Starting servers")

    django_env = {
        "DJANGO_SETTINGS_MODULE": "netlab.settings.dev",
        "PYTHONUNBUFFERED": "1",
    }

    info("Starting Django API on http://localhost:8000 ...")
    django_proc = spawn(
        [str(VENV_PYTHON), "manage.py", "runserver", "0.0.0.0:8000"],
        cwd=API_DIR,
        env=django_env,
    )

    # Give Django a moment to bind before starting Next.js.
    time.sleep(1.5)

    info("Starting Next.js server on http://localhost:3000 ...")
    next_proc = spawn(
        ["npm", "run", "start"],
        cwd=WEB_DIR,
    )

    print()
    print(_c("1;32", "  ┌─────────────────────────────────────────┐"))
    print(_c("1;32", "  │  NetLab Academy is running               │"))
    print(_c("1;32", "  │                                          │"))
    print(_c("1;32", f"  │  Frontend  →  http://localhost:3000      │"))
    print(_c("1;32", f"  │  API       →  http://localhost:8000      │"))
    print(_c("1;32", f"  │  Admin     →  http://localhost:8000/admin│"))
    print(_c("1;32", f"  │  Health    →  http://localhost:8000/health│"))
    print(_c("1;32", "  │                                          │"))
    print(_c("1;32", "  │  Press Ctrl+C to stop all servers        │"))
    print(_c("1;32", "  └─────────────────────────────────────────┘"))
    print()

    # ── Wait and handle shutdown ───────────────────────────────────────────────

    procs = [django_proc, next_proc]

    def shutdown(signum=None, frame=None):
        print()
        info("Shutting down servers ...")
        for p in procs:
            try:
                if IS_WINDOWS:
                    p.terminate()
                else:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        ok("All servers stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Poll processes — exit if either crashes.
    while True:
        time.sleep(2)
        for p in procs:
            ret = p.poll()
            if ret is not None:
                err(f"A server process exited unexpectedly (pid={p.pid}, code={ret})")
                shutdown()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="NetLab Academy — start the full development stack"
    )
    parser.add_argument(
        "--skip-pull",
        action="store_true",
        help="Skip git pull (useful offline or on feature branches)",
    )
    parser.add_argument(
        "--skip-frontend-build",
        action="store_true",
        help="Skip the Next.js production build (use when frontend hasn't changed)",
    )
    parser.add_argument(
        "--skip-migrate",
        action="store_true",
        help="Skip makemigrations + migrate",
    )
    args = parser.parse_args()

    header("NetLab Academy — startup")
    info(f"Root: {ROOT}")
    info(f"Platform: {platform.system()} {platform.machine()}")

    # ── Prerequisites ──────────────────────────────────────────────────────────
    check_python_version()
    check_git()
    check_node()

    # ── Setup ──────────────────────────────────────────────────────────────────
    ensure_venv()

    if not args.skip_pull:
        git_pull()
    else:
        warn("Skipping git pull (--skip-pull)")

    if not args.skip_migrate:
        run_migrations()
    else:
        warn("Skipping migrations (--skip-migrate)")

    if not args.skip_frontend_build:
        build_frontend()
    else:
        warn("Skipping frontend build (--skip-frontend-build)")
        ensure_node_modules()

    # ── Launch ─────────────────────────────────────────────────────────────────
    start_servers()


if __name__ == "__main__":
    main()
