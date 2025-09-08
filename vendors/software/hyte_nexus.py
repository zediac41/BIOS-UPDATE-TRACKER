# vendors/software/hyte_nexus.py
# HYTE Nexus
from __future__ import annotations
import re, datetime as dt
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

VER_RX = re.compile(r"(?i)\b(?:Nexus|Version|v)\s*[:\-]?\s*(v?\d+(?:\.\d+){1,3}\w*)")
DATE_RXES = [
    re.compile(r"\b(20\d{2})[-/\.](\d{1,2})[-/\.](\d{1,2})\b"),
    re.compile(r"(?i)\b([A-Za-z]{3,9})\s+(\d{1,2}),\s*(20\d{2})\b"),
]
_MONTH = {m.lower():i for i,m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"],1)}
_MONTH.update({a.lower():i for a,i in zip(["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], range(1,13))})

def _iso(text:str)->str|None:
    for rx in DATE_RXES:
        m = rx.search(text)
        if not m: continue
        if rx.pattern.startswith(r"\b(20"):
            y,mo,d = map(int,m.groups()); return f"{y:04d}-{mo:02d}-{d:02d}"
        mon = _MONTH.get(m.group(1).lower()); d=int(m.group(2)); y=int(m.group(3))
        if mon: return f"{y:04d}-{mon:02d}-{d:02d}"
    return None

def fetch_latest(name:str, url:str)->dict:
    try:
        r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
    except Exception as e:
        return {"ok":False,"version":None,"date":None,"error":f"GET failed: {e}"}
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n", strip=True)

    ver = None
    m = VER_RX.search(text)
    if m: ver = m.group(1)
    date = _iso(text)
    ok = bool(ver)
    return {"ok":ok,"version":ver,"date":date,"error":None if ok else "version not found"}
