from bs4 import BeautifulSoup
from .common import parse_best_version, parse_any_date

def parse(url: str, html: str, selectors=None):
  """
  Returns dict: {version, date, title, url}
  selectors: optional dict with keys item, version, date, title
  """
  soup = BeautifulSoup(html, "lxml")
  sel = selectors or {}

  # If selectors provided, try them first
  try:
    item_sel = sel.get("item")
    if item_sel:
      item = soup.select_one(item_sel)
      if item:
        texts = [item.get_text(" ", strip=True)]
        if sel.get("version"):
          vtag = item.select_one(sel["version"])
          if vtag:
            texts.append(vtag.get_text(" ", strip=True))
        v = parse_best_version(texts)
        if sel.get("date"):
          dtag = item.select_one(sel["date"])
          dtexts = [dtag.get_text(" ", strip=True)] + texts if dtag else texts
          d = parse_any_date(dtexts)
        else:
          d = parse_any_date(texts)
        title = None
        if sel.get("title"):
          ttag = item.select_one(sel["title"])
          title = ttag.get_text(" ", strip=True) if ttag else None
        return {"version": v, "date": d, "title": title, "url": url}
  except Exception:
    pass

  # Heuristic fallback: look for BIOS sections then pick first/most recent row/card
  texts = []
  for css in ["#bios", ".bios", ".driver-bios", "#Content", "table", "ul", "ol", ".download", ".support", ".dl-bios"]:
    for node in soup.select(css):
      txt = node.get_text(" ", strip=True)
      if "BIOS" in txt.upper():
        texts.append(txt)

  if not texts:
    texts = [soup.get_text(" ", strip=True)]

  version = parse_best_version(texts)
  date = parse_any_date(texts)
  title = None
  return {"version": version, "date": date, "title": title, "url": url}
