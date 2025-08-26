import argparse, requests, yaml
from typing import Dict, Any
from vendors import PARSERS
from storage import load_state, save_state
from notify import notify

def fetch(url: str) -> str:
  headers = {"User-Agent": "Mozilla/5.0 (BIOS-Tracker/1.0)"}
  r = requests.get(url, headers=headers, timeout=45)
  r.raise_for_status()
  return r.text

def check_board(board: Dict[str, Any]):
  name = board.get("name", "Unknown Board")
  vendor = (board.get("vendor") or "").lower()
  url = board.get("url")
  selectors = board.get("selectors") or {}
  if vendor not in PARSERS:
    raise ValueError(f"Unsupported vendor '{vendor}' for {name}")
  html = fetch(url)
  data = PARSERS[vendor].parse(url, html, selectors=selectors)
  data["name"] = name
  data["vendor"] = vendor
  return data

def run(config_path: str, verbose=False):
  with open(config_path, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)
  state = load_state()
  changed = []

  for board in cfg.get("boards", []):
    try:
      latest = check_board(board)
      key = latest["name"]
      prev = state.get(key, {})
      if verbose:
        print(f"[{key}] latest: {latest} | prev: {prev}")
      if latest.get("version") and latest.get("version") != prev.get("version"):
        changed.append((prev, latest))
        state[key] = latest
      else:
        state.setdefault(key, latest)
    except Exception as e:
      err = f"[ERROR] {board.get('name')} ({board.get('vendor')}): {e}"
      print(err)
      notify(err)

  if changed:
    save_state(state)
    for prev, latest in changed:
      msg = f"🧪 BIOS update detected for **{latest['name']}** ({latest['vendor']})\n"
      msg += f"- Version: `{latest.get('version')}`"
      if prev.get("version"):
        msg += f" (prev `{prev.get('version')}`)"
      if latest.get("date"):
        msg += f"\n- Release date: {latest['date']}"
      msg += f"\n- Page: {latest.get('url')}"
      notify(msg)
  else:
    save_state(state)
    if verbose:
      print("No changes detected.")

if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("--config", required=True)
  ap.add_argument("--verbose", action="store_true")
  args = ap.parse_args()
  run(args.config, verbose=args.verbose)
