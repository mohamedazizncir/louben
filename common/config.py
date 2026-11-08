"""Shared configuration: ports, paths, env."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
KEYS_DIR = ROOT / "keys"
STATIC_DIR = ROOT / "hub" / "static"

DATA_DIR.mkdir(exist_ok=True)
KEYS_DIR.mkdir(exist_ok=True)

HOST = os.getenv("HOST", "127.0.0.1")
PORT_BASE = int(os.getenv("PORT_BASE", "8000"))

# name -> port offset
SERVICES: dict[str, int] = {
    "hub": 0,
    "sales": 1,
    "intel": 2,
    "payment": 3,
    "analyst": 4,
    "strategy": 5,
    "security": 6,
    "redteam": 7,
    "gate": 8,
}

# uvicorn import path for each service
APPS: dict[str, str] = {
    "hub": "hub.main:app",
    "sales": "agents.sales.main:app",
    "intel": "agents.intel.main:app",
    "payment": "agents.payment.main:app",
    "analyst": "agents.analyst.main:app",
    "strategy": "agents.strategy.main:app",
    "security": "agents.security.main:app",
    "redteam": "agents.redteam.main:app",
    "gate": "gate.main:app",
}

AGENTS = [n for n in SERVICES if n != "hub"]

LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile").strip()
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "8"))

HUMAN_PIN = os.getenv("HUMAN_PIN", "2026")
STRIPE_TEST_KEY = os.getenv("STRIPE_TEST_KEY", "").strip()


def port(name: str) -> int:
    return PORT_BASE + SERVICES[name]


def url(name: str) -> str:
    return f"http://{HOST}:{port(name)}"


def load_json(name: str) -> dict | list:
    """Load a JSON file from config/ (fresh read, so edits apply live)."""
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def catalog() -> list[dict]:
    return load_json("catalog.json")["products"]  # type: ignore[index]


def product(product_id: str) -> dict | None:
    for p in catalog():
        if p["product_id"] == product_id:
            return p
    return None
