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
import unittest.mock
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
    def test_save_manifest_survives_a_crash_mid_write(self):
        """A crash partway through a SECOND save must not corrupt the file
        on disk — it must still hold the FIRST save's valid content
        afterward, not truncated/garbage bytes from the failed write.

        This is a discriminating test, not just a happy-path check: it
        patches Path.write_text so the *second* call writes only a third of
        its payload and then raises, mimicking a process killed mid-write.

        Against the pre-fix implementation (`MANIFEST.write_text(...)`
        directly), that patched write_text call lands ON manifest.json
        itself, so the file on disk ends up truncated/invalid after the
        "crash" — this test fails.

        Against the fix (write to a sibling .tmp then os.replace()), that
        same patched write_text call lands on the .tmp file; the crash
        happens before os.replace runs, so manifest.json is never touched
        during the second save and still holds the first save's content —
        this test passes.
        """
        tmp_dir = Path(__file__).parent / "_tmp_manifest_test"
        tmp_dir.mkdir(exist_ok=True)
        manifest_path = tmp_dir / "manifest.json"

        original_manifest = wakareo_scrape.MANIFEST
        wakareo_scrape.MANIFEST = manifest_path
        real_write_text = Path.write_text
        calls = {"n": 0}

        def flaky_write_text(self_path, data, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                # Simulate a kill signal arriving mid-write: some bytes hit
                # disk, then the write is aborted before it completes.
                real_write_text(self_path, data[: len(data) // 3], *args, **kwargs)
                raise OSError("simulated crash mid-write")
            return real_write_text(self_path, data, *args, **kwargs)

        try:
            with unittest.mock.patch.object(Path, "write_text", flaky_write_text):
                # First save succeeds normally and establishes known-good
                # content on disk.
                wakareo_scrape.save_manifest(
                    {"tag_counts": {}}, {1, 2, 3}, set(), {}
                )
                # Second save crashes partway through its write.
                with self.assertRaises(OSError):
                    wakareo_scrape.save_manifest(
                        {"tag_counts": {}}, {1, 2, 3, 4, 5}, set(), {}
                    )

            # manifest.json must still parse and still hold the FIRST
            # save's content — untouched by the crashed second write.
            reloaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(reloaded["fetched"], [1, 2, 3])
        finally:
            wakareo_scrape.MANIFEST = original_manifest
            for p in tmp_dir.glob("*"):
                p.unlink()
            tmp_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
