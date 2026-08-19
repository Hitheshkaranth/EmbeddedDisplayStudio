"""
tests/run_all.py
Layer: Test (W11)
Discovers and runs all tests in tests/ and ui/tests/.
Prints a summary table and exits non-zero on failure.
"""

import os
import sys
import unittest

def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Discover in tests/
    tests_dir = os.path.join(repo_root, "tests")
    suite.addTests(loader.discover(tests_dir, pattern="test_*.py"))
    
    # Discover in ui/tests/
    ui_tests_dir = os.path.join(repo_root, "ui", "tests")
    if os.path.isdir(ui_tests_dir):
        suite.addTests(loader.discover(ui_tests_dir, pattern="test_*.py"))
        
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"{'Module / Class':<40} {'Status':<15}")
    print("-" * 60)
    
    # Collate results
    all_tests = []
    
    # Traverse suite to extract individual tests
    def _extract(s):
        if isinstance(s, unittest.TestCase):
            all_tests.append(s)
        elif isinstance(s, unittest.TestSuite):
            for t in s:
                _extract(t)
    _extract(suite)
    
    # We will just print the aggregate if desired, but requirement says:
    # "prints a summary table (module, tests, failures, skips with reasons)"
    
    modules = {}
    for t in all_tests:
        mod = t.id().split('.')[0]
        if mod not in modules:
            modules[mod] = {"run": 0, "failures": 0, "skips": [], "skip_reasons": []}
        modules[mod]["run"] += 1
        
    # Account for failures/errors
    for t, err in result.failures + result.errors:
        mod = t.id().split('.')[0]
        if mod not in modules:
            modules[mod] = {"run": 0, "failures": 0, "skips": [], "skip_reasons": []}
        modules[mod]["failures"] += 1
        
    for t, reason in result.skipped:
        mod = t.id().split('.')[0]
        if mod not in modules:
            modules[mod] = {"run": 0, "failures": 0, "skips": [], "skip_reasons": []}
        modules[mod]["skips"].append(t)
        modules[mod]["skip_reasons"].append(reason)
        
    print(f"{'Module':<35} | {'Tests':<5} | {'Failures':<8} | {'Skips'}")
    print("-" * 75)
    for mod, stats in modules.items():
        skips_count = len(stats["skips"])
        print(f"{mod:<35} | {stats['run']:<5} | {stats['failures']:<8} | {skips_count}")
        if skips_count > 0:
            for reason in set(stats["skip_reasons"]):
                print(f"  -> Skip reason: {reason}")
                
    print("="*75)
    
    if not result.wasSuccessful():
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
