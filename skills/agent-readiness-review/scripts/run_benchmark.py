#!/usr/bin/env python3
"""基准回归 runner（零依赖，仅标准库）。

一键重跑 evals/benchmark.json 全部用例，比对「总分 / 定级 / 退出码」三类期望。
规则库（rubric / gates / score.py）每次变更后必跑——定级漂移或防御失效立即报警。

用法：
  python3 scripts/run_benchmark.py            # 跑全部用例
  python3 scripts/run_benchmark.py --json     # JSON 输出（供 CI）
退出码：0 全绿；1 有用例失败；2 用例文件不可读。
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCORE = os.path.join(HERE, "score.py")
BM = os.path.join(os.path.dirname(HERE), "evals", "benchmark.json")
PY = sys.executable


def run_case(case):
    args = [PY, SCORE,
            "--scores", json.dumps(case["scores"]),
            "--scenario", case.get("scenario", "default"),
            "--gates", json.dumps(case["gates"]),
            "--json"]
    if case.get("evidence"):
        args += ["--evidence", json.dumps(case["evidence"])]
    p = subprocess.run(args, capture_output=True, text=True)

    exp = case["expect"]
    # 期望退出码优先：用于「应当被拒绝的非法输入」类回归（如 gates 传字符串）
    if "exit" in exp:
        return {"pass": p.returncode == exp["exit"],
                "detail": f"退出码 {p.returncode}（预期 {exp['exit']}）",
                "stderr": p.stderr.strip().splitlines()[:1]}
    if p.returncode != 0:
        return {"pass": False, "detail": f"意外退出码 {p.returncode}: {p.stderr.strip()[:120]}", "stderr": []}
    r = json.loads(p.stdout)
    ok = (("total" not in exp or r["total"] == exp["total"]) and r["grade"] == exp["grade"])
    return {"pass": ok, "total": r["total"], "grade": r["grade"],
            "detail": f"总分 {r['total']}（预期 {exp.get('total')}）定级 {r['grade']}（预期 {exp['grade']}）",
            "stderr": []}


def main():
    ap = argparse.ArgumentParser(description="agent-readiness-review 基准回归")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        cases = json.load(open(BM, encoding="utf-8"))["cases"]
    except Exception as e:
        print(f"用例文件读取失败: {e}", file=sys.stderr)
        sys.exit(2)

    results = []
    for c in cases:
        r = run_case(c)
        r["id"] = c["id"]
        r["name"] = c["name"]
        results.append(r)

    passed = sum(1 for r in results if r["pass"])
    if args.json:
        print(json.dumps({"passed": passed, "total": len(results), "results": results},
                         ensure_ascii=False, indent=2))
    else:
        print(f"基准回归：evals/benchmark.json（{len(cases)} 用例）")
        print("-" * 72)
        for r in results:
            flag = "PASS" if r["pass"] else "FAIL"
            print(f"[{flag}] {r['id']:<26} {r['detail']}")
            for line in r.get("stderr", []):
                print(f"        {line[:110]}")
        print("-" * 72)
        print(f"--> {passed}/{len(cases)} PASS")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
