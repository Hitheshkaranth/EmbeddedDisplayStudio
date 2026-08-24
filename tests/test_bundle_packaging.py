"""
tests/test_bundle_packaging.py
Layer: Test
Purpose: Cover what actually ends up inside a deployed bundle.

Validation decides whether a bundle is *allowed* onto the panel; packaging
decides what *reaches* it. The second half was previously untested, and the
failure it allowed was not subtle: the packager archived every file in the
bundle directory, so a real application folder shipped its build outputs, its
caches and any archive somebody had left lying next to the source. On the folder
that prompted these tests that came to 66 GB against a 500 MB target limit.
"""
import json
import os
import sys
import tarfile
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.hmi_deployer.deployer import (  # noqa: E402
    BundleTooLargeError,
    MAX_BUNDLE_BYTES,
    load_excludes,
    package_bundle,
    plan_bundle,
)


def write(path: str, content: str = "x") -> None:
    """Creates a file and any missing parent directories."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class BundleFixture(unittest.TestCase):
    """A minimal valid bundle in a temporary directory."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = os.path.join(self.tmp.name, "my-app")
        os.makedirs(self.bundle)
        write(os.path.join(self.bundle, "main.qml"), "import QtQuick\nItem {}\n")
        with open(os.path.join(self.bundle, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({
                "schema": 1,
                "name": "my-app",
                "version": "1.0.0",
                "entry": "main.qml",
                "runtime": "qml",
                "screen": {"width": 1280, "height": 800},
                "tags_required": [],
                "qt": ">=6.5",
            }, f)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def planned_names(self):
        entries, _ = plan_bundle(self.bundle)
        return {arcname for _, arcname in entries}


class TestDefaultExcludes(BundleFixture):

    def test_application_files_are_kept(self):
        """Invariant: everything the app actually consists of is packaged."""
        write(os.path.join(self.bundle, "assets", "logo.png"))
        write(os.path.join(self.bundle, "lib", "helper.py"))
        names = self.planned_names()
        self.assertIn("manifest.json", names)
        self.assertIn("main.qml", names)
        self.assertIn("assets/logo.png", names)
        self.assertIn("lib/helper.py", names)

    def test_build_and_cache_directories_are_dropped(self):
        """Build outputs and caches are regenerated on the target, never shipped."""
        write(os.path.join(self.bundle, "__pycache__", "main.cpython-312.pyc"))
        write(os.path.join(self.bundle, "build", "out.o"))
        write(os.path.join(self.bundle, "dist", "app.exe"))
        write(os.path.join(self.bundle, ".git", "config"))
        write(os.path.join(self.bundle, "node_modules", "pkg", "index.js"))
        write(os.path.join(self.bundle, ".venv", "pyvenv.cfg"))
        names = self.planned_names()
        for unwanted in ("__pycache__", "build/", "dist/", ".git/", "node_modules/", ".venv/"):
            self.assertFalse(
                any(n.startswith(unwanted) or unwanted in n for n in names),
                f"{unwanted} should not be packaged, got {sorted(names)}",
            )

    def test_nested_caches_are_dropped(self):
        """A pattern matches on the name, so it catches the directory at any depth."""
        write(os.path.join(self.bundle, "lib", "__pycache__", "helper.pyc"))
        write(os.path.join(self.bundle, "lib", "helper.py"))
        names = self.planned_names()
        self.assertIn("lib/helper.py", names)
        self.assertFalse(any("__pycache__" in n for n in names))

    def test_loose_pyc_is_dropped(self):
        """*.pyc matches as a file pattern, not only inside __pycache__."""
        write(os.path.join(self.bundle, "stale.pyc"))
        self.assertNotIn("stale.pyc", self.planned_names())


class TestHmiIgnore(BundleFixture):

    def test_hmiignore_patterns_are_applied(self):
        write(os.path.join(self.bundle, "app_archive.zip"))
        write(os.path.join(self.bundle, "keep.zip"))
        write(os.path.join(self.bundle, ".hmiignore"), "app_archive.zip\n")
        names = self.planned_names()
        self.assertNotIn("app_archive.zip", names)
        self.assertIn("keep.zip", names, "only the listed pattern should be excluded")

    def test_hmiignore_supports_globs_comments_and_blank_lines(self):
        write(os.path.join(self.bundle, "capture-01.log"))
        write(os.path.join(self.bundle, "capture-02.log"))
        write(os.path.join(self.bundle, "notes.txt"))
        write(os.path.join(self.bundle, ".hmiignore"),
              "# logs from bench captures\n\n*.log\n")
        names = self.planned_names()
        self.assertNotIn("capture-01.log", names)
        self.assertNotIn("capture-02.log", names)
        self.assertIn("notes.txt", names)

    def test_hmiignore_can_target_a_subdirectory(self):
        write(os.path.join(self.bundle, "release", "app.exe"))
        write(os.path.join(self.bundle, "src", "app.py"))
        write(os.path.join(self.bundle, ".hmiignore"), "release/\n")
        names = self.planned_names()
        self.assertFalse(any(n.startswith("release/") for n in names))
        self.assertIn("src/app.py", names)

    def test_hmiignore_itself_is_not_shipped(self):
        write(os.path.join(self.bundle, ".hmiignore"), "*.log\n")
        self.assertNotIn(".hmiignore", self.planned_names())

    def test_absent_hmiignore_leaves_defaults(self):
        self.assertEqual(load_excludes(self.bundle), list(load_excludes(self.bundle)))
        self.assertIn("__pycache__", load_excludes(self.bundle))


class TestSizeGuard(BundleFixture):

    def test_oversized_bundle_is_refused_before_upload(self):
        """
        Invariant: a bundle the target would reject fails on the host first.

        The target caps a bundle at MAX_BUNDLE_SIZE. Discovering that after the
        upload wastes the whole transfer, and on a field link that is minutes.
        """
        big = os.path.join(self.bundle, "huge.bin")
        os.makedirs(os.path.dirname(big), exist_ok=True)
        with open(big, "wb") as f:
            f.truncate(MAX_BUNDLE_BYTES + 1)

        out = os.path.join(self.tmp.name, "out")
        os.makedirs(out)
        with self.assertRaises(BundleTooLargeError) as ctx:
            package_bundle(self.bundle, out)

        message = str(ctx.exception)
        self.assertIn("huge.bin", message, "the error must name the offending file")
        self.assertIn(".hmiignore", message, "the error must say how to fix it")
        self.assertEqual(os.listdir(out), [], "nothing should be written on refusal")

    def test_excluded_files_do_not_count_toward_the_limit(self):
        """A bundle that is only oversized because of ignored files still packages."""
        big = os.path.join(self.bundle, "huge.bin")
        with open(big, "wb") as f:
            f.truncate(MAX_BUNDLE_BYTES + 1)
        write(os.path.join(self.bundle, ".hmiignore"), "huge.bin\n")

        out = os.path.join(self.tmp.name, "out")
        os.makedirs(out)
        tar_path, sha_path = package_bundle(self.bundle, out)
        self.assertTrue(os.path.isfile(tar_path))
        self.assertTrue(os.path.isfile(sha_path))


class TestPackageContents(BundleFixture):

    def test_archive_members_sit_at_the_root(self):
        """
        Invariant: CONTRACT section 4 requires members at the archive root.

        hmi-install extracts straight into the release directory, so a tarball
        with a leading directory component installs an app the loader cannot
        find.
        """
        write(os.path.join(self.bundle, "assets", "logo.png"))
        write(os.path.join(self.bundle, "__pycache__", "x.pyc"))

        out = os.path.join(self.tmp.name, "out")
        os.makedirs(out)
        tar_path, sha_path = package_bundle(self.bundle, out)

        with tarfile.open(tar_path, "r:gz") as tar:
            names = tar.getnames()

        self.assertIn("manifest.json", names)
        self.assertIn("main.qml", names)
        self.assertIn("assets/logo.png", names)
        self.assertFalse(any(n.startswith("my-app/") for n in names),
                         f"members must not be nested under the bundle dir: {names}")
        self.assertFalse(any("__pycache__" in n for n in names))

    def test_checksum_sidecar_matches_the_tarball(self):
        """The target verifies this digest before it will extract anything."""
        import hashlib

        out = os.path.join(self.tmp.name, "out")
        os.makedirs(out)
        tar_path, sha_path = package_bundle(self.bundle, out)

        with open(sha_path, "r", encoding="utf-8") as f:
            recorded, _, filename = f.read().strip().partition("  ")

        digest = hashlib.sha256()
        with open(tar_path, "rb") as f:
            for block in iter(lambda: f.read(8192), b""):
                digest.update(block)

        self.assertEqual(recorded, digest.hexdigest())
        self.assertEqual(filename, os.path.basename(tar_path),
                         "sha256sum -c is run from the upload dir, so the name must match")


if __name__ == "__main__":
    unittest.main()
