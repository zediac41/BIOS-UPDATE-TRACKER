"""Browser checks for the static page. Run from the repository root."""

from pathlib import Path

import yaml
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PILOTS = ["ROG STRIX X870E-E GAMING WIFI", "MAG X870 TOMAHAWK WIFI", "X870 AORUS ELITE WIFI7 ICE"]


def run():
    output = ROOT / "cache/lane-preview"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1080}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("https://**/*", lambda route: route.fulfill(status=200, content_type="text/plain", body="google.visualization.Query.setResponse({\"table\":{\"cols\":[],\"rows\":[]}});"))
        page.goto((ROOT / "docs/index.html").as_uri())
        config = yaml.safe_load((ROOT / 'config.yml').read_text(encoding='utf-8'))
        assert page.locator('.card').count() == sum(len(items) for items in config['vendors'].values())
        assert page.locator('.lane-status--verified').count() == 3
        for model in PILOTS:
            page.locator('#search-input').fill(model)
            card = page.locator('.card:visible')
            assert card.count() == 1
            card.locator('.kv').first.click()
            assert page.locator('#lane-dialog').is_visible()
            assert page.locator('#lane-title').inner_text() == model
            assert page.locator('#lane-body .lane-slots tbody tr').count() >= 4
            assert page.locator('#lane-body a[href^="https://"]').count() > 0
            page.keyboard.press('Escape')
            assert not page.locator('#lane-dialog').is_visible()
            expect(card.locator('.lane-open')).to_be_focused()
            card.locator('.lane-open').press('Enter')
            page.screenshot(path=str(output / (model.split()[0].lower() + '-desktop.png')))
            page.locator('#lane-close').click()

        # A link or an error disclosure must retain its own action.
        card.locator('.meta a').evaluate("el => el.addEventListener('click', e => e.preventDefault())")
        card.locator('.meta a').click()
        assert not page.locator('#lane-dialog').is_visible()
        page.locator('#search-input').fill('B550M PRO-VDH WIFI')
        page.locator('.card:visible .lane-open').click()
        assert 'Slot conflicts are unknown' in page.locator('#lane-body').inner_text()
        page.mouse.click(2, 2)
        assert not page.locator('#lane-dialog').is_visible()
        page.locator('#search-input').fill('')
        page.get_by_role('button', name='GIGABYTE', exact=True).click()
        assert page.locator('.card:visible').count() == len(config['vendors']['gigabyte'])
        page.get_by_role('button', name='All', exact=True).click()
        assert page.locator('.card h3 .badge').evaluate_all('(els) => els.every(el => el.getBoundingClientRect().height < 30)')
        page.screenshot(path=str(output / 'board-list-desktop.png'))

        for width in (375, 768):
            page.set_viewport_size({"width": width, "height": 900})
            page.locator('#search-input').fill('MAG X870 TOMAHAWK WIFI')
            page.locator('.card:visible .lane-open').click()
            assert page.locator('#lane-dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
            page.screenshot(path=str(output / f'msi-{width}.png'))
            page.locator('#lane-close').click()
        assert not errors, errors
        browser.close()
    print('Desktop/mobile dialog, keyboard, source links, pending state and filters passed.')


if __name__ == '__main__':
    run()
