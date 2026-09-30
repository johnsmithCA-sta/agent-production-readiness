#!/usr/bin/env python3
"""agent-production-readiness 评分计算（零依赖，仅标准库）。

用法：
  python3 scripts/score.py --scores '{"R1":14,...}' --scenario default \
      --gates '{"M1":false,...}' [--evidence '{"R1":"A",...}'] [--json]

v0.1.1 修复（依据跨 harness 实测报告）：
  - P0-1 gates 严格校验：提供时必须四键齐全、值必须布尔；不明确即拒绝（退出码 2）。
  - P1-1 关键维度底线改比例制：≥ ceil(75% × 该场景维度满分)——双场景 S 级均可达。
  - P2-2 --evidence：C 级证据自动 clamp 至该维满分 60%。
  - P2-3 越界报错附带当前场景各维上限表。

退出码：0 正常；2 输入错误（缺键/类型错/越界/未知维度）。
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
KEY_DIMS = ("R1", "R2", "R3", "R6")
FLOOR_RATIO = {"R1": 0.60, "R2": 0.75, "R3": 0.75, "R6": 0.75}  # P1-1：按维比例。R1 用 0.60（default 底线 11/18）与 v0.2 四样本校准的绝对值一致，防止历史 S 级基准（85/S）漂移；R2/R3/R6 用 0.75 与校准值 12/16 一致
EVIDENCE_CLAMP = 0.60       # P2-2：C 级证据该维最高 60%
GATE_KEYS = ("M1", "M2", "M3", "M4")
GATE_NAMES = {"M1": "M1 凭据裸露", "M2": "M2 高风险无守卫", "M3": "M3 注入即执行", "M4": "M4 可疑脚本"}


def fail(msg):
    print("输入错误: " + msg, file=sys.stderr)
    sys.exit(2)


def floor_min(dim, maxv):
    return math.ceil(FLOOR_RATIO[dim] * maxv)


def parse_gates(raw):
    """P0-1：键齐全 + 布尔类型，不明确即拒绝。"""
    try:
        gates = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(f"gates JSON 解析失败: {e}")
    if not isinstance(gates, dict):
        fail("gates 必须是 JSON 对象")
    missing = [g for g in GATE_KEYS if g not in gates]
    if missing:
        fail(f"gates 缺键: {missing}（安全项必须显式声明，不提供请整体省略用默认全 false）")
    bad = [g for g in gates if not isinstance(gates[g], bool)]
    if bad:
        fail(f"gates 值必须为布尔: {bad}（得到 {[gates[g] for g in bad]}）——不明确即拒绝")
    return {g: gates.get(g, False) for g in GATE_KEYS}


def parse_evidence(raw, w):
    """P2-2：返回 {dim: clamp 后上限}；仅对提供的键生效。"""
    if not raw:
        return {}
    try:
        ev = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(f"evidence JSON 解析失败: {e}")
    if not isinstance(ev, dict):
        fail("evidence 必须是 JSON 对象")
    clamps = {}
    for k, v in ev.items():
        if k not in w:
            fail(f"evidence 未知维度: {k}")
        if v not in ("A", "B", "C"):
            fail(f"evidence[{k}] 必须为 A/B/C，得到 {v!r}")
        if v == "C":
            clamps[k] = int(w[k] * EVIDENCE_CLAMP)
    return clamps


def main():
    ap = argparse.ArgumentParser(description="agent-production-readiness 评分计算 v0.2.0")
    ap.add_argument("--scores", required=True, help='JSON，如 {"R1":14,...,"R8":6}')
    ap.add_argument("--scenario", default="default", choices=["default", "A", "B"])
    ap.add_argument("--gates", default=None,
                    help='JSON，四键齐全且全布尔；缺省视为全 false')
    ap.add_argument("--evidence", default=None, help='JSON，如 {"R1":"A","R4":"C"}；C 级自动 clamp 60%')
    ap.add_argument("--json", action="store_true", help="JSON 输出（供 CI 集成）")
    args = ap.parse_args()

    try:
        scores = json.loads(args.scores)
    except json.JSONDecodeError as e:
        fail(f"scores JSON 解析失败: {e}")
    if not isinstance(scores, dict):
        fail("scores 必须是 JSON 对象")

    w = WEIGHTS[args.scenario]
    gates = parse_gates(args.gates) if args.gates else {g: False for g in GATE_KEYS}
    clamps = parse_evidence(args.evidence, w)

    # P2-2：先应用 C 级 clamp，再校验范围
    clamped_note = {}
    for k, cap in clamps.items():
        if scores.get(k, 0) > cap:
            clamped_note[k] = {"raw": scores[k], "capped": cap}
            scores[k] = cap

    # 校验（P2-3：越界报错附场景上限表）
    errs = []
    for k, maxv in w.items():
        v = scores.get(k)
        if v is None:
            errs.append(f"{k} 缺失")
        elif not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 <= v <= maxv):
            errs.append(f"{k}={v} 超出 [0,{maxv}]（场景 {args.scenario} 上限）")
    unknown = [k for k in scores if k not in w]
    if unknown:
        errs.append(f"未知维度: {unknown}")
    if errs:
        limit_table = " ".join(f"{k}:{m}" for k, m in w.items())
        fail("; ".join(errs) + f"\n场景 {args.scenario} 各维上限: {limit_table}")

    total = sum(scores[k] for k in w)
    hit = [g for g in GATE_KEYS if gates[g]]
    floor_fail = [k for k in KEY_DIMS if scores[k] < floor_min(k, w[k])]

    if hit:
        grade, reason = "D", f"命中门槛 {'/'.join(GATE_NAMES[g] for g in hit)}，禁止上生产"
    elif total >= 85 and not floor_fail:
        grade, reason = "S", "生产就绪，可无人值守上线"
    elif total >= 75:
        grade = "A"
        reason = "基本就绪，灰度+人工抽查"
        if floor_fail:
            reason += f"；关键维度未达 S 底线（按 v0.2 校准比例）:{'/'.join(floor_fail)}"
    elif total >= 60:
        grade, reason = "B", "部分就绪，修复中危项后复评"
    else:
        grade, reason = "C", "未就绪，系统性补课"

    result = {
        "total": total, "max": sum(w.values()), "grade": grade, "reason": reason,
        "scenario": args.scenario,
        "gates_hit": hit,
        "floor_rule": "关键维度底线(比例·v0.2校准对齐): " + ",".join(f"{d}>={int(r*100)}%" for d, r in FLOOR_RATIO.items()),
        "floor_check": {k: {"score": scores[k], "min": floor_min(k, w[k]), "max": w[k], "pass": scores[k] >= floor_min(k, w[k])} for k in KEY_DIMS},
        "evidence_clamped": clamped_note,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"总分 {total}/{result['max']} → {grade} 级")
        print(f"判定：{reason}")
        if hit:
            print("门槛命中：" + "、".join(GATE_NAMES[g] for g in hit))
        for k in KEY_DIMS:
            f = result["floor_check"][k]
            print(f"  {k}: {f['score']}/{f['max']}（S 底线 {f['min']}）{'✓' if f['pass'] else '✗'}")
        if clamped_note:
            print("证据 clamp：" + "、".join(f"{k} {v['raw']}→{v['capped']}（C 级上限）" for k, v in clamped_note.items()))
    sys.exit(0)


if __name__ == "__main__":
    main()
