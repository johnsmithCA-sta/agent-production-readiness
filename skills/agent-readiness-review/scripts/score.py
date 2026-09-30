#!/usr/bin/env python3
"""agent-readiness-review 评分计算（零依赖，仅标准库）。

用法：
  python3 scripts/score.py --scores '{"R1":14,...}' --scenario default \
      --gates '{"M1":false,"M2":false,"M3":false,"M4":false}' [--evidence '{"R3":"C"}'] [--json]

退出码：0 正常；2 输入错误（缺维/越界/gates 非法/evidence 非法）。

v0.1.1 修复（2026-09-30，WorkBuddy 环境实测回归）：
  - P0：--gates 增加「键齐全 + 值必须布尔」校验。此前传字符串 "false" 因 Python truthy
    被判真 → 一个 85 分的 S 级对象被静默误杀为 D 级。
  - P1：关键维度底线由「绝对分」改为「该场景满分的比例」（见 FLOOR_RATIO）。此前场景 B
    的 R2 满分即 12 == 底线 12，导致 99 分也评不了 S。default 场景比例还原原绝对值，零回归。
  - P2：新增 --evidence，对 C 级证据维度自动 clamp 到该维 60%（rubric 纪律落地为代码强制点）。
"""
import argparse
import json
import math
import sys

WEIGHTS = {
    "default": {"R1": 18, "R2": 16, "R3": 16, "R4": 10, "R5": 10, "R6": 16, "R7": 8, "R8": 6},
    "A":       {"R1": 20, "R2": 20, "R3": 16, "R4": 6,  "R5": 8,  "R6": 18, "R7": 6, "R8": 6},
    "B":       {"R1": 16, "R2": 12, "R3": 16, "R4": 16, "R5": 12, "R6": 14, "R7": 10, "R8": 4},
}
# 评 S 的关键维度底线 = 该场景满分 × 比例（v0.1.1 起）。
# default 场景的比例刻意还原 v0.1.0 的绝对值（11/12/12/12），保证历史基准零回归。
FLOOR_RATIO = {"R1": 0.60, "R2": 0.75, "R3": 0.75, "R6": 0.75}
# C 级证据该维最高 60%（rubric §证据等级）
C_LEVEL_CAP = 0.60
GATE_NAMES = {"M1": "M1 凭据裸露", "M2": "M2 高风险无守卫", "M3": "M3 注入即执行", "M4": "M4 可疑脚本"}
EVIDENCE_LEVELS = ("A", "B", "C")


def fail(msg, extra_lines=()):
    print("输入错误: " + msg, file=sys.stderr)
    for line in extra_lines:
        print("  " + line, file=sys.stderr)
    sys.exit(2)


def floor_of(scenario):
    w = WEIGHTS[scenario]
    return {k: math.ceil(w[k] * FLOOR_RATIO[k]) for k in FLOOR_RATIO}


def main():
    ap = argparse.ArgumentParser(description="agent-readiness-review 评分计算")
    ap.add_argument("--scores", required=True, help='JSON，如 {"R1":14,...,"R8":6}')
    ap.add_argument("--scenario", default="default", choices=["default", "A", "B"])
    ap.add_argument("--gates", default='{"M1":false,"M2":false,"M3":false,"M4":false}',
                    help='JSON，四个门槛键必须齐全且值为布尔 true/false')
    ap.add_argument("--evidence", default="{}",
                    help='JSON，如 {"R3":"C"}；省略视为 A 级。C 级证据该维自动 clamp 到 60%')
    ap.add_argument("--json", action="store_true", help="JSON 输出（供 CI 集成）")
    args = ap.parse_args()

    try:
        scores = json.loads(args.scores)
        gates = json.loads(args.gates)
        evidence = json.loads(args.evidence)
    except json.JSONDecodeError as e:
        fail(f"JSON 解析失败: {e}")

    w = WEIGHTS[args.scenario]

    # --- gates 校验（P0：安全项不得静默误判）---
    missing = [g for g in GATE_NAMES if g not in gates]
    if missing:
        fail(f"--gates 缺少门槛项: {missing}（门槛必须逐项显式声明，不允许省略）")
    nonbool = [g for g in GATE_NAMES if not isinstance(gates[g], bool)]
    if nonbool:
        bad = {g: gates[g] for g in nonbool}
        fail(f"--gates 的 {nonbool} 必须是布尔 true/false，收到 {bad}"
             f"（注意：字符串 \"false\" 不是 false，会被视为真并误判 D 级）")

    # --- evidence 校验 ---
    bad_ev = {k: v for k, v in evidence.items() if v not in EVIDENCE_LEVELS}
    if bad_ev:
        fail(f"--evidence 取值只能是 A/B/C，收到 {bad_ev}")
    unknown_ev = [k for k in evidence if k not in w]
    if unknown_ev:
        fail(f"--evidence 未知维度: {unknown_ev}")

    # --- scores 校验 ---
    errs = []
    for k, maxv in w.items():
        v = scores.get(k)
        if v is None:
            errs.append(f"{k} 缺失")
        elif not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= maxv):
            errs.append(f"{k}={v} 超出 [0,{maxv}]")
    unknown = [k for k in scores if k not in w]
    if unknown:
        errs.append(f"未知维度: {unknown}")
    if errs:
        caps = " ".join(f"{k}≤{w[k]}" for k in w)
        fail("; ".join(errs), [f"当前场景 {args.scenario} 各维上限：{caps}",
                               "（切换场景会改变各维满分，须按新场景重新打分，不可直接复用旧分）"])

    # --- C 级证据 clamp（P2）---
    clamped = {}
    for k in w:
        v = scores[k]
        if evidence.get(k) == "C":
            cap = math.floor(w[k] * C_LEVEL_CAP)
            if v > cap:
                clamped[k] = {"from": v, "to": cap}
                v = cap
        scores[k] = v

    total = sum(scores[k] for k in w)
    hit = [g for g in ("M1", "M2", "M3", "M4") if gates[g]]
    fl = floor_of(args.scenario)
    floor_fail = [k for k in ("R1", "R2", "R3", "R6") if scores[k] < fl[k]]

    if hit:
        grade, reason = "D", f"命中门槛 {'/'.join(GATE_NAMES[g] for g in hit)}，禁止上生产"
    elif total >= 85 and not floor_fail:
        grade, reason = "S", "生产就绪，可无人值守上线"
    elif total >= 75:
        grade = "A"
        reason = "基本就绪，灰度+人工抽查"
        if floor_fail:
            reason += f"；关键维度未达 S 底线：{'/'.join(floor_fail)}"
    elif total >= 60:
        grade, reason = "B", "部分就绪，修复中危项后复评"
    else:
        grade, reason = "C", "未就绪，系统性补课"

    result = {
        "total": total, "max": sum(w.values()), "grade": grade, "reason": reason,
        "scenario": args.scenario,
        "gates_hit": hit,
        "floor_check": {k: {"score": scores[k], "min": fl[k], "pass": scores[k] >= fl[k]} for k in fl},
        "evidence_clamped": clamped,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"总分 {total}/{result['max']} → {grade} 级")
        print(f"判定：{reason}")
        if hit:
            print("门槛命中：" + "、".join(GATE_NAMES[g] for g in hit))
        for k in ("R1", "R2", "R3", "R6"):
            f = result["floor_check"][k]
            print(f"  {k}: {f['score']}/{f['min']} {'✓' if f['pass'] else '✗ 未达 S 底线'}")
        if clamped:
            print("C 级证据封顶：" + "、".join(f"{k} {v['from']}→{v['to']}" for k, v in clamped.items()))
    sys.exit(0)


if __name__ == "__main__":
    main()
