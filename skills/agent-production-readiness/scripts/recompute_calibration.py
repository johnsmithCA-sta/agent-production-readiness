#!/usr/bin/env python3
"""校准表复算器（零依赖，仅标准库）。

用途
----
把 references/04-calibration.md 的「四核心基准 · 双轨逐锚复核表」固化为机器可
复算的 evals/calibration_cases.json，并逐维重算、再把各维得分回喂
scripts/score.py，核对 total / grade / floor_fail——证明校准表可被独立复核
（这是本技能向独立评审承诺「可复核」的立身之本）。

用法
----
  python3 scripts/recompute_calibration.py

无参数。技能根由 `os.path.dirname(os.path.abspath(__file__))` 的上一级定位，
因此可从任意 cwd 调用（不依赖相对路径）。score.py 以
`subprocess` + `sys.executable` 方式调用，**不 import**，以免生成 __pycache__。

复算规则
--------
  baseline = round(max × achieved / achievable)
  score    = baseline + Σ anchors.delta
  achievable = 适用检查项数（不适用项已剔除，见用例 excluded 字段）

退出码
------
  0 = 全绿：5 样本 × 8 维逐维零差异，且 total / grade / floor_fail 全部一致
  1 = 存在差异：任一维复算分 ≠ 表内分，或 total / grade / floor_fail 不符
  2 = 文件不可读：calibration_cases.json 缺失 / JSON 非法 / 结构非法，
      或 scripts/score.py 缺失

为何用 round() 而非截断
-----------------------
与 04-calibration.md 的历史口径「四舍五入取整」一致（表内基线即按此得出）。
反例自证：law-fetch 与 ui-design-eval 的 R1 为 3/4 × 18 = 13.5，表内记 14。
若用截断会得 13，直接与表冲突——故必须四舍五入。
全表唯一出现的 .5 恰是 13.5，其两侧 13（奇）/ 14（偶）中 14 为偶，故 Python
默认的「银行家舍入」（round-half-to-even）与常见「四舍五入（half-up）」在此
数据上结果一致，不触舍入方向分歧。若将来新增 x.5 且向下为偶的取值，需显式
改为 half-up（Decimal.quantize ROUND_HALF_UP），否则会静默偏差 1 分。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_PATH = os.path.join(ROOT, "evals", "calibration_cases.json")
SCORE_PATH = os.path.join(ROOT, "scripts", "score.py")

DIM_ORDER = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8")
KEY_DIMS = ("R1", "R2", "R3", "R6")          # 与 score.py 的关键维度一致
GATE_KEYS = ("M1", "M2", "M3", "M4", "M5")   # 校准样本无门槛命中 → 全 false

RC_OK, RC_DIFF, RC_UNREADABLE = 0, 1, 2


def die_unreadable(msg):
    print("[不可读] " + msg, file=sys.stderr)
    return RC_UNREADABLE


def load_cases():
    if not os.path.isfile(CASES_PATH):
        return None, die_unreadable(f"用例文件不存在: {CASES_PATH}")
    try:
        with open(CASES_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as e:
        return None, die_unreadable(f"用例文件读取失败: {e}")
    except json.JSONDecodeError as e:
        return None, die_unreadable(f"用例文件 JSON 非法: {e}")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        return None, die_unreadable("用例文件缺少非空的 cases 数组")
    return data, None


def recompute_dim(dim):
    """返回 (baseline, anchor_sum, 复算 score)。"""
    mx, ach, got = dim["max"], dim["achievable"], dim["achieved"]
    if not ach:
        raise ValueError("achievable 必须为正")
    baseline = round(mx * got / ach)
    anchor_sum = sum(int(a.get("delta", 0)) for a in dim.get("anchors", []))
    return baseline, anchor_sum, baseline + anchor_sum


def run_score(scores, scenario):
    """调用 score.py 核 total / grade / floor_fail；返回 (result_dict, err_msg)。"""
    if not os.path.isfile(SCORE_PATH):
        return None, f"score.py 不存在: {SCORE_PATH}"
    cmd = [
        sys.executable, SCORE_PATH,
        "--scores", json.dumps(scores),
        "--scenario", scenario,
        "--gates", json.dumps({g: False for g in GATE_KEYS}),
        "--json",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as e:
        return None, f"score.py 调用失败: {e}"
    if proc.returncode != 0:
        return None, f"score.py rc={proc.returncode}: {proc.stderr.strip()}"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as e:
        return None, f"score.py 输出非 JSON: {e}"


def main():
    data, rc = load_cases()
    if rc is not None:
        return rc
    scenario = data.get("scenario", "default")

    header = "样本 / 维度".ljust(30) + "满分/适用  达成   基线   锚    表内分  复算分  差异"
    print("=" * 96)
    print("校准表复算：references/04-calibration.md ⇄ evals/calibration_cases.json")
    print(f"场景 {scenario} ｜ 规则 baseline = round(max × achieved / achievable)；score = baseline + Σ anchors.delta")
    print("=" * 96)
    print(header)
    print("-" * 96)

    any_diff = False
    total_cases = 0
    total_dims = 0

    for case in data["cases"]:
        skill = case.get("skill", "?")
        dims = case.get("dims", {})
        expect = case.get("expect", {})
        date_note = ""
        recomputed = {}
        case_ok = True

        for dim in DIM_ORDER:
            d = dims.get(dim)
            if d is None:
                print(f"{skill}/{dim}".ljust(30) + "  缺少该维记录")
                any_diff = case_ok = False
                continue
            total_dims += 1
            baseline, anchor_sum, calc = recompute_dim(d)
            recomputed[dim] = calc
            table_score = d["score"]
            ok = calc == table_score
            case_ok &= ok
            anchor_txt = f"{anchor_sum:+d}" if anchor_sum else "—"
            print(
                f"{skill}/{dim}".ljust(30)
                + f"{d['max']:>3}/{d['achievable']:<3}  "
                + f"{d['achieved']}/{d['achievable']:<4}".ljust(7)
                + f"{baseline:>5}  {anchor_txt:>4}  "
                + f"{table_score:>6}  {calc:>6}  "
                + ("✓" if ok else "✗ 差异")
            )
            if not ok:
                any_diff = True
                print(f"      ↑ {skill}/{dim}: 表内 {table_score} ≠ 复算 {calc}"
                      f"（基线 {baseline} + 锚 {anchor_sum:+d}）")

        total_cases += 1
        table_total = sum(dims[k]["score"] for k in DIM_ORDER if k in dims)
        calc_total = sum(recomputed.values())
        result, err = run_score(recomputed, scenario)
        if err:
            print(f"  [{skill}] score.py 调用异常：{err}")
            any_diff = case_ok = False
            grade, floor, reason = "?", [], err
            total_ok = grade_ok = floor_ok = False
        else:
            total_ok = result["total"] == expect.get("total")
            grade = result["grade"]
            grade_ok = grade == expect.get("grade")
            floor = [k for k in KEY_DIMS if not result["floor_check"][k]["pass"]]
            floor_ok = sorted(floor) == sorted(expect.get("floor_fail", []))
            reason = result["reason"]
            if not (total_ok and grade_ok and floor_ok):
                any_diff = case_ok = False

        print(
            f"  → 表内合计 {table_total} ｜ 复算合计 {calc_total} ｜ 差异 "
            f"{calc_total - table_total:+d} ｜ score.py: {result['total'] if result else '?'}/{result['max'] if result else '?'} "
            f"{grade} ｜ floor_fail {floor if floor else '无'}"
        )
        print(
            f"  → 期望 {expect.get('total')} {expect.get('grade')} / floor_fail "
            f"{expect.get('floor_fail')} ｜ total {'✓' if total_ok else '✗'} "
            f"grade {'✓' if grade_ok else '✗'} floor {'✓' if floor_ok else '✗'}"
            f" ｜ 定级理由：{reason}"
        )
        print(f"  → 本样本：{'全绿' if case_ok else '有差异'}{date_note}")
        print("-" * 96)

    print(f"汇总：{total_cases} 样本 × {total_dims} 维；逐维差异 "
          f"{'0 处' if not any_diff else '存在'}；total / grade / floor_fail "
          f"{'全部一致' if not any_diff else '存在不一致'}")
    print("结果：全绿（校准表可复算）" if not any_diff else "结果：存在差异，请核对")
    return RC_OK if not any_diff else RC_DIFF


if __name__ == "__main__":
    sys.exit(main())
