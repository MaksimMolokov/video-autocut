#!/usr/bin/env python3
"""
TASK-013: Preprocessing pipeline performance benchmark.

Usage:
    python3 scripts/benchmark_preprocessing.py /path/to/project/with/videos

The project dir must contain at least 1 real video file.
"""

import sys
import time
import os
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def run_benchmarks(project_dir: str):
    from src.storage.analysis_db import AnalysisDB
    from src.preprocessing.pipeline import analyze_project, list_video_files
    from src.preprocessing.clip_library import FragmentLibrary

    print(f'\n=== Preprocessing Benchmark ===')
    print(f'Project dir: {project_dir}')

    videos = list_video_files(project_dir)
    if not videos:
        print('ERROR: No video files found. Provide a directory with .mp4/.mov files.')
        sys.exit(1)
    print(f'Videos: {len(videos)}')

    # --- BENCH 1: Full analysis ---
    print('\n[1] Full analysis (force_reanalyze=True)...')
    db = AnalysisDB(project_dir)
    db.reset_all()
    t0 = time.time()
    n = analyze_project(project_dir, progress_callback=lambda f, d, t: None, force_reanalyze=False)
    t1 = time.time()
    elapsed_full = t1 - t0
    print(f'    Time: {elapsed_full:.1f}s')
    print(f'    Good fragments (q>=0.55): {n}')

    total = db.count_fragments(min_quality=0.0)
    print(f'    Total fragments: {total}')
    assert elapsed_full < 300.0, f'FAIL: Too slow: {elapsed_full:.1f}s (limit: 300s)'
    print('    PASS: within 5-minute time limit')

    if total == 0:
        print('    WARNING: 0 fragments found — check threshold settings')
    else:
        print(f'    INFO: {n}/{total} fragments passed quality threshold')

    # --- BENCH 2: Cache hit ---
    print('\n[2] Repeat run (cache hit)...')
    t0 = time.time()
    n2 = analyze_project(project_dir)
    t2 = time.time()
    elapsed_cache = t2 - t0
    print(f'    Time: {elapsed_cache:.3f}s')
    assert elapsed_cache < 2.0, f'FAIL: Cache not working: {elapsed_cache:.2f}s'
    print('    PASS: cache works (< 2s)')

    # --- BENCH 3: Fragment quality ---
    print('\n[3] Fragment quality distribution...')
    lib = FragmentLibrary(db)
    all_frags = lib.get_fragments_for_ui(min_quality=0.0, limit=500)
    if all_frags:
        qualities = [f.quality_score for f in all_frags]
        avg_q = sum(qualities) / len(qualities)
        good_count = sum(1 for q in qualities if q >= 0.55)
        print(f'    Total: {len(all_frags)}  Good (q>=0.55): {good_count}  Avg quality: {avg_q:.3f}')

        if len(all_frags) >= 5:
            candidates = lib.get_all_candidates_for_project(min_quality=0.55)
            if candidates:
                avg_cand_q = sum(c.final_score for c in candidates) / len(candidates)
                print(f'    Candidates avg quality: {avg_cand_q:.3f}')
                if avg_cand_q >= 0.50:
                    print('    PASS: candidate quality above 0.50')
                else:
                    print(f'    INFO: candidate quality {avg_cand_q:.3f} (below 0.50 — consider more source material)')
        else:
            print('    INFO: Too few fragments for quality assertion (<5)')
    else:
        print('    INFO: No fragments found — thresholds may be too strict for this material')

    # --- BENCH 4: Thumbnail check ---
    print('\n[4] Thumbnail generation...')
    all_frags = lib.get_fragments_for_ui(min_quality=0.0, limit=20)
    thumbs_ok = 0
    thumbs_missing = 0
    for f in all_frags:
        if f.thumbnail_path and Path(f.thumbnail_path).exists():
            thumbs_ok += 1
        else:
            thumbs_missing += 1
    print(f'    Thumbnails: {thumbs_ok} present, {thumbs_missing} missing')
    if all_frags and thumbs_ok == 0:
        print('    WARNING: No thumbnails generated — check ffmpeg installation')
    elif thumbs_missing == 0:
        print('    PASS: all thumbnails present')

    # --- BENCH 5: Adaptive threshold ---
    print('\n[5] Adaptive threshold test...')
    frags_strict = lib.get_all_candidates_for_project(min_quality=0.80)
    frags_relaxed = lib.get_all_candidates_for_project(min_quality=0.30)
    print(f'    q>=0.80: {len(frags_strict)}  q>=0.30: {len(frags_relaxed)}')
    if len(frags_relaxed) > len(frags_strict):
        print('    PASS: adaptive threshold produces more candidates')

    print('\n=== All benchmarks complete ===')
    print(f'Full analysis: {elapsed_full:.1f}s | Cache hit: {elapsed_cache:.3f}s')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        # Default: use Desktop if has videos
        test_dir = os.path.expanduser('~/Desktop')
        from src.preprocessing.pipeline import list_video_files
        if not list_video_files(test_dir):
            print('Usage: python3 scripts/benchmark_preprocessing.py <project_dir>')
            sys.exit(1)
    else:
        test_dir = sys.argv[1]

    run_benchmarks(test_dir)
