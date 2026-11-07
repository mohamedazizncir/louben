"""Backup demo (acts 1, 2 and 5) if the microphone fails. Run it while /demo is on screen.

Usage: python scripts/demo_business.py [--fast]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from common import config  # noqa: E402

BASE = config.url("hub")
PAUSE = 0.8 if "--fast" in sys.argv else 3.0


def say(c, sid, text):
    print(f"\n  CUSTOMER > {text}")
    r = c.post(f"{BASE}/api/chat", json={"session_id": sid, "text": text, "channel": "voice"}).json()
    print(f"  AGENT    > {r.get('reply')}  [{r.get('stage')}]")
    time.sleep(PAUSE)
    return r


def main():
    c = httpx.Client(timeout=60)
    sid = f"demo-{int(time.time())}"
    print("ACT 1: sale by voice")
    say(c, sid, "Bonjour, je suis étudiant et je veux apprendre les agents IA")
    say(c, sid, "C'est trop cher pour moi, je peux payer en plusieurs fois ?")
    print("\nACT 2: payment with 3 signatures")
    say(c, sid, "D'accord, je prends")
    r = c.post(f"{BASE}/api/chat/end", json={"session_id": sid}).json()
    print(f"\n  INTEL    > objections={r['intel']['objections']} sentiment={r['intel']['sentiment']} segment={r['intel']['segment']}")
    time.sleep(PAUSE)
    print("\nACT 5: strategy recommendations")
    for rec in c.post(f"{BASE}/api/recommendations/run").json().get("items", []):
        print(f"  - {rec['title']}: {rec['rationale']}")


if __name__ == "__main__":
    main()
