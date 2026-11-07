"""Generate one Ed25519 key per identity + keys/registry.json. Owner: B after CP0.

Usage: python scripts/gen_keys.py [--force]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import crypto  # noqa: E402


def main(force: bool = False) -> None:
    crypto.generate_keys(force=force)
    print(f"keys ready in {crypto.KEYS_DIR} (trusted: {', '.join(crypto.IDENTITIES)}; untrusted: rogue)")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
