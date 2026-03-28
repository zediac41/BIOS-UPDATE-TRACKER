 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/bios_tracker.py b/bios_tracker.py
index 898834bcce63f8832728b4a314d3cc5c05527ca6..77fc4d8b7963f9e3cd16cec1a8952b4dea55ef00 100644
--- a/bios_tracker.py
+++ b/bios_tracker.py
@@ -1,38 +1,39 @@
 #!/usr/bin/env python3
 # -*- coding: utf-8 -*-
 
 import json
 import yaml
 import datetime
 import html
-import time
 import sys
 import re
 import csv
 from pathlib import Path
 from zoneinfo import ZoneInfo
+from concurrent.futures import ThreadPoolExecutor, as_completed
+from typing import Callable
 
 DEFAULT_FORM_EMBED = "https://docs.google.com/forms/d/e/1FAIpQLSeeu3yf7GYgZbPWPLX_iDzg_ulEfe7FdgiW66Co3QHUKaG7Cw/viewform?embedded=true"
 DEFAULT_SHEET_ID   = "1O6A9AI0wMu5vWrtKgvwFAxJFEGu6aznUal2khv_oukI"
 DEFAULT_GID        = "1502059609"
 
 # -------------------------------------------------------------------
 # Vendor scrapers (your existing modules)
 # Each module must expose: latest_two(model_name, override_url=None) -> dict
 # -------------------------------------------------------------------
 from vendors import asus, msi, gigabyte, asrock
 
 VENDOR_FUNCS = {
     "asus": asus.latest_two,
     "msi": msi.latest_two,
     "gigabyte": gigabyte.latest_two,
     "asrock": asrock.latest_two,
 }
 
 # -------------------------------------------------------------------
 # Vendor scrapers (your existing modules)
 # -------------------------------------------------------------------
 from vendors.software import fetch as fetch_software
 
 # -------------------------------------------------------------------
 # Config
@@ -609,74 +610,84 @@ def _google_comments_block(cfg: dict) -> str:
 # Main
 # -------------------------------------------------------------------
 def main():
     cfg = load_config()
     vendors = (cfg.get("vendors") or {})
 
     # Manual issue flags (optional)
     issue_names: set[str] = set(map(str, (cfg.get("issues") or [])))
     for vendor_key, boards in vendors.items():
         for b in boards or []:
             if isinstance(b, dict) and b.get("issue"):
                 name = str(b.get("name") or b.get("model") or "").strip()
                 if name:
                     issue_names.add(name)
 
     # Optional notes
     notes_text = (cfg.get("notes") or "").strip()
 
     results: list[dict] = []
 
     def normalize_model(item):
         if isinstance(item, dict):
             return item.get("name") or item.get("model") or "", item.get("url")
         return str(item), None
 
-    # Scrape vendors
+    # Scrape vendors concurrently to reduce total network wait time.
+    jobs: list[tuple[str, Callable[..., dict], str, str | None]] = []
     for vkey, models in vendors.items():
         func = VENDOR_FUNCS.get(vkey.lower())
         if not func:
             print(f"Unknown vendor key: {vkey}", file=sys.stderr)
             continue
         for item in (models or []):
             model, override_url = normalize_model(item)
-            print(f"[{vkey}] {model} ...", file=sys.stderr)
+            jobs.append((vkey, func, model, override_url))
+
+    def scrape_job(vkey: str, func, model: str, override_url: str | None) -> dict:
+        print(f"[{vkey}] {model} ...", file=sys.stderr)
+        try:
             try:
-                res = func(model, override_url=override_url)
+                return func(model, override_url=override_url)
             except TypeError:
-                res = func(model)
-            except Exception as e:
-                res = {
-                    "vendor": vkey.upper(),
-                    "model": model,
-                    "url": override_url or "",
-                    "versions": [],
-                    "ok": False,
-                    "error": str(e),
-                }
-            results.append(res)
-            time.sleep(0.3)
+                return func(model)
+        except Exception as e:
+            return {
+                "vendor": vkey.upper(),
+                "model": model,
+                "url": override_url or "",
+                "versions": [],
+                "ok": False,
+                "error": str(e),
+            }
+
+    # Keep this conservative by default; allow config override.
+    max_workers = max(1, int(cfg.get("scrape_workers") or 4))
+    with ThreadPoolExecutor(max_workers=max_workers) as pool:
+        futures = [pool.submit(scrape_job, vkey, func, model, override_url) for vkey, func, model, override_url in jobs]
+        for future in as_completed(futures):
+            results.append(future.result())
 
     # Sort cards by current release date (newest first)
     results = _sort_results_newest_first(results)
 
     # Build cards
     today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
     cards_html = "\n".join(build_card(r, issue_names=issue_names, today=today) for r in results)
 
     # Comments section (Google Form + Sheet)
     comments_html = _google_comments_block(cfg)
 
     # Write docs
     docs = Path("docs"); docs.mkdir(parents=True, exist_ok=True)
     idx = docs / "index.html"
     data_path = docs / "data.json"
 
     now = datetime.datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M %Z")
 
     header_html = f"""
 <header class="page-header">
   <h1>Motherboard BIOS Tracker</h1>
   <div class="search">
     <input type="search" id="search-input" placeholder="Search model…" aria-label="Search models" />
   </div>
   <div class="toolbar">
 
EOF
)
