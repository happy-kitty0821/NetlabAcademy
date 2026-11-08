#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_project.py -- NetLab Academy development launcher
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

# ── Windows UTF-8 console fix ─────────────────────────────────────────────────
# Must run before any print() call. Windows cmd/PowerShell default to cp1252;
# wrap stdout/stderr to UTF-8 so box characters and arrows render correctly.
if sys.platform == "win32":
    import io as _io
    sys.stdout = _io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    sys.stderr = _io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
API_DIR = ROOT / "services" / "api"
WEB_DIR = ROOT / "apps" / "web"

# Virtual-environment paths differ between Windows and Unix.
# We probe three locations in order of preference:
#   1. services/venv/     — created manually beside the api directory
#   2. services/api/venv/ — created by a previous run of this script
#
# If neither exists, ensure_venv() creates services/api/venv/ automatically.
IS_WINDOWS = platform.system() == "Windows"

_VENV_CANDIDATES = [
    API_DIR.parent / "venv",   # services/venv/
    API_DIR / "venv",          # services/api/venv/
]


def _resolve_venv_dir() -> Path:
    for candidate in _VENV_CANDIDATES:
        if candidate.exists():
            return candidate
    # Neither exists yet — default creation path.
    return _VENV_CANDIDATES[1]  # services/api/venv/


def _venv_bin(venv: Path, name: str) -> Path:
    """Return the path to an executable inside a venv directory."""
    suffix = ".exe" if IS_WINDOWS else ""
    sub = "Scripts" if IS_WINDOWS else "bin"
    return venv / sub / (name + suffix)


# Resolved lazily so ensure_venv() can update VENV_DIR after creation.
VENV_DIR    = _resolve_venv_dir()
VENV_PYTHON = _venv_bin(VENV_DIR, "python")
VENV_PIP    = _venv_bin(VENV_DIR, "pip")

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
    line = "-" * width
    print()
    print(_c("1;34", line))
    print(_c("1;34", f"  {msg}"))
    print(_c("1;34", line))


# ── Subprocess helpers ─────────────────────────────────────────────────────────
#
# On Windows, npm/npx/node are .cmd shims and cannot be found by subprocess
# unless shell=True is set or the full .cmd path is used.
# We set shell=True on Windows for all subprocess calls to handle this uniformly.

def _shell() -> bool:
    """True on Windows — required so .cmd shims (npm, npx) are found."""
    return IS_WINDOWS


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> int:
    """Run a command, stream output, and return the exit code."""
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(cmd, cwd=cwd, env=merged_env, shell=_shell())
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
    return subprocess.Popen(cmd, cwd=cwd, env=merged_env, shell=_shell())


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
        ["node", "--version"], capture_output=True, text=True, shell=IS_WINDOWS
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

    global VENV_DIR, VENV_PYTHON, VENV_PIP

    # Re-resolve in case the user created one since the script started.
    VENV_DIR    = _resolve_venv_dir()
    VENV_PYTHON = _venv_bin(VENV_DIR, "python")
    VENV_PIP    = _venv_bin(VENV_DIR, "pip")

    info(f"Using venv: {VENV_DIR}")

    if not VENV_DIR.exists():
        info(f"Creating venv at {VENV_DIR} ...")
        run_or_die([sys.executable, "-m", "venv", str(VENV_DIR)],
                   label="create venv")
        # Re-resolve paths now that the venv exists.
        VENV_PYTHON = _venv_bin(VENV_DIR, "python")
        VENV_PIP    = _venv_bin(VENV_DIR, "pip")
        ok("venv created")
    else:
        ok(f"venv found at {VENV_DIR}")

    info("Installing / updating Python dependencies ...")
    run_or_die(
        [str(VENV_PYTHON), "-m", "pip", "install",
         "-r", str(API_DIR / "requirements.txt"), "-q"],
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


# ── Port conflict detection ────────────────────────────────────────────────────

def kill_port(port: int) -> bool:
    """
    If *port* is occupied, kill the process holding it.
    Returns True if something was killed, False if the port was free.
    Works on both Windows and Unix.
    """
    import socket as _socket

    # Quick check — is the port actually in use?
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
        return False  # port is free
    except OSError:
        s.close()

    # Port is in use — find and kill the process.
    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, shell=True
            )
            for line in result.stdout.strip().splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/F"],
                        shell=True, capture_output=True
                    )
                    return True
        except Exception:
            pass
    else:
        try:
            subprocess.run(
                ["fuser", "-k", f"{port}/tcp"],
                capture_output=True, shell=True
            )
            return True
        except Exception:
            pass

    return False


def ensure_port_free(port: int, name: str) -> None:
    """Kill any process holding *port*, or warn if it cannot be freed."""
    if kill_port(port):
        warn(f"Killed stale process on port {port} ({name})")
        time.sleep(0.5)
    # Verify it is actually free now.
    import socket as _socket
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
    except OSError:
        s.close()
        err(f"Port {port} is in use and could not be freed. "
            f"Close the application using it and try again.")
        sys.exit(1)


# ── Start servers ──────────────────────────────────────────────────────────────

def start_servers() -> None:
    header("Starting servers")

    # ── Free ports before binding ───────────────────────────────────────────────
    ensure_port_free(8000, "Django API")
    ensure_port_free(3000, "Next.js")

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
    print(_c("1;32", "  +------------------------------------------+"))
    print(_c("1;32", "  |  NetLab Academy is running               |"))
    print(_c("1;32", "  |                                          |"))
    print(_c("1;32", f"  |  Frontend  ->  http://localhost:3000     |"))
    print(_c("1;32", f"  |  API       ->  http://localhost:8000     |"))
    print(_c("1;32", f"  |  Admin     ->  http://localhost:8000/admin|"))
    print(_c("1;32", f"  |  Health    ->  http://localhost:8000/health|"))
    print(_c("1;32", "  |                                          |"))
    print(_c("1;32", "  |  Press Ctrl+C to stop all servers        |"))
    print(_c("1;32", "  +------------------------------------------+"))
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
        description="NetLab Academy - start the full development stack"
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
