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

    def load(self, payload):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lane_sharing.yml"
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")
            return lane_sharing.load_catalog(path, self.config)

    def test_catalog_matches_live_inventory_and_has_sources(self):
        catalog = self.load(self.payload)
        self.assertEqual(len(catalog), 3)
        for record in catalog.values():
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
        self.assertEqual(output.count('class="lane-gpu"'), 3)
        self.assertIn('id="lane-dialog"', output)

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
                        patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': ''}), \
                        patch('requests.sessions.Session.request', side_effect=AssertionError('Network call')), \
                        redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    bios_tracker.main()
                results = json.loads(Path('docs/data.json').read_text(encoding='utf-8'))
                failed = next(entry for entry in results if entry['model'] == failed_model)
                self.assertTrue(failed['stale'])
                self.assertTrue(failed['versions'])
                self.assertIn('id="lane-dialog"', Path('docs/index.html').read_text(encoding='utf-8'))
                self.assertEqual(len(results), len(saved))
                os.chdir(previous_cwd)
        finally:
            os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
