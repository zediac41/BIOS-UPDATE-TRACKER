import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

import bios_tracker
import lane_sharing


ROOT = Path(__file__).resolve().parents[1]


class LaneSharingTests(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8"))
        self.payload = yaml.safe_load((ROOT / "lane_sharing.yml").read_text(encoding="utf-8"))

    def load(self, payload, config=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lane_sharing.yml"
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            return lane_sharing.load_catalog(path, self.config if config is None else config)

    def test_catalog_matches_live_inventory_and_has_sources(self):
        catalog = self.load(self.payload)
        self.assertTrue(catalog)
        for record in catalog.values():
            if record['status'] != 'pending':
                self.assertTrue(record["sources"])
                self.assertTrue(record["revision"])
        self.assertTrue(all(key[0] in {vendor.upper() for vendor in self.config['vendors']} for key in catalog))

    def test_bad_source_and_wrong_board_cannot_be_published_as_verified(self):
        for mutate in (
            lambda data: data["boards"][0]["rules"][0].update(sources=["missing"]),
            lambda data: data["boards"][0].update(model="A different motherboard"),
            lambda data: data["boards"][0]["sources"][0].update(url="javascript:alert(1)"),
        ):
            data = copy.deepcopy(self.payload)
            mutate(data)
            with self.assertRaises(ValueError):
                self.load(data)

    def test_pending_never_claims_no_sharing(self):
        output = lane_sharing.render_details({}, None)
        self.assertIn("unknown", output)
        self.assertNotIn("No sharing", output)

    def test_research_content_is_escaped(self):
        record = copy.deepcopy(self.payload["boards"][0])
        record["rules"][0]["result"] = '<img src=x onerror="alert(1)">'
        output = lane_sharing.render_details({}, record)
        self.assertNotIn('<img src=x', output)
        self.assertIn('&lt;img', output)

    def test_rendering_uses_saved_results_without_vendor_calls(self):
        results = json.loads((ROOT / "docs/data.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder, patch("requests.sessions.Session.request", side_effect=AssertionError("Network call")):
            bios_tracker.render_site(self.config, results, "2026-11-20 07:07 CST", Path(folder))
            output = (Path(folder) / "index.html").read_text(encoding="utf-8")
        self.assertEqual(output.count('data-lane-template="'), len(results))
        catalog = self.load(self.payload)
        researched = sum(
            catalog.get(lane_sharing.board_key(row['vendor'], row['model']), {}).get('status')
            in {'verified', 'no_sharing_documented'} for row in results
        )
        self.assertEqual(output.count('class="lane-gpu"'), researched)
        self.assertIn('id="lane-dialog"', output)

    def test_new_board_requires_research_but_existing_backlog_does_not(self):
        base_config = copy.deepcopy(self.config)
        config = copy.deepcopy(self.config)
        config['vendors']['msi'].append({'name': 'New model for onboarding test'})
        catalog = self.load(self.payload, config)
        expected = [{'vendor': 'MSI', 'model': 'New model for onboarding test'}]
        self.assertEqual(lane_sharing.research_needed(config, catalog, base_config), expected)
        self.assertEqual(lane_sharing.research_needed(base_config, catalog, base_config), [])

        record = copy.deepcopy(self.payload['boards'][1])
        record.update(model='New model for onboarding test')
        payload = copy.deepcopy(self.payload)
        payload['boards'].append(record)
        catalog = self.load(payload, config)
        self.assertEqual(lane_sharing.research_needed(config, catalog, base_config), [])
        key = lane_sharing.board_key('MSI', record['model'])
        catalog[key]['status'] = 'pending'
        self.assertEqual(lane_sharing.research_needed(config, catalog, base_config), expected)

    def test_failed_first_scrape_still_has_saved_research_and_clickable_tile(self):
        record = self.payload['boards'][1]
        entry = {'vendor': record['vendor'], 'model': record['model'], 'ok': False,
                 'versions': [], 'error': 'timeout'}
        with tempfile.TemporaryDirectory() as folder:
            bios_tracker.render_site(self.config, [entry], 'Unknown', Path(folder))
            output = (Path(folder) / 'index.html').read_text(encoding='utf-8')
        self.assertIn('class="lane-open"', output)
        self.assertIn('class="lane-gpu"', output)
        self.assertIn('M2_3', output)

    def test_summary_includes_new_unresearched_board(self):
        config = copy.deepcopy(self.config)
        config['vendors']['msi'].append('New model for onboarding test')
        catalog = self.load(self.payload, config)
        summary = lane_sharing.coverage_summary(config, catalog)
        self.assertIn('MSI: New model for onboarding test', summary)
        self.assertIn(f"of {sum(len(items) for items in config['vendors'].values())}", summary)

    def test_new_board_check_reports_missing_research(self):
        config = copy.deepcopy(self.config)
        config['vendors']['msi'].append('New model for onboarding test')
        previous_cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as folder:
                os.chdir(folder)
                Path('config.yml').write_text(yaml.safe_dump(config), encoding='utf-8')
                Path('lane_sharing.yml').write_text(yaml.safe_dump(self.payload), encoding='utf-8')
                with patch('lane_sharing.subprocess.check_output', return_value=yaml.safe_dump(self.config)):
                    with self.assertRaisesRegex(ValueError, 'New model for onboarding test'):
                        lane_sharing.check_new_boards('0' * 40)
                os.chdir(previous_cwd)
        finally:
            os.chdir(previous_cwd)

    def test_daily_build_preserves_last_good_bios_and_includes_lane_details(self):
        saved = json.loads((ROOT / "docs/data.json").read_text(encoding="utf-8"))
        failed_model = "B550M PRO-VDH WIFI"
        modules = {}
        for vendor in self.config['vendors']:
            batch = [copy.deepcopy(entry) for entry in saved if entry['vendor'].lower() == vendor]
            for entry in batch:
                if entry['model'] == failed_model:
                    entry.update(ok=False, versions=[], error="temporary timeout")
            modules[vendor] = SimpleNamespace(latest_many=lambda _items, batch=batch: batch)
        previous_cwd = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as folder:
                os.chdir(folder)
                Path('docs').mkdir()
                Path('docs/data.json').write_text(json.dumps(saved), encoding='utf-8')
                with patch.object(bios_tracker, 'load_config', return_value=self.config), \
                        patch.dict(bios_tracker.VENDOR_MODULES, modules), \
                        patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(Path('summary.md').resolve())}), \
                        patch('requests.sessions.Session.request', side_effect=AssertionError('Network call')), \
                        redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    bios_tracker.main()
                results = json.loads(Path('docs/data.json').read_text(encoding='utf-8'))
                failed = next(entry for entry in results if entry['model'] == failed_model)
                self.assertTrue(failed['stale'])
                self.assertTrue(failed['versions'])
                self.assertIn('id="lane-dialog"', Path('docs/index.html').read_text(encoding='utf-8'))
                self.assertEqual(len(results), len(saved))
                summary = Path('summary.md').read_text(encoding='utf-8')
                self.assertIn('## Lane-sharing research', summary)
                self.assertIn('## BIOS tracker summary', summary)
                os.chdir(previous_cwd)
        finally:
            os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
