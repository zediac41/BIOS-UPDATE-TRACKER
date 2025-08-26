import time, random, re
import requests
DEFAULT_HEADERS={'User-Agent':'Mozilla/5.0','Accept-Language':'en-US,en;q=0.9'}
def _save_raw_html(vendor, model, html):
    from pathlib import Path
    safe=re.sub(r'[^A-Za-z0-9._-]+','_',model)[:120]
    p=Path('docs')/'raw'; p.mkdir(parents=True,exist_ok=True)
    (p/f'{vendor}__{safe}.html').write_text(html or '',encoding='utf-8')
def fetch_html(url, vendor, model, use_playwright_fallback=True, timeout=25):
    last_err=None
    for _ in range(2):
        try:
            r=requests.get(url,headers=DEFAULT_HEADERS,timeout=timeout)
            if r.status_code==200 and r.text and len(r.text)>500:
                _save_raw_html(vendor,model,r.text); return r.text,None
            last_err=f'HTTP {r.status_code}'
        except Exception as e:
            last_err=str(e)[:200]
        time.sleep(0.8+random.random()*0.6)
    if not use_playwright_fallback: return '', last_err or 'unknown'
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b=p.chromium.launch(args=['--no-sandbox']); pg=b.new_page(user_agent=DEFAULT_HEADERS['User-Agent'])
            pg.set_default_timeout(timeout*1000); pg.goto(url, wait_until='domcontentloaded'); pg.wait_for_timeout(2500)
            html=pg.content(); b.close()
            if html and len(html)>500: _save_raw_html(vendor,model,html); return html,None
            return html or '', 'empty after playwright'
    except Exception as e:
        return '', f'playwright: {str(e)[:200]}'
