"""Start every service (hub + 8 agents). Ctrl+C stops everything. Owner: A.

Usage:
  python scripts/run_all.py            # start
  python scripts/run_all.py --seed     # (re)create demo history first
  python scripts/run_all.py --only hub sales   # start a subset
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common import config, crypto  # noqa: E402


def main() -> None:
    args = sys.argv[1:]
    if not crypto.keys_exist():
        crypto.generate_keys()
        print("[run_all] keys generated")
    if "--seed" in args or not (config.DATA_DIR / "business.db").exists():
        from data import seed
        seed.main()
        for f in ("rules.json", "audit.db"):        # clean demo: no vaccine approved yet, fresh audit chain
            (config.DATA_DIR / f).unlink(missing_ok=True)
        try:
            from data import seed_trust  # B's synthetic trust history (optional)
            seed_trust.main()
        except ImportError:
            pass
    only = args[args.index("--only") + 1:] if "--only" in args else list(config.APPS)
    import socket
    busy = []
    for name in only:
        with socket.socket() as s:
            if s.connect_ex((config.HOST, config.port(name))) == 0:
                busy.append(f"{name}:{config.port(name)}")
    if busy:
        print(f"[run_all] ports already in use: {', '.join(busy)}. Another run_all is running? "
              f"Stop it, or set PORT_BASE in .env (example 8100).")
        sys.exit(1)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1"}
    procs: list[tuple[str, subprocess.Popen]] = []
    # agents first, hub last
    for name in sorted(only, key=lambda n: n == "hub"):
        cmd = [sys.executable, "-m", "uvicorn", config.APPS[name], "--host", config.HOST,
               "--port", str(config.port(name)), "--log-level", "warning"]
        procs.append((name, subprocess.Popen(cmd, cwd=ROOT, env=env)))
        print(f"[run_all] {name:9s} -> {config.url(name)}")
    time.sleep(2.5)
    print("\n  Demo page   :", config.url("hub") + "/demo")
    print("  Dashboard   :", config.url("hub") + "/dashboard")
    print("  Customer    :", config.url("hub") + "/client")
    print("  Partner demo:", config.url("hub") + "/partner-demo")
    print("\n  Ctrl+C to stop.\n")
    try:
        while True:
            for name, p in procs:
                if p.poll() is not None:
                    print(f"[run_all] {name} exited with code {p.returncode}, restarting")
                    cmd = [sys.executable, "-m", "uvicorn", config.APPS[name], "--host", config.HOST,
                           "--port", str(config.port(name)), "--log-level", "warning"]
                    procs[procs.index((name, p))] = (name, subprocess.Popen(cmd, cwd=ROOT, env=env))
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[run_all] stopping...")
    finally:
        for _, p in procs:
            try:
                if os.name == "nt":
                    p.terminate()
                else:
                    p.send_signal(signal.SIGINT)
            except Exception:
                pass
        for _, p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
