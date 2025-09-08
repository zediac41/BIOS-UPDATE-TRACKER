# vendors/software/masterplus.py
# Cooler Master MasterPlus+ – extract the correct version (e.g., 1.9.6), ignore stray numbers like “USB 2.0”.

from __future__ import annotations
import re, requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Candidate version tokens (v optional). Accept 2–4 segments but we’ll SCORE 3+ segments higher.
VER_CAND_RX = re.compile(r"\bv?(\d+(?:\.\d+){1,3}(?:[a-z]\d*)?)\b", re.I)

# “Near” cues that usually surround the real version
NEAR_GOOD_RX = re.compile(r"(?i)(masterplus\+?|version|release|changelog|what'?s new|notes)")
# Context to avoid (things that often create false hits like “USB 2.0”, “Bluetooth 5.2”, etc.)
NEAR_BAD_RX  = re.compile(r"(?i)(usb|bluetooth|directx|\.net|pcie|opengl|hdmi|ghz|gen\s*\d|ddr\d)")

def _score_candidate(text: str, pos: int, token: str) -> int:
    """
    Score a found version token by its context:
      +3 if token has 3 or more segments (e.g., 1.9.6)
      +2 if within 120 chars of 'version', 'masterplus', 'release', etc.
      -3 if within 24 chars of bad context (USB 2.0, etc.)
      -2 if only two segments (e.g., 2.0)
    """
    score = 0
    segs = token.split(".")
    if len(segs) >= 3:
        score += 3
    elif len(segs) == 2:
        score -= 2

    lo = max(0, pos - 120)
    hi = min(len(text), pos + 120)
    ctx = text[lo:hi]

    if NEAR_GOOD_RX.search(ctx):
        score += 2
    if NEAR_BAD_RX.search(text[max(0, pos - 24):min(len(text), pos + 24)]):
        score -= 3

    return score

def _pick_version(full_text: str) -> str | None:
    """
    Choose the best-matching version by context-score; tie-break:
      1) more segments wins
      2) higher numeric tuple (major, minor, patch, build) wins
    """
    candidates = []
    for m in VER_CAND_RX.finditer(full_text):
        token = m.group(1)
        score = _score_candidate(full_text, m.start(1), token)
        segs = token.split(".")
        # Build a numeric tuple for tie-break (pad to 4)
        nums = []
        for s in segs[:4]:
            try:
                nums.append(int(re.match(r"(\d+)", s).group(1)))
            except Exception:
                nums.append(-1)
        while len(nums) < 4:
            nums.append(-1)
        candidates.append((score, len(segs), tuple(nums), token))

    if not candidates:
        return None

    # Sort by score DESC, segment count DESC, numeric tuple DESC
    candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return candidates[0][3]

def fetch_latest(name: str, url: str) -> dict:
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
    except Exception as e:
        return {"ok": False, "version": None, "date": None, "error": f"GET failed: {e}"}

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    version = _pick_version(text)

    ok = bool(version)
    return {"ok": ok, "version": version, "date": None, "error": None if ok else "version not found"}
