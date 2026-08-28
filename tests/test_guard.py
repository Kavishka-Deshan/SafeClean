"""
Protection tests for safeclean.guard.

These are the tests that matter. If any of them fail, SafeClean must not be
allowed to delete anything. The suite is deliberately paranoid: it asserts on
every browser credential file by name, on the DPAPI key file, on the extension
and session stores, and on the traversal tricks that could smuggle a protected
path past an allowlist.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safeclean import guard  # noqa: E402


LOCAL = os.environ.get("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
ROAMING = os.environ.get("APPDATA", r"C:\Users\test\AppData\Roaming")
PROFILE = os.environ.get("USERPROFILE", r"C:\Users\test")

CHROME = os.path.join(LOCAL, r"Google\Chrome\User Data")
EDGE = os.path.join(LOCAL, r"Microsoft\Edge\User Data")
BRAVE = os.path.join(LOCAL, r"BraveSoftware\Brave-Browser\User Data")
FIREFOX_LOCAL = os.path.join(LOCAL, r"Mozilla\Firefox")
FIREFOX_ROAMING = os.path.join(ROAMING, r"Mozilla\Firefox")


class BrowserCredentialTests(unittest.TestCase):
    """Nothing that could log the user out may ever be deletable."""

    # Every Chromium file/dir that carries a session, a password, autofill data,
    # or the user's own content.
    CHROMIUM_PROTECTED = [
        "Cookies",
        "Cookies-journal",
        "Login Data",
        "Login Data For Account",
        "Web Data",
        "Local State",
        "Preferences",
        "Secure Preferences",
        "Local Storage",
        "Session Storage",
        "IndexedDB",
        "Extensions",
        "Extension State",
        "Local Extension Settings",
        "Sync Data",
        "Bookmarks",
        "Bookmarks.bak",
        "History",
        "Favicons",
        "Top Sites",
        "Sessions",
        "Current Session",
        "Last Session",
        "Trust Tokens",
        "Affiliation Database",
        "Network Persistent State",
        "TransportSecurity",
        "Visited Links",
        "Reading List",
    ]

    def test_chromium_credentials_protected_in_every_browser(self):
        for browser_root in (CHROME, EDGE, BRAVE):
            for profile in ("Default", "Profile 1", "Profile 17", "Guest Profile"):
                for name in self.CHROMIUM_PROTECTED:
                    path = os.path.join(browser_root, profile, name)
                    with self.subTest(path=path):
                        self.assertTrue(
                            guard.is_protected(path),
                            f"MUST be protected but was allowed: {path}",
                        )

    def test_local_state_at_browser_root_protected(self):
        # "Local State" sits beside the profiles, not inside one. It holds the
        # key that decrypts every saved password -- losing it loses them all.
        for browser_root in (CHROME, EDGE, BRAVE):
            path = os.path.join(browser_root, "Local State")
            with self.subTest(path=path):
                self.assertTrue(guard.is_protected(path))

    def test_contents_of_protected_dirs_are_protected(self):
        # Not just the directory -- everything inside it too.
        deep = [
            os.path.join(CHROME, "Default", "Local Storage", "leveldb", "000003.log"),
            os.path.join(CHROME, "Default", "Session Storage", "000005.ldb"),
            os.path.join(CHROME, "Default", "IndexedDB", "https_mail.google.com_0.indexeddb.leveldb", "LOG"),
            os.path.join(CHROME, "Default", "Extensions", "abcdefg", "manifest.json"),
            os.path.join(EDGE, "Default", "Sync Data", "LevelDB", "CURRENT"),
        ]
        for path in deep:
            with self.subTest(path=path):
                self.assertTrue(guard.is_protected(path))

    FIREFOX_PROTECTED = [
        "logins.json",
        "logins-backup.json",
        "key4.db",
        "key3.db",
        "cert9.db",
        "cookies.sqlite",
        "cookies.sqlite-wal",
        "places.sqlite",
        "formhistory.sqlite",
        "permissions.sqlite",
        "webappsstore.sqlite",
        "prefs.js",
        "user.js",
        "sessionstore.jsonlz4",
        "sessionstore-backups",
        "extensions.json",
        "storage",
    ]

    def test_firefox_credentials_protected(self):
        for base in (FIREFOX_LOCAL, FIREFOX_ROAMING):
            for name in self.FIREFOX_PROTECTED:
                path = os.path.join(base, "Profiles", "a1b2c3.default-release", name)
                with self.subTest(path=path):
                    self.assertTrue(
                        guard.is_protected(path),
                        f"MUST be protected but was allowed: {path}",
                    )

    def test_credential_names_are_case_insensitive(self):
        for variant in ("cookies", "COOKIES", "CoOkIeS", "login data", "LOGIN DATA"):
            path = os.path.join(CHROME, "Default", variant)
            with self.subTest(variant=variant):
                self.assertTrue(guard.is_protected(path))


class BrowserAllowlistTests(unittest.TestCase):
    """Only the named cache folders may be removed -- everything else denied."""

    def test_allowlisted_caches_are_deletable(self):
        allowed = [
            os.path.join(CHROME, "Default", "Cache"),
            os.path.join(CHROME, "Default", "Code Cache"),
            os.path.join(CHROME, "Default", "GPUCache"),
            os.path.join(CHROME, "Default", "Service Worker", "CacheStorage"),
            os.path.join(CHROME, "ShaderCache"),
            os.path.join(CHROME, "GrShaderCache"),
            os.path.join(EDGE, "Profile 1", "Cache"),
            os.path.join(BRAVE, "Default", "Code Cache", "js", "index"),
            os.path.join(FIREFOX_LOCAL, "Profiles", "a1b2c3.default-release", "cache2", "entries", "ABC123"),
        ]
        for path in allowed:
            with self.subTest(path=path):
                self.assertFalse(
                    guard.is_protected(path),
                    f"Should be deletable cache but was blocked: {path}",
                )

    def test_unknown_browser_file_is_denied_by_default(self):
        # The core of the design: a file we have never heard of is refused.
        unknown = [
            os.path.join(CHROME, "Default", "Some New Chrome File"),
            os.path.join(CHROME, "Default", "AuthTokens2027"),
            os.path.join(CHROME, "Default", "Network", "SCT Auditing Pending Reports"),
            os.path.join(EDGE, "Default", "WebAssistDatabase"),
            os.path.join(BRAVE, "Default", "brave_wallet"),
        ]
        for path in unknown:
            with self.subTest(path=path):
                self.assertTrue(
                    guard.is_protected(path),
                    f"Unknown browser file must default to PROTECTED: {path}",
                )

    def test_cache_name_buried_inside_protected_tree_is_denied(self):
        # A "Cache" directory nested inside Local Storage must not inherit the
        # allowlist. The allowlist only anchors at the root or one level down.
        sneaky = [
            os.path.join(CHROME, "Default", "Local Storage", "Cache"),
            os.path.join(CHROME, "Default", "IndexedDB", "Cache", "data.ldb"),
            os.path.join(CHROME, "Default", "Extensions", "abc", "Cache"),
        ]
        for path in sneaky:
            with self.subTest(path=path):
                self.assertTrue(guard.is_protected(path))

    def test_browser_profile_root_itself_is_denied(self):
        for root in (CHROME, EDGE, BRAVE):
            with self.subTest(root=root):
                self.assertTrue(guard.is_protected(root))
                self.assertTrue(guard.is_protected(os.path.join(root, "Default")))


class SystemProtectionTests(unittest.TestCase):
    def test_system_locations_denied(self):
        denied = [
            r"C:\Windows\System32",
            r"C:\Windows\System32\config\SAM",
            r"C:\Windows\WinSxS",
            r"C:\Program Files\Git",
            r"C:\Program Files (x86)\Steam",
            r"C:\System Volume Information",
            r"C:\Recovery",
            os.path.join(PROFILE, "Documents", "taxes.xlsx"),
            os.path.join(PROFILE, "Desktop", "notes.txt"),
            os.path.join(PROFILE, "OneDrive", "work"),
            os.path.join(PROFILE, "Pictures", "wedding.jpg"),
            os.path.join(PROFILE, ".ssh", "id_rsa"),
            os.path.join(PROFILE, "AppData", "Roaming", "Microsoft", "Protect"),
        ]
        for path in denied:
            with self.subTest(path=path):
                self.assertTrue(guard.is_protected(path))

    def test_windows_temp_and_logs_allowed(self):
        allowed = [
            r"C:\Windows\Temp\somefile.tmp",
            r"C:\Windows\Logs\CBS\CBS.log",
            r"C:\Windows\SoftwareDistribution\Download\abc123",
            r"C:\Windows\Prefetch\NOTEPAD.EXE-1234.pf",
        ]
        for path in allowed:
            with self.subTest(path=path):
                self.assertFalse(guard.is_protected(path))

    def test_windows_temp_root_itself_not_deletable(self):
        # Contents may go; the directory itself must stay.
        self.assertTrue(guard.is_protected(r"C:\Windows\Temp"))

    def test_critical_files_denied(self):
        for name in ("pagefile.sys", "swapfile.sys", "hiberfil.sys", "NTUSER.DAT"):
            for path in (os.path.join("C:\\", "sub", name), os.path.join(PROFILE, name)):
                with self.subTest(path=path):
                    self.assertTrue(guard.is_protected(path))

    def test_drive_roots_and_shallow_paths_denied(self):
        for path in ("C:\\", "C:", "D:\\", r"C:\Windows", r"C:\Users"):
            with self.subTest(path=path):
                self.assertTrue(guard.is_protected(path))

    def test_source_repositories_denied(self):
        for path in (
            os.path.join(PROFILE, "Projects", "app", ".git"),
            os.path.join(PROFILE, "Projects", "app", ".git", "objects", "ab", "cd"),
        ):
            with self.subTest(path=path):
                self.assertTrue(guard.is_protected(path))

    def test_relative_paths_denied(self):
        for path in ("Temp", r"..\..\Windows", "./cache"):
            with self.subTest(path=path):
                self.assertTrue(guard.is_protected(path))


class RootConfinementTests(unittest.TestCase):
    """A rule may only delete inside the roots it declared."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="safeclean_test_")
        self.root = os.path.join(self.tmp, "cacheroot")
        self.outside = os.path.join(self.tmp, "elsewhere")
        os.makedirs(os.path.join(self.root, "sub"), exist_ok=True)
        os.makedirs(self.outside, exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_inside_declared_root_allowed(self):
        target = os.path.join(self.root, "sub", "file.tmp")
        self.assertFalse(guard.is_protected(target, allowed_roots=[self.root]))

    def test_outside_declared_root_denied(self):
        target = os.path.join(self.outside, "file.tmp")
        self.assertTrue(guard.is_protected(target, allowed_roots=[self.root]))

    def test_dotdot_traversal_out_of_root_denied(self):
        escape = os.path.join(self.root, "..", "elsewhere", "file.tmp")
        self.assertTrue(guard.is_protected(escape, allowed_roots=[self.root]))

    def test_root_itself_is_not_a_strict_descendant(self):
        self.assertTrue(guard.is_protected(self.root, allowed_roots=[self.root]))


class ReparsePointTests(unittest.TestCase):
    def test_junction_is_refused(self):
        tmp = tempfile.mkdtemp(prefix="safeclean_link_")
        try:
            real = os.path.join(tmp, "real")
            link = os.path.join(tmp, "link")
            os.makedirs(os.path.join(real, "deep"), exist_ok=True)
            try:
                os.symlink(real, link, target_is_directory=True)
            except (OSError, NotImplementedError, AttributeError):
                self.skipTest("symlink creation needs privileges or dev mode")
            self.assertTrue(guard.is_protected(link, allowed_roots=[tmp]))
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


class CheckApiTests(unittest.TestCase):
    def test_check_raises_with_reason(self):
        path = os.path.join(CHROME, "Default", "Cookies")
        with self.assertRaises(guard.ProtectedPathError) as ctx:
            guard.check(path)
        self.assertIn("login", str(ctx.exception).lower())
        self.assertEqual(ctx.exception.path, path)

    def test_check_passes_for_cache(self):
        guard.check(os.path.join(CHROME, "Default", "Cache", "data_1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class SystemDrivePortabilityTests(unittest.TestCase):
    """
    Protection must follow the drive Windows is actually installed on.

    Hardcoding C: would silently leave the real system folders unprotected on a
    machine where Windows lives on D:, so the denylist is rebuilt from
    %SystemDrive%. These tests reload the module with a patched environment.
    """

    @contextlib.contextmanager
    def patched_env(self, **env):
        """
        Reload guard with a patched environment, then put it back.

        It has to be a context manager: the module's denylists are built at
        import time, so the reloaded module is only valid while the patched
        environment is still in place.
        """
        saved = {k: os.environ.get(k) for k in env}
        try:
            for key, value in env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            yield importlib.reload(guard)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            importlib.reload(guard)

    def test_denylist_follows_system_drive(self):
        with self.patched_env(
            SystemDrive="D:",
            SystemRoot=r"D:\Windows",
            ProgramFiles=r"D:\Program Files",
            ProgramData=r"D:\ProgramData",
        ) as g:
            for path in (
                r"D:\Windows\System32\config\SAM",
                r"D:\Program Files\App\thing.dll",
                r"D:\System Volume Information\x",
                r"D:\Recovery\y",
            ):
                with self.subTest(path=path):
                    self.assertTrue(
                        g.is_protected(path),
                        f"should be protected on a D: install: {path}",
                    )
            # And the carved-out temp/log paths still work on that drive.
            self.assertFalse(g.is_protected(r"D:\Windows\Temp\scratch.tmp"))
            self.assertTrue(g.is_protected(r"D:\Windows\Temp"))

    def test_system_drive_falls_back_to_system_root(self):
        with self.patched_env(SystemDrive=None, SystemRoot=r"E:\Windows") as g:
            self.assertEqual(g._system_drive(), "E:")
