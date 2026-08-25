"""
tests/run_all.py
Layer: Test (W11)

Discovers and runs every test under tests/ and ui/tests/, prints a per-module
summary, and exits non-zero on failure.

The summary used to be empty for every passing module. It collected the test
cases by walking the suite *after* runner.run(), and unittest removes each test
from its suite as it runs it, so the walk always found nothing and only modules
with failures or skips appeared. The cases are now collected before the run.
"""

import os
import sys
import unittest


def collect(suite, into):
    """Flatten a TestSuite into a list of TestCase objects.

    Args:
        suite: a TestSuite or TestCase.
        into:  list that receives every TestCase found.

    Must be called BEFORE the suite is run: TestSuite drops its references to
    tests as it executes them, so walking afterwards yields nothing.
    """
    if isinstance(suite, unittest.TestCase):
        into.append(suite)
        return
    for item in suite:
        collect(item, into)


def module_of(test):
    """Return the module name a test belongs to.

    Args:
        test: a TestCase whose id() is "module.Class.method".
    """
    return test.id().split(".")[0]


def main():
    """Run every suite and print the summary table.

    Returns:
        Never returns; exits 0 when everything passed, 1 otherwise.
    """
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.discover(os.path.join(repo_root, "tests"), pattern="test_*.py"))

    ui_tests_dir = os.path.join(repo_root, "ui", "tests")
    if os.path.isdir(ui_tests_dir):
        suite.addTests(loader.discover(ui_tests_dir, pattern="test_*.py"))

    # Collected up front, for the reason in the module docstring.
    all_tests = []
    collect(suite, all_tests)

    stats = {}
    for test in all_tests:
        stats.setdefault(
            module_of(test), {"run": 0, "failures": 0, "skips": 0, "reasons": set()}
        )["run"] += 1

    result = unittest.TextTestRunner(verbosity=2).run(suite)

    for test, _ in result.failures + result.errors:
        entry = stats.setdefault(
            module_of(test), {"run": 0, "failures": 0, "skips": 0, "reasons": set()}
        )
        entry["failures"] += 1

    for test, reason in result.skipped:
        entry = stats.setdefault(
            module_of(test), {"run": 0, "failures": 0, "skips": 0, "reasons": set()}
        )
        entry["skips"] += 1
        entry["reasons"].add(reason)

    print("\n" + "=" * 78)
    print("TEST SUMMARY")
    print("=" * 78)
    print(f"{'Module':<40} | {'Tests':>5} | {'Failures':>8} | {'Skips':>5}")
    print("-" * 78)
    for module in sorted(stats):
        entry = stats[module]
        print(
            f"{module:<40} | {entry['run']:>5} | {entry['failures']:>8} | {entry['skips']:>5}"
        )
        for reason in sorted(entry["reasons"]):
            print(f"{'':<40} |   skipped: {reason}")
    print("-" * 78)
    print(
        f"{'TOTAL':<40} | {len(all_tests):>5} | "
        f"{len(result.failures) + len(result.errors):>8} | {len(result.skipped):>5}"
    )
    print("=" * 78)

    # A skip is not a pass. Skips are legitimate (the installer suite needs a
    # POSIX shell), but they must be visible in the last line a CI log shows.
    if result.skipped:
        print(
            f"NOTE: {len(result.skipped)} test(s) were skipped and asserted nothing. "
            "Run the suite on Linux for full coverage."
        )

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
