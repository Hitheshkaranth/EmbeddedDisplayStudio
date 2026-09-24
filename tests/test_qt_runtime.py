"""
tests/test_qt_runtime.py
Layer: Test

Pins tools/hmi_deployer/qt_runtime.py: the Windows-side port of
deploy/provision_pyside2.sh and the wheel fetchers for Qt bundles
(CONTRACT 4.1, 6).

Everything here is offline and synthetic except LiveBuildTest, which builds
the real PySide2 runtime (~100+ MB download) and runs only with
QT_RUNTIME_LIVE=1.
"""

import gzip
import io
import lzma
import os
import pathlib
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.hmi_deployer import qt_runtime as qr  # noqa: E402


def _ar_header(name: bytes, size: int) -> bytes:
    """One 60-byte ar member header."""
    return (name.ljust(16) + b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6)
            + b"100644".ljust(8) + str(size).encode().ljust(10) + b"`\n")


def make_ar(members) -> bytes:
    """An ar archive of (name bytes, body bytes), GNU-style names."""
    out = bytearray(qr.AR_MAGIC)
    for name, body in members:
        out += _ar_header(name, len(body)) + body
        if len(body) & 1:
            out += b"\n"
    return bytes(out)


def _tar_add(tf, name, data=None, *, mode=0o644, symlink=None, isdir=False, hardlink=None):
    """Add a synthetic member to an open TarFile."""
    info = tarfile.TarInfo(name)
    info.mode = mode
    if isdir:
        info.type = tarfile.DIRTYPE
        tf.addfile(info)
    elif symlink is not None:
        info.type, info.linkname = tarfile.SYMTYPE, symlink
        tf.addfile(info)
    elif hardlink is not None:
        info.type, info.linkname = tarfile.LNKTYPE, hardlink
        tf.addfile(info)
    else:
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))


def make_deb(path, build_data, compression="xz"):
    """Write a .deb whose data.tar.<compression> is filled by build_data(tf)."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tf:
        build_data(tf)
    data = raw.getvalue()
    if compression == "xz":
        data = lzma.compress(data)
    elif compression == "gz":
        data = gzip.compress(data)
    ctrl = io.BytesIO()
    with tarfile.open(fileobj=ctrl, mode="w:gz"):
        pass
    pathlib.Path(path).write_bytes(make_ar([
        (b"debian-binary/", b"2.0\n"),
        (b"control.tar.gz/", ctrl.getvalue()),
        (f"data.tar.{compression}/".encode(), data),
    ]))


class ArParsingTest(unittest.TestCase):
    """The hand-rolled ar reader: .deb is an ar archive and Windows has no ar."""

    def test_members_names_and_odd_padding(self):
        blob = make_ar([(b"debian-binary/", b"2.0\n"), (b"odd/", b"abc"), (b"even", b"wxyz")])
        self.assertEqual(qr.parse_ar(blob),
                         [("debian-binary", b"2.0\n"), ("odd", b"abc"), ("even", b"wxyz")])

    def test_gnu_long_names_bsd_names_and_symbol_table(self):
        table = b"a_very_long_member_name.txt/\n"
        bsd_body = b"bsdname.bin" + b"payload"
        blob = make_ar([(b"/", b"\0\0\0\0"), (b"//", table), (b"/0", b"long"),
                        (b"#1/11", bsd_body)])
        self.assertEqual(qr.parse_ar(blob),
                         [("a_very_long_member_name.txt", b"long"), ("bsdname.bin", b"payload")])

    def test_rejects_non_ar_and_truncation(self):
        with self.assertRaises(ValueError):
            qr.parse_ar(b"PK\x03\x04")
        blob = make_ar([(b"x/", b"12345")])
        with self.assertRaises(ValueError):
            qr.parse_ar(blob[:-3])

    def test_zst_data_is_a_clear_error(self):
        blob = make_ar([(b"debian-binary/", b"2.0\n"), (b"data.tar.zst/", b"\x28\xb5")])
        with self.assertRaisesRegex(RuntimeError, "zst"):
            qr.deb_data_tar(blob, "libfoo")


PACKAGES = """\
Package: root
Depends: liba (>= 1.0), libb | libc, python3:any, virt-thing, qtbase-abi-5-15-8
Filename: pool/r/root.deb

Package: liba
Depends: libc6 (>= 2.34), libdeep
Filename: pool/a/liba.deb
Description: first line
 continuation: line that looks like a field

Package: libb
Filename: pool/b/libb.deb

Package: libc
Filename: pool/c/libc.deb

Package: libdeep
Filename: pool/d/libdeep.deb

Package: provider
Provides: virt-thing (= 1)
Depends: libz
Filename: pool/p/provider.deb

Package: python3
Filename: pool/p/python3.deb

Package: libz
Filename: pool/z/libz.deb
"""


class ClosureTest(unittest.TestCase):
    """Port of the bash script's embedded resolver."""

    def test_closure(self):
        pkgs, provides = qr.parse_packages_index(PACKAGES)
        self.assertEqual(provides["virt-thing"], ["provider"])
        order = qr.resolve_closure(pkgs, provides, ["root"], skip={"libc6", "python3"})
        names = [p["Package"] for p in order]
        # First alternative only; :any stripped then skipped; Provides followed;
        # virtual prefix dropped; SKIP pruned with its dependencies.
        self.assertEqual(names, ["root", "liba", "libb", "libdeep", "provider", "libz"])
        self.assertNotIn("libc", names)
        self.assertEqual(order[0]["Filename"], "pool/r/root.deb")

    def test_dep_names(self):
        self.assertEqual(qr._dep_names("a (>= 1) | b, c:any, , d:arm64 (<< 2)"),
                         ["a", "c", "d"])


def _deb_one(tf):
    """Qt lib chain, a plugin tree and the bindings, as bookworm lays them out."""
    ma = "./usr/lib/aarch64-linux-gnu"
    _tar_add(tf, "./usr", isdir=True, mode=0o755)
    _tar_add(tf, f"{ma}/libQt5Core.so.5.15.8", b"ELF-core", mode=0o644)
    _tar_add(tf, f"{ma}/libQt5Core.so.5.15", symlink="libQt5Core.so.5.15.8")
    _tar_add(tf, f"{ma}/libQt5Core.so.5", symlink="libQt5Core.so.5.15")
    _tar_add(tf, f"{ma}/libabs.so.1", symlink="/usr/lib/aarch64-linux-gnu/libQt5Core.so.5")
    _tar_add(tf, f"{ma}/libhard.so.1", hardlink=f"{ma}/libQt5Core.so.5.15.8")
    _tar_add(tf, f"{ma}/sub/libnested.so.1", b"nested")      # below maxdepth 1
    _tar_add(tf, f"{ma}/libnot-a-lib.a", b"static")
    _tar_add(tf, f"{ma}/qt5/plugins", isdir=True, mode=0o755)
    _tar_add(tf, f"{ma}/qt5/plugins/platforms", isdir=True, mode=0o755)
    _tar_add(tf, f"{ma}/qt5/plugins/platforms/libqwayland-egl.so", b"wl", mode=0o644)
    _tar_add(tf, "./usr/lib/python3/dist-packages/PySide2", isdir=True, mode=0o755)
    _tar_add(tf, "./usr/lib/python3/dist-packages/PySide2/__init__.py", b"# pyside2\n")
    _tar_add(tf, "./usr/lib/python3/dist-packages/PySide2/QtWidgets.cpython-311-aarch64-linux-gnu.so",
             b"ELF-w", mode=0o644)
    _tar_add(tf, "./usr/share/doc/x/copyright", b"(c)")


def _deb_two(tf):
    """A later package: overrides a lib and ships one under /lib."""
    _tar_add(tf, "./lib/aarch64-linux-gnu/libz.so.1", b"zlib", mode=0o644)
    _tar_add(tf, "./usr/lib/aarch64-linux-gnu/libQt5Core.so.5.15.8", b"ELF-core-v2", mode=0o644)


def make_cpython(path):
    """A tiny install_only-shaped tarball."""
    with tarfile.open(path, "w:gz") as tf:
        _tar_add(tf, "python", isdir=True, mode=0o755)
        _tar_add(tf, "python/bin", isdir=True, mode=0o755)
        _tar_add(tf, "python/bin/python3.11", b"#!elf", mode=0o755)
        _tar_add(tf, "python/bin/python3", symlink="python3.11")
        _tar_add(tf, "python/lib/python3.11/site-packages", isdir=True, mode=0o755)
        _tar_add(tf, "python/lib/python3.11/site-packages/README.txt", b"readme")


def make_wheel(path, files):
    """A wheel zip with the given {name: bytes}."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


class AssemblyTest(unittest.TestCase):
    """Streaming .deb members into the runtime tarball without extracting."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.cpy = self.tmp / "cpython.tar.gz"
        make_cpython(self.cpy)
        self.deb1, self.deb2 = self.tmp / "one.deb", self.tmp / "two.deb"
        make_deb(self.deb1, _deb_one, "xz")
        make_deb(self.deb2, _deb_two, "gz")
        self.whl = self.tmp / "pkg-1.0-py3-none-any.whl"
        make_wheel(self.whl, {"pkg/__init__.py": b"x=1\n",
                              "pkg-1.0.dist-info/METADATA": b"Name: pkg\n",
                              "pkg-1.0.data/purelib/extra_mod.py": b"y=2\n",
                              "pkg-1.0.data/scripts/tool": b"#!python\n"})
        self.out = self.tmp / "out.tar.gz"
        self.stats = qr.assemble_runtime(self.cpy, [self.deb1, self.deb2], self.out,
                                         wheels=[self.whl], progress=lambda s: None)
        self.tf = tarfile.open(self.out, "r:gz")
        self.members = {m.name: m for m in self.tf.getmembers()}

    def tearDown(self):
        self.tf.close()
        self._tmp.cleanup()

    def read(self, name):
        return self.tf.extractfile(self.members[name]).read()

    def test_no_duplicate_entries_and_single_top_dir(self):
        names = [m.name for m in self.tf.getmembers()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n == "python" or n.startswith("python/") for n in names))

    def test_cpython_copied_with_modes_and_symlink(self):
        self.assertEqual(self.members["python/bin/python3.11"].mode & 0o777, 0o755)
        link = self.members["python/bin/python3"]
        self.assertTrue(link.issym())
        self.assertEqual(link.linkname, "python3.11")
        self.assertIn("python/lib/python3.11/site-packages/README.txt", self.members)

    def test_lib_sweep_keeps_symlink_chain(self):
        lib = qr.OUT_QT_LIB
        so5 = self.members[f"{lib}/libQt5Core.so.5"]
        self.assertTrue(so5.issym())
        self.assertEqual(so5.linkname, "libQt5Core.so.5.15")
        self.assertTrue(self.members[f"{lib}/libQt5Core.so.5.15"].issym())
        # Later package wins, as successive dpkg-deb -x would.
        self.assertEqual(self.read(f"{lib}/libQt5Core.so.5.15.8"), b"ELF-core-v2")
        # Absolute target flattened to a same-directory basename.
        self.assertEqual(self.members[f"{lib}/libabs.so.1"].linkname, "libQt5Core.so.5")
        # Hard link materialised as a regular file (with the first package's bytes).
        hard = self.members[f"{lib}/libhard.so.1"]
        self.assertTrue(hard.isreg())
        self.assertEqual(self.read(f"{lib}/libhard.so.1"), b"ELF-core")
        self.assertEqual(self.read(f"{lib}/libz.so.1"), b"zlib")
        self.assertNotIn(f"{lib}/libnested.so.1", self.members)
        self.assertNotIn(f"{lib}/libnot-a-lib.a", self.members)
        self.assertEqual(self.stats["dangling"], [])

    def test_plugins_and_bindings(self):
        plug = f"{qr.OUT_QT_PLUGINS}/platforms/libqwayland-egl.so"
        self.assertEqual(self.read(plug), b"wl")
        self.assertTrue(self.members[f"{qr.OUT_QT_PLUGINS}/platforms"].isdir())
        site = qr.OUT_SITE
        self.assertEqual(self.read(f"{site}/PySide2/__init__.py"), b"# pyside2\n")
        self.assertIn(f"{site}/PySide2/QtWidgets.cpython-311-aarch64-linux-gnu.so", self.members)
        self.assertFalse(any("usr/share" in n for n in self.members))

    def test_ownership_is_root(self):
        m = self.members[f"{qr.OUT_QT_LIB}/libz.so.1"]
        self.assertEqual((m.uid, m.gid, m.uname), (0, 0, "root"))

    def test_wheel_installed_into_site_packages(self):
        site = qr.OUT_SITE
        self.assertEqual(self.read(f"{site}/pkg/__init__.py"), b"x=1\n")
        self.assertEqual(self.read(f"{site}/extra_mod.py"), b"y=2\n")
        self.assertIn(f"{site}/pkg-1.0.dist-info/METADATA", self.members)
        self.assertFalse(any(n.endswith("/tool") for n in self.members))


class PipArgvTest(unittest.TestCase):
    """How pip is launched from a source run and from the frozen Studio."""

    def test_unfrozen(self):
        with mock.patch.object(qr.sys, "frozen", False, create=True):
            self.assertEqual(qr.pip_argv(["download", "x"]),
                             [sys.executable, "-m", "pip", "download", "x"])

    def test_frozen(self):
        with mock.patch.object(qr.sys, "frozen", True, create=True):
            self.assertEqual(qr.pip_argv(["wheel"]), [sys.executable, "--pip-install", "wheel"])

    def test_fallback_flag_matches_native_preview(self):
        try:
            from tools.hmi_deployer.native_preview import PIP_FLAG
        except ImportError:
            self.skipTest("PySide6 not installed")
        self.assertEqual(PIP_FLAG, qr._PIP_FLAG_FALLBACK)


def _write_wheel(dirpath, filename, requires=()):
    """Drop a wheel named `filename` with Requires-Dist lines into dirpath."""
    dist, ver = filename.split("-")[:2]
    meta = "Metadata-Version: 2.1\nName: %s\n" % dist
    meta += "".join(f"Requires-Dist: {r}\n" for r in requires)
    make_wheel(pathlib.Path(dirpath) / filename,
               {f"{dist}-{ver}.dist-info/METADATA": meta.encode()})


class FakePip:
    """Stands in for _run_pip: download succeeds only for `binary`, wheel builds `built`."""

    def __init__(self, binary, built):
        self.binary, self.built, self.calls = binary, built, []

    def __call__(self, args, progress):
        self.calls.append(args)
        req = args[-1]
        name = qr._canon(req)
        if args[0] == "download":
            if name not in self.binary:
                return 1, "ERROR: No matching distribution found"
            dest = args[args.index("--dest") + 1]
            _write_wheel(dest, self.binary[name])
            return 0, ""
        if args[0] == "wheel":
            if name not in self.built:
                return 1, "error: build failed"
            fname, requires = self.built[name]
            _write_wheel(args[args.index("-w") + 1], fname, requires)
            return 0, ""
        raise AssertionError(args)


class AppWheelsTest(unittest.TestCase):
    """Binary download first; local pure-Python build as the fallback."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_with(self, fake, dists, pyver="3.11"):
        with mock.patch.object(qr, "_run_pip", fake):
            return qr.app_wheels(dists, pyver, lambda s: None, cache=self.cache)

    def test_sdist_only_accepted_when_pure_and_deps_resolved(self):
        fake = FakePip(
            binary={"pyserial": "pyserial-3.5-py2.py3-none-any.whl",
                    "netifaces2": "netifaces2-0.1-cp311-cp311-manylinux_2_28_aarch64.whl"},
            built={"networkscan": ("networkscan-1.0-py3-none-any.whl",
                                   ["netifaces2>=0.1", "colorama; sys_platform == 'win32'",
                                    "pytest; extra == 'test'",
                                    "tomli; python_version < '3.11'"])},
        )
        out = self.run_with(fake, ["pyserial", "networkscan"])
        names = sorted(p.name for p in out.glob("*.whl"))
        self.assertEqual(names, ["netifaces2-0.1-cp311-cp311-manylinux_2_28_aarch64.whl",
                                 "networkscan-1.0-py3-none-any.whl",
                                 "pyserial-3.5-py2.py3-none-any.whl"])
        download = fake.calls[0]
        self.assertIn("--only-binary=:all:", download)
        self.assertIn("manylinux_2_39_aarch64", download)
        self.assertEqual(download[download.index("--python-version") + 1], "3.11")

    def test_platform_wheel_built_locally_is_rejected(self):
        fake = FakePip(binary={}, built={"cext": ("cext-1.0-cp312-cp312-win_amd64.whl", [])})
        with self.assertRaisesRegex(RuntimeError, "cext"):
            self.run_with(fake, ["cext"], "3.12")

    def test_packaged_studio_takes_published_wheels_only(self):
        """A onefile Studio re-unpacks itself for every build subprocess, so a
        source build would run for many minutes; it is not attempted, and
        the operator is told why."""
        fake = FakePip(binary={}, built={})
        lines = []
        with mock.patch.object(qr.sys, "frozen", True, create=True), \
                mock.patch.object(qr, "_run_pip", fake):
            with self.assertRaisesRegex(RuntimeError, "srconly"):
                qr.app_wheels(["srconly"], "3.12", lines.append, cache=self.cache)
        wheel_call = fake.calls[-1]
        self.assertEqual(wheel_call[0], "wheel")
        self.assertIn("--only-binary=:all:", wheel_call)
        self.assertTrue(any("only as source code" in line for line in lines))

    def test_failure_names_every_missing_distribution(self):
        fake = FakePip(binary={"ok": "ok-1-py3-none-any.whl"}, built={})
        with self.assertRaises(RuntimeError) as ctx:
            self.run_with(fake, ["ok", "gone-a", "gone_b"])
        self.assertIn("gone-a", str(ctx.exception))
        self.assertIn("gone_b", str(ctx.exception))

    def test_directory_is_refreshed_per_call(self):
        fake = FakePip(binary={"ok": "ok-1-py3-none-any.whl"}, built={})
        out = self.run_with(fake, ["ok"])
        (out / "stale-0-py3-none-any.whl").write_bytes(b"")
        out2 = self.run_with(fake, ["ok"])
        self.assertEqual(out, out2)
        self.assertEqual([p.name for p in out2.iterdir()], ["ok-1-py3-none-any.whl"])

    def test_portable_wheel_names(self):
        self.assertTrue(qr.is_portable_wheel("a-1-py3-none-any.whl"))
        self.assertTrue(qr.is_portable_wheel("a-1-py2.py3-none-any.whl"))
        self.assertFalse(qr.is_portable_wheel("a-1-py2-none-any.whl"))
        self.assertFalse(qr.is_portable_wheel("a-1-cp312-cp312-win_amd64.whl"))
        self.assertFalse(qr.is_portable_wheel("a-1-cp312-none-win_amd64.whl"))

    def test_markers(self):
        env = qr._marker_env("3.11")
        self.assertTrue(qr.marker_matches("python_version >= '3.8' and os_name == 'posix'", env))
        self.assertFalse(qr.marker_matches('python_version < "3.10"', env))
        self.assertTrue(qr.marker_matches("(sys_platform == 'win32' or platform_machine == 'aarch64')", env))
        self.assertFalse(qr.marker_matches("platform_system not in 'Windows Darwin' and sys_platform == 'x'", env))


class CacheNameTest(unittest.TestCase):
    """A recipe change must not reuse an old tarball."""

    def test_name_tracks_recipe(self):
        name = qr.pyside2_runtime_name()
        self.assertIn(qr.PY_VER, name)
        with mock.patch.object(qr, "SKIP_PKGS", qr.SKIP_PKGS + ("libfoo",)):
            self.assertNotEqual(qr.pyside2_runtime_name(), name)

    def test_cached_tarball_is_returned_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / qr.pyside2_runtime_name()
            out.write_bytes(b"x")
            with mock.patch.object(qr, "_fetch_bytes", side_effect=AssertionError("network")):
                self.assertEqual(qr.build_pyside2_runtime(lambda s: None, cache=tmp), out)


class PySide6WheelsTest(unittest.TestCase):
    """Cache hit on the names PyPI actually serves (lower-case project name)."""

    def test_cached_dir_skips_pip(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp) / "pyside6" / "6.11.2"
            d.mkdir(parents=True)
            for n in ("pyside6_essentials-6.11.2-cp310-abi3-manylinux_2_39_aarch64.whl",
                      "shiboken6-6.11.2-cp310-abi3-manylinux_2_39_aarch64.whl"):
                (d / n).write_bytes(b"")
            with mock.patch.object(qr, "_run_pip", side_effect=AssertionError("pip")):
                self.assertEqual(qr.pyside6_wheels(lambda s: None, cache=tmp), d)

    def test_download_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def fake(args, progress):
                calls.append(args)
                dest = pathlib.Path(args[args.index("--dest") + 1])
                (dest / "pyside6_essentials-6.9.0-cp39-abi3-manylinux_2_28_aarch64.whl").write_bytes(b"")
                (dest / "shiboken6-6.9.0-cp39-abi3-manylinux_2_28_aarch64.whl").write_bytes(b"")
                return 0, ""

            with mock.patch.object(qr, "_run_pip", fake):
                qr.pyside6_wheels(lambda s: None, version="6.9.0", cache=tmp)
            args = calls[0]
            self.assertEqual(args[-1], "PySide6-Essentials==6.9.0")
            self.assertEqual(args[args.index("--python-version") + 1], "3.12")
            self.assertIn("manylinux2014_aarch64", args)


@unittest.skipUnless(os.environ.get("QT_RUNTIME_LIVE") == "1", "set QT_RUNTIME_LIVE=1")
class LiveBuildTest(unittest.TestCase):
    """Builds the real runtime from Debian and python-build-standalone."""

    def test_build(self):
        import fnmatch
        cache = os.environ.get("QT_RUNTIME_CACHE") or tempfile.mkdtemp(prefix="qtrt-live-")
        lines = []
        path = qr.build_pyside2_runtime(lambda s: (lines.append(s), print(s)), cache=cache)
        with tarfile.open(path, "r:gz") as tf:
            names = tf.getnames()
        self.assertEqual(len(names), len(set(names)))
        for pattern in ("python/bin/python3",
                        "python/qt5/lib/libQt5Core.so.5*",
                        "python/lib/python3.11/site-packages/PySide2/QtWidgets*.so",
                        "python/qt5/plugins/platforms/libqwayland*.so",
                        "python/lib/python3.11/site-packages/serial/__init__.py"):
            self.assertTrue(fnmatch.filter(names, pattern), pattern)
        print(f"\n{path.name}: {path.stat().st_size / 1e6:.1f} MB, {len(names)} members, "
              f"{sum(n.startswith('python/qt5/lib/') for n in names)} in qt5/lib")


if __name__ == "__main__":
    unittest.main()
