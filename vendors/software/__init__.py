# vendors/software/__init__.py
from __future__ import annotations
from importlib import import_module

# Map IDs in config.yml → module path (keep these ids in your config)
_ID_TO_MODULE = {
    "masterplus": "vendors.software.masterplus",
    "hyte_nexus": "vendors.software.hyte_nexus",
    "kanali": "vendors.software.kanali",
    "lconnect3": "vendors.software.lconnect3",
    "gigabytecs": "vendors.software.gigabytecs",
    "msicenter": "vendors.software.msicenter",
    "armourycrate": "vendors.software.armourycrate",
}

def fetch(id_: str, name: str, url: str) -> dict:
    """
    Returns dict: { ok: bool, version: str|None, date: None, error: str|None }
    (We no longer surface a date for software tiles.)
    """
    mod_name = _ID_TO_MODULE.get(id_)
    if not mod_name:
        return {"ok": False, "version": None, "date": None, "error": f"unknown id '{id_}'"}
    try:
        mod = import_module(mod_name)
    except Exception as e:
        return {"ok": False, "version": None, "date": None, "error": f"import failed: {e}"}
    try:
        return mod.fetch_latest(name, url)
    except Exception as e:
        return {"ok": False, "version": None, "date": None, "error": f"scrape failed: {e}"}
