from __future__ import annotations
import json, os
from typing import Dict, Any

STATE_PATH = os.environ.get("STATE_PATH", "state/db.json")

def load_state() -> Dict[str, Any]:
  if not os.path.exists(STATE_PATH):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    return {}
  try:
    with open(STATE_PATH, "r", encoding="utf-8") as f:
      return json.load(f)
  except Exception:
    return {}

def save_state(state: Dict[str, Any]) -> None:
  os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
  with open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
