# -*- coding: utf-8 -*-
"""
W25 지연 상위 20개 편명 중 2개 조합(C(20,2)=190쌍) 전체에 대해 build_ontime_scenario.py를
--auto-skip-unresolved --no-save --summary-json 옵션으로 반복 실행하고 결과를 취합한다.

각 조합은 실제 스왑/이식 기반 정시성 최적화를 그대로 적용한다(근사 스크리닝 없음,
build_ontime_scenario.py의 로직을 축소하지 않고 서브프로세스로 그대로 재사용).

사용 예:
    python run_pair_batch.py
    python run_pair_batch.py --workers 14
    python run_pair_batch.py --aggregate-only   # 재실행 없이 기존 결과만 취합/랭킹 출력
"""
import argparse
import io
import itertools
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', write_through=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', write_through=True)

TOP20_FLTNOS = [
    '7C122', '7C140', '7C130', '7C907', '7C505', '7C132', '7C134', '7C141', '7C227', '7C131',
    '7C138', '7C228', '7C135', '7C706', '7C124', '7C128', '7C142', '7C705', '7C504', '7C137',
]

SOURCE_XLSX = r'c:\Users\admin\Downloads\upload_template (W25).xlsx'
RESULTS_DIR = Path('pair_search_results')
LOG_DIR = RESULTS_DIR / 'logs'


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workers', type=int, default=14, help='동시 실행 서브프로세스 수(기본 14)')
    p.add_argument('--aggregate-only', action='store_true', help='재실행 없이 기존 pair_search_results/*.json만 취합')
    return p.parse_args()


def run_pair(f1, f2):
    """(f1, f2, ok, summary_or_error) 반환. summary_path가 이미 있으면 재실행하지 않는다(재개 가능)."""
    summary_path = RESULTS_DIR / f'{f1}_{f2}.json'
    if summary_path.exists():
        try:
            return f1, f2, True, json.loads(summary_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass  # 손상된 파일이면 재실행

    log_path = LOG_DIR / f'{f1}_{f2}.log'
    cmd = [
        sys.executable, 'build_ontime_scenario.py',
        '--cancel', f'{f1},{f2}',
        '--name', 'batch',
        '--source', SOURCE_XLSX,
        '--auto-skip-unresolved', '--no-save',
        '--summary-json', str(summary_path),
    ]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(proc.stdout)
        f.write('\n--- STDERR ---\n')
        f.write(proc.stderr)

    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            return f1, f2, True, summary
        except (OSError, ValueError) as e:
            return f1, f2, False, f'summary-json 파싱 실패: {e}'

    elapsed = time.time() - t0
    return f1, f2, False, f'summary-json 미생성(exit={proc.returncode}, {elapsed:.0f}s) — 로그: {log_path}'


def aggregate():
    rows = []
    for jf in sorted(RESULTS_DIR.glob('*.json')):
        try:
            rows.append(json.loads(jf.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            print(f'[경고] 손상된 결과 파일: {jf}')
    total_pairs = len(list(itertools.combinations(TOP20_FLTNOS, 2)))
    print(f'\n=== 취합 결과: {len(rows)}/{total_pairs}쌍 수집 ===')

    feasible = [r for r in rows if r.get('feasible') and r.get('domestic_delta_pp') is not None]
    infeasible = [r for r in rows if not r.get('feasible')]
    print(f'feasible(skip<=80%): {len(feasible)}쌍 / infeasible(skip>80%): {len(infeasible)}쌍')

    feasible.sort(key=lambda r: r['domestic_delta_pp'], reverse=True)
    print('\n=== 국내선 정시율 개선폭 상위 20쌍 ===')
    print(f"{'편1':>7} {'편2':>7} {'개선(pp)':>9} {'skip%':>7} {'전':>7} {'후':>7}")
    for r in feasible[:20]:
        f1, f2 = r['cancel']
        print(f"{f1:>7} {f2:>7} {r['domestic_delta_pp']:>9.2f} {r['skip_pct']*100:>6.1f}% "
              f"{r['domestic_before_rate']:>7} {r['domestic_after_rate']:>7}")

    out_path = RESULTS_DIR / '_aggregated.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'feasible': feasible, 'infeasible': infeasible}, f, ensure_ascii=False, indent=2)
    print(f'\n취합 결과 저장: {out_path}')
    return feasible, infeasible


def main():
    args = parse_args()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if args.aggregate_only:
        aggregate()
        return

    pairs = list(itertools.combinations(TOP20_FLTNOS, 2))
    print(f'후보 편명 {len(TOP20_FLTNOS)}개 -> {len(pairs)}쌍, workers={args.workers}')

    t0 = time.time()
    done = 0
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(run_pair, f1, f2): (f1, f2) for f1, f2 in pairs}
        for fut in as_completed(futures):
            f1, f2, ok, result = fut.result()
            done += 1
            elapsed = time.time() - t0
            if ok:
                dp = result.get('domestic_delta_pp')
                print(f'[{done}/{len(pairs)}] {f1},{f2} 완료 (개선 {dp}pp, feasible={result.get("feasible")}), '
                      f'누적 경과 {elapsed/60:.1f}분')
            else:
                failed.append((f1, f2, result))
                print(f'[{done}/{len(pairs)}] {f1},{f2} 실패: {result}')

    print(f'\n배치 완료: {len(pairs)}쌍, 실패 {len(failed)}건, 총 소요 {(time.time()-t0)/60:.1f}분')
    for f1, f2, err in failed:
        print(f'  실패: {f1},{f2} -> {err}')

    aggregate()


if __name__ == '__main__':
    main()
