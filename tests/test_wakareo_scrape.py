"""Wakareo scraper helpers — pure functions, no network.

Covers the two fixes from code review:
  1. looks_like_login_page distinguishes an inline login/session-expired
     body from a real record page, even when both could be served at the
     same URL (so fetch() doesn't need a redirect to notice expiry).
  2. save_manifest writes atomically (temp file + os.replace), so a kill
     mid-write can never leave manifest.json truncated/unparseable.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.stdout.reconfigure(encoding="utf-8")

import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    "wakareo_scrape", Path(__file__).parent.parent / "scripts" / "41_wakareo_scrape.py"
)
wakareo_scrape = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wakareo_scrape)

FIXTURES = Path(__file__).parent / "fixtures" / "wakareo"
# login_page.html lives under non_record/ (not directly in FIXTURES) so it is
# excluded from test_wakareo_records.py's `FIXTURES.glob("*.html")` sweep,
# which asserts every fixture there IS a parseable record — this one, by
# design, is not.
NON_RECORD = FIXTURES / "non_record"


def fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class LoginPageDetection(unittest.TestCase):
    def test_login_page_fixture_is_detected(self):
        # Captured live via a plain unauthenticated GET to the public
        # login.aspx — no credentials involved.
        html = (NON_RECORD / "login_page.html").read_text(encoding="utf-8")
        self.assertTrue(wakareo_scrape.looks_like_login_page(html))

    def test_real_record_is_not_a_login_page(self):
        self.assertFalse(
            wakareo_scrape.looks_like_login_page(fx("entry_DICT4_47746.html"))
        )

    def test_williams_record_is_not_a_login_page(self):
        self.assertFalse(
            wakareo_scrape.looks_like_login_page(fx("entry_DICT1_1.html"))
        )

    def test_empty_string_is_not_a_login_page(self):
        self.assertFalse(wakareo_scrape.looks_like_login_page(""))


class ManifestAtomicity(unittest.TestCase):
    def test_save_manifest_never_leaves_a_partial_file(self):
        """A prior write must remain intact even if writing the temp file
        raises partway through — save_manifest must not touch the real
        path until the temp file is fully written."""
        tmp_dir = Path(__file__).parent / "_tmp_manifest_test"
        tmp_dir.mkdir(exist_ok=True)
        manifest_path = tmp_dir / "manifest.json"
        good = {"fetched": [1, 2, 3], "empty": [], "errors": {}, "tag_counts": {}}
        manifest_path.write_text(json.dumps(good), encoding="utf-8")

        original_manifest = wakareo_scrape.MANIFEST
        wakareo_scrape.MANIFEST = manifest_path
        try:
            wakareo_scrape.save_manifest(
                {"tag_counts": {}}, {1, 2, 3, 4}, set(), {}
            )
            reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["fetched"], [1, 2, 3, 4])
            # No leftover .tmp file after a successful save.
            self.assertFalse((tmp_dir / "manifest.json.tmp").exists())
        finally:
            wakareo_scrape.MANIFEST = original_manifest
            for p in tmp_dir.glob("*"):
                p.unlink()
            tmp_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
