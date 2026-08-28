"""
End-to-end deletion tests against a sandboxed fake browser profile.

test_guard.py proves the guard says "no" to the right paths. This file proves
the cleaner actually honours it: it builds a realistic browser profile in a temp
directory, runs the real deletion engine over it, and then asserts byte-for-byte
that every credential file is untouched while the cache is gone.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safeclean import cleaner, guard  # noqa: E402
from safeclean.rules import Risk, Rule  # noqa: E402


# Files that must survive a clean, with the content we will hash afterwards.
CREDENTIAL_FILES = {
    "Cookies": b"SQLite format 3\x00fake-cookie-database-with-my-sessions",
    "Cookies-journal": b"journal",
    "Login Data": b"SQLite format 3\x00fake-saved-passwords",
    "Login Data For Account": b"SQLite format 3\x00fake-account-passwords",
    "Web Data": b"SQLite format 3\x00fake-autofill-and-cards",
    "Local State": b'{"os_crypt":{"encrypted_key":"THIS-DECRYPTS-ALL-PASSWORDS"}}',
    "Preferences": b'{"profile":{"name":"test-user"}}',
    "Secure Preferences": b'{"protection":{"macs":{}}}',
    "Bookmarks": b'{"roots":{"bookmark_bar":{"children":[]}}}',
    "Bookmarks.bak": b'{"roots":{}}',
    "History": b"SQLite format 3\x00browsing-history",
    "Favicons": b"SQLite format 3\x00favicons",
    "Top Sites": b"SQLite format 3\x00top-sites",
    "TransportSecurity": b'{"hsts":{}}',
    "Visited Links": b"VLNK",
}

# Directories that must survive intact, with one file each.
CREDENTIAL_DIRS = {
    "Local Storage": ("leveldb/000003.log", b"site-auth-tokens-live-here"),
    "Session Storage": ("000005.ldb", b"open-tab-session-state"),
    "IndexedDB": ("https_app.example_0.indexeddb.leveldb/LOG", b"indexeddb-data"),
    "Extensions": ("nmmhkkegccagdldgiimedpiccmgmieda/manifest.json", b"{}"),
    "Extension State": ("000004.log", b"extension-state"),
    "Sync Data": ("LevelDB/CURRENT", b"sync-state"),
    "Sessions": ("Session_13300000000000000", b"restore-my-tabs"),
}

# Cache content that SHOULD be removed.
CACHE_FILES = {
    "Cache/data_0": b"x" * 4096,
    "Cache/data_1": b"y" * 8192,
    "Cache/index": b"cache-index",
    "Cache/f_000001": b"z" * 2048,
    "Code Cache/js/index": b"compiled-js",
    "Code Cache/wasm/index": b"compiled-wasm",
    "GPUCache/data_0": b"shader-blob",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SandboxProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="safeclean_profile_"))
        self.profile = self.tmp / "User Data" / "Default"
        self.profile.mkdir(parents=True)

        for name, content in CREDENTIAL_FILES.items():
            (self.profile / name).write_bytes(content)

        for dirname, (relpath, content) in CREDENTIAL_DIRS.items():
            target = self.profile / dirname / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        for relpath, content in CACHE_FILES.items():
            target = self.profile / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        # Fingerprint everything that must survive.
        self.before = {}
        for name in CREDENTIAL_FILES:
            self.before[name] = sha(self.profile / name)
        for dirname, (relpath, _c) in CREDENTIAL_DIRS.items():
            self.before[f"{dirname}/{relpath}"] = sha(self.profile / dirname / relpath)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cache_rule(self) -> Rule:
        """A rule aimed at the allowlisted cache dirs, as rules.py would build."""
        return Rule(
            id="test_cache",
            label="Test browser cache",
            category="Browser",
            risk=Risk.CAUTION,
            what="test",
            cost="test",
            roots=[
                self.profile / "Cache",
                self.profile / "Code Cache",
                self.profile / "GPUCache",
            ],
        )

    def _whole_profile_rule(self) -> Rule:
        """
        A deliberately WRONG rule pointed at the entire profile.

        This is the important one. It simulates a buggy or malicious rule that
        tries to sweep the whole profile. The guard must still save every
        credential file.
        """
        return Rule(
            id="test_bad_rule",
            label="Deliberately overreaching rule",
            category="Browser",
            risk=Risk.CAUTION,
            what="test",
            cost="test",
            roots=[self.profile],
        )

    def _assert_credentials_intact(self):
        for name in CREDENTIAL_FILES:
            path = self.profile / name
            with self.subTest(file=name):
                self.assertTrue(path.exists(), f"{name} was DELETED")
                self.assertEqual(
                    sha(path), self.before[name], f"{name} was MODIFIED"
                )
        for dirname, (relpath, _c) in CREDENTIAL_DIRS.items():
            path = self.profile / dirname / relpath
            key = f"{dirname}/{relpath}"
            with self.subTest(file=key):
                self.assertTrue(path.exists(), f"{key} was DELETED")
                self.assertEqual(sha(path), self.before[key], f"{key} was MODIFIED")

    def test_cache_removed_and_credentials_intact(self):
        result = cleaner.clean_rule(self._cache_rule(), dry_run=False)
        self.assertGreater(result.deleted, 0)
        self.assertEqual(result.refused, 0)

        for relpath in CACHE_FILES:
            with self.subTest(cache=relpath):
                self.assertFalse(
                    (self.profile / relpath).exists(),
                    f"cache file survived: {relpath}",
                )
        self._assert_credentials_intact()

    def test_overreaching_rule_cannot_touch_credentials(self):
        # The rule asks to delete the whole profile. The guard must refuse every
        # credential file individually.
        result = cleaner.clean_rule(self._whole_profile_rule(), dry_run=False)
        self._assert_credentials_intact()
        self.assertGreater(
            result.refused, 0, "guard should have refused the credential files"
        )

    def test_dry_run_deletes_nothing(self):
        result = cleaner.clean_rule(self._cache_rule(), dry_run=True)
        self.assertGreater(result.deleted, 0)
        self.assertGreater(result.freed, 0)
        for relpath in CACHE_FILES:
            with self.subTest(cache=relpath):
                self.assertTrue(
                    (self.profile / relpath).exists(),
                    f"dry run deleted a file: {relpath}",
                )
        self._assert_credentials_intact()

    def test_dry_run_size_matches_real_run(self):
        dry = cleaner.clean_rule(self._cache_rule(), dry_run=True)
        real = cleaner.clean_rule(self._cache_rule(), dry_run=False)
        self.assertEqual(dry.freed, real.freed)
        self.assertEqual(dry.deleted, real.deleted)

    def test_rule_root_survives_cleaning(self):
        cleaner.clean_rule(self._cache_rule(), dry_run=False)
        self.assertTrue((self.profile / "Cache").exists())

    def test_refusal_reasons_are_recorded(self):
        result = cleaner.clean_rule(self._whole_profile_rule(), dry_run=False)
        refused_names = {Path(p).name for p, _reason in result.refusals}
        for expected in ("Cookies", "Login Data", "Local State"):
            with self.subTest(expected=expected):
                self.assertIn(expected, refused_names)


class RemoveOnePathTests(unittest.TestCase):
    """The single deletion function must refuse before it touches anything."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="safeclean_one_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refuses_and_reports(self):
        target = self.tmp / "Cookies"
        target.write_bytes(b"session")
        result = cleaner.RuleResult(rule_id="t", label="t")
        freed = cleaner._remove_one(
            str(target), [self.tmp], result, dry_run=False, recycle=False
        )
        self.assertEqual(freed, 0)
        self.assertEqual(result.refused, 1)
        self.assertTrue(target.exists())

    def test_allows_plain_temp_file(self):
        target = self.tmp / "scratch.tmp"
        target.write_bytes(b"junk" * 100)
        result = cleaner.RuleResult(rule_id="t", label="t")
        freed = cleaner._remove_one(
            str(target), [self.tmp], result, dry_run=False, recycle=False
        )
        self.assertEqual(freed, 400)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
