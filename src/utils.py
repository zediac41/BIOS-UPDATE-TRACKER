import re
from bs4 import BeautifulSoup

def clean_text(s: str) -> str:
    if not s:
        return ""
    return " ".join(s.split())

def parse_date_guess(s: str):
    """Try to parse a date from common vendor formats.
    Returns ISO date string (YYYY-MM-DD) or None.
    """
    if not s:
        return None

    s = s.strip()

    # Patterns: 2025/08/01, 2025-08-01, 08/01/2025, 2025.08.01, Aug 1 2025, 01-Aug-2025, etc.
    patterns = [
        r'(?P<y>\d{4})[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})',
        r'(?P<m>\d{1,2})[./-](?P<d>\d{1,2})[./-](?P<y>\d{4})',
        r'(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{4})',
    ]

    for pat in patterns:
        m = re.search(pat, s)
        if m:
            try:
                y = int(m.group('y'))
                mo = int(m.group('m'))
                d = int(m.group('d'))
                if 1 <= mo <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100:
                    return f"{y:04d}-{mo:02d}-{d:02d}"
            except Exception:
                pass

    # Month name patterns
    month_map = {m.lower(): i for i, m in enumerate(
        ["January","February","March","April","May","June","July","August","September","October","November","December"], start=1)}
    # e.g., Aug 1, 2025 or 1 Aug 2025
    m = re.search(r'(?P<mon>[A-Za-z]{3,9})\s+(?P<d>\d{1,2}),?\s+(?P<y>\d{4})', s)
    if m:
        mon = month_map.get(m.group('mon').lower())
        if mon:
            d = int(m.group('d'))
            y = int(m.group('y'))
            if 1 <= d <= 31 and 2000 <= y <= 2100:
                return f"{y:04d}-{mon:02d}-{d:02d}"

    m = re.search(r'(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]{3,9}),?\s+(?P<y>\d{4})', s)
    if m:
        mon = month_map.get(m.group('mon').lower())
        if mon:
            d = int(m.group('d'))
            y = int(m.group('y'))
            if 1 <= d <= 31 and 2000 <= y <= 2100:
                return f"{y:04d}-{mon:02d}-{d:02d}"
    return None

def best_effort_versions_and_dates(html: str):
    """Heuristic parser that tries to find BIOS version strings and adjacent dates from arbitrary vendor pages."""
    soup = BeautifulSoup(html, "lxml")

    # Find likely blocks containing BIOS info by keyword
    candidates = []
    for tag in soup.find_all(text=True):
        t = clean_text(tag)
        if not t: 
            continue
        if re.search(r'\b(BIOS|UEFI)\b', t, re.I):
            # Use parent block
            parent = getattr(tag, 'parent', None)
            if parent:
                candidates.append(parent)

    # Collect version/date pairs
    entries = []
    for block in candidates:
        text = clean_text(block.get_text(" "))
        # Version formats like "Version 2014.01", "v1.23", "F8c", "7D75v1C", "P3.90"
        for m in re.finditer(r'\b(?:Version|Ver\.?|V)\s*[:\-]?\s*([A-Za-z0-9._-]{2,})\b', text, re.I):
            version = m.group(1)
            # try to find a nearby date window around the match
            start = max(0, m.start() - 120)
            end = min(len(text), m.end() + 120)
            window = text[start:end]
            date = parse_date_guess(window) or parse_date_guess(text)
            entries.append({"version": version, "date": date})

        # Some vendors use patterns like "F10", "F10a" (Gigabyte), "P3.90" (ASRock), "7D75v1C" (MSI), etc.
        # Also capture standalone looking tokens that look like versions
        for m in re.finditer(r'\b([A-Z]?\d+[A-Za-z]?(?:\.\d+)?[a-z]?)\b', text):
            token = m.group(1)
            if len(token) >= 3 and any(ch.isdigit() for ch in token):
                # Check nearby if "BIOS" mentioned
                start = max(0, m.start() - 80)
                end = min(len(text), m.end() + 80)
                window = text[start:end]
                if re.search(r'BIOS|UEFI|Version|Ver\.?', window, re.I):
                    date = parse_date_guess(window) or parse_date_guess(text)
                    entries.append({"version": token, "date": date})

    # De-duplicate while preserving order and filter junk
    seen = set()
    filtered = []
    for e in entries:
        key = (e["version"], e.get("date"))
        if key in seen:
            continue
        seen.add(key)
        # Basic junk filter: ignore obviously-too-long version strings
        if len(e["version"]) > 20:
            continue
        filtered.append(e)

    # Keep most recent-looking first by presence of date then keep first two unique
    # We cannot truly sort by date reliably from arbitrary pages; leave heuristic order.
    return filtered[:6]  # caller will trim to 2 later
