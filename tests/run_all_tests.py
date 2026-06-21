#!/usr/bin/env python3
"""
Full test runner — runs all test suites and prints a summary report.

Usage:
    python3 tests/run_all_tests.py              # all tests including integration
    RUN_INTEGRATION_TESTS=0 python3 tests/run_all_tests.py  # skip FFmpeg renders
"""

import sys
import unittest
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TEST_SUITES = [
    ('Style Config (Parts 1.1–1.4)',    'tests.test_style_config'),
    ('Custom Duration (Part 2)',         'tests.test_custom_duration'),
    ('Timeline Builder (Parts 3–4)',     'tests.test_timeline_full'),
    ('Intro/Outro Scoring',              'tests.test_intro_outro'),
    ('FFmpeg Integration (Part 5)',      'tests.test_ffmpeg_integration'),
    ('Regression Tests (Parts 7–10)',    'tests.test_regression_full'),
    ('Regeneration Flow',                'tests.test_regeneration'),
    # VI2 layer tests
    ('Reject Reason Builder (VI2-013)', 'tests.test_reject_reason_builder'),
    ('Scoring Service (VI2-012/016)',    'tests.test_scoring_service'),
    ('Timeline Service (VI2-011)',       'tests.test_timeline_service'),
    ('Shot Boundary Detector (VI2-010)','tests.test_shot_boundary_detector'),
    ('Composition Analyzer (VI2-008)',   'tests.test_composition_analyzer'),
    ('Pose Analyzer (VI2-007)',          'tests.test_pose_analyzer'),
    ('Eye State Analyzer (VI2-007)',     'tests.test_eye_state_analyzer'),
    ('Video Intelligence Service',       'tests.test_video_intelligence_service'),
]


def run_suite(name: str, module_name: str) -> tuple:
    """Load and run a test module. Returns (tests_run, failures, errors, skip)."""
    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromName(module_name)
    except Exception as e:
        print(f"  ✗ LOAD ERROR: {e}")
        return 0, 0, 1, 0

    runner = unittest.TextTestRunner(
        stream=open('/dev/null', 'w'),  # suppress per-test output
        verbosity=0
    )
    t0 = time.time()
    result = runner.run(suite)
    elapsed = time.time() - t0

    n_run    = result.testsRun
    n_fail   = len(result.failures)
    n_err    = len(result.errors)
    n_skip   = len(result.skipped)
    ok       = n_fail == 0 and n_err == 0

    status = "✅ PASSED" if ok else "❌ FAILED"
    print(f"  {status}  {name}")
    print(f"           {n_run} tests | {n_fail} failures | {n_err} errors | "
          f"{n_skip} skipped | {elapsed:.1f}s")

    if not ok:
        for test, traceback in result.failures + result.errors:
            # Print just the last few lines of each failure
            lines = traceback.strip().split('\n')
            print(f"    → {test}")
            for line in lines[-4:]:
                print(f"      {line}")

    return n_run, n_fail, n_err, n_skip


def main():
    print("\n" + "═" * 70)
    print("  AUTO VIDEO EDITOR — Full Test Suite")
    print("═" * 70)

    total_run  = 0
    total_fail = 0
    total_err  = 0
    total_skip = 0
    failed_suites = []

    for name, module in TEST_SUITES:
        n_run, n_fail, n_err, n_skip = run_suite(name, module)
        total_run  += n_run
        total_fail += n_fail
        total_err  += n_err
        total_skip += n_skip
        if n_fail > 0 or n_err > 0:
            failed_suites.append(name)

    print()
    print("─" * 70)
    print("TEST SUMMARY")
    print("─" * 70)
    print(f"  Total:    {total_run} tests")
    print(f"  Passed:   {total_run - total_fail - total_err} tests")
    print(f"  Failed:   {total_fail} tests")
    print(f"  Errors:   {total_err} tests")
    print(f"  Skipped:  {total_skip} tests (integration / manual)")
    print()

    if failed_suites:
        print(f"  ❌ FAILED SUITES ({len(failed_suites)}):")
        for s in failed_suites:
            print(f"     • {s}")
    else:
        print("  ✅ ALL SUITES PASSED")
    print("═" * 70)

    # Stress tests — manual
    print()
    print("STRESS TESTS (manual / nightly):")
    print("  • 10 files × 6-8 GB: run with actual large video files")
    print("  • Mixed source formats: VFR, rotation metadata, different codecs")
    print("  Command: python3 -m unittest tests.test_stress -v")
    print()

    sys.exit(0 if not failed_suites else 1)


if __name__ == '__main__':
    main()
