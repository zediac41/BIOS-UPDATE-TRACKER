import re
from datetime import datetime
from packaging.version import Version, InvalidVersion

VERSION_PAT = re.compile(r'\b(?:v?\s*)?(\d+(?:\.\d+){0,3}[A-Za-z0-9\-]*)\b')
DATE_PATS = [
  r'\b(\d{4}[/-]\d{1,2}[/-]\d{1,2})\b',
  r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b',
  r'\b([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})\b',
]

def parse_best_version(texts):
  """
  Find the most 'reasonable' version string from a list of texts.
  Prefer semantic versions; fallback to highest numeric.
  """
  candidates = []
  for t in texts:
    for m in VERSION_PAT.finditer(t):
      ver = m.group(1).strip().lstrip('vV')
      # skip obvious file sizes or dates
      if any(x in ver.lower() for x in ["kb", "mb", "gb"]):
        continue
      candidates.append(ver)
  # Try packaging.version for comparables
  parsed = []
  for c in candidates:
    try:
      parsed.append((Version(c), c))
    except InvalidVersion:
      pass
  if parsed:
    parsed.sort(reverse=True, key=lambda x: x[0])
    return parsed[0][1]
  return max(candidates, key=len) if candidates else None

def parse_any_date(texts):
  for t in texts:
    for pat in DATE_PATS:
      m = re.search(pat, t)
      if m:
        raw = m.group(1)
        for fmt in ("%Y-%m-%d","%Y/%m/%d","%m/%d/%Y","%m-%d-%Y","%d/%m/%Y","%d-%m-%Y","%b %d, %Y","%B %d, %Y"):
          try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
          except Exception:
            continue
  return None
