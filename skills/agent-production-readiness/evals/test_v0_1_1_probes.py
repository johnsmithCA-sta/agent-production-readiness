#!/usr/bin/env python3
"""v0.1.1 修复探针 + 全量回归。运行：python3 evals/test_v0_1_1_probes.py"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 技能根（本脚本位于 evals/）
SCORE = os.path.join(ROOT, "scripts", "score.py")
BENCH = os.path.join(ROOT, "evals", "benchmark.json")
PY = sys.executable

G = '{"M1":false,"M2":false,"M3":false,"M4":false,"M5":false}'
S85 = {"R1": 15, "R2": 13, "R3": 14, "R4": 9, "R5": 9, "R6": 13, "R7": 7, "R8": 5}


def run(args):
    r = subprocess.run([PY, SCORE] + args, capture_output=True, text=True)
    return r.returncode, (r.stdout.strip() or r.stderr.strip())


def run3(args):
    """返回 (rc, stdout, stderr)——用于需单独检查 stderr 的探针（v0.2.3）。"""
    r = subprocess.run([PY, SCORE] + args, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def main():
    passed = failed = 0

    def check(name, ok, detail=""):
        nonlocal passed, failed
        print(("PASS" if ok else "FAIL"), name, ("| " + detail) if detail else "")
        passed += ok
        failed += (not ok)

    # ── P0-1 gates 严格校验 ──
    rc, out = run(["--scores", json.dumps(S85), "--gates", '{"M1":false,"M2":"false","M3":false,"M4":false,"M5":false}'])
    check("P0-1a 字符串false被拒绝", rc == 2 and "布尔" in out, out.splitlines()[0][:80])
    rc, out = run(["--scores", json.dumps(S85), "--gates", '{"M1":false}'])
    check("P0-1b 缺键被拒绝", rc == 2 and "缺键" in out, out.splitlines()[0][:80])
    rc, out = run(["--scores", json.dumps(S85), "--gates", G, "--json"])
    check("P0-1c 正常gates通过", rc == 0, "")

    # ── P0-1（v0.2.2）：gates 失败关闭——未知键 / 重复键 ──
    # 未知键（M9）原被 gates.get() 静默丢弃 → 100 分误判 S
    rc, out = run(["--scores", json.dumps(S85), "--gates",
                   '{"M1":false,"M2":false,"M3":false,"M4":false,"M5":false,"M9":true}'])
    check("G6 未知键被拒", rc == 2 and "未知键" in out, out.splitlines()[0][:80])
    # 重复键（M5 出现两次，JSON 取末值 false）→ 一票否决被吞掉
    rc, out = run(["--scores", json.dumps(S85), "--gates",
                   '{"M1":false,"M2":false,"M3":false,"M4":false,"M5":true,"M5":false}'])
    check("G7 重复键被拒", rc == 2 and "重复键" in out, out.splitlines()[0][:80])

    # ── v0.2.3：可观测性与缺省护栏 ──
    # --help 曾因裸 % 抛 ValueError 而完全不可用（既有债、零测试覆盖 ⇒ 长期无人发现）
    rc, out, err = run3(["--help"])
    check("v0.2.3 --help可运行", rc == 0 and "--gates" in out and "--evidence" in out, f"rc={rc}")
    # 省略 --gates 时必须有运行期警示（rc 仍 0，供分维试算）
    rc, out, err = run3(["--scores", json.dumps(S85), "--json"])
    check("v0.2.3 省略gates有警示", rc == 0 and "不得用于正式定级" in err,
          (err.splitlines() or [""])[0][:70])

    # ── P1-1 场景B S 可达 ──
    sB = {"R1": 14, "R2": 10, "R3": 14, "R4": 14, "R5": 10, "R6": 12, "R7": 8, "R8": 4}
    rc, out = run(["--scores", json.dumps(sB), "--scenario", "B", "--gates", G, "--json"])
    d = json.loads(out)
    check("P1-1 场景B可达S", rc == 0 and d["grade"] == "S" and all(v["pass"] for v in d["floor_check"].values()),
          f"grade={d['grade']} floors=" + str({k: v["min"] for k, v in d["floor_check"].items()}))

    # ── P2-2 evidence C clamp ──
    rc, out = run(["--scores", json.dumps(S85), "--evidence", '{"R1":"C"}', "--gates", G, "--json"])
    d = json.loads(out)
    check("P2-2 C级clamp到10", rc == 0 and d["evidence_clamped"].get("R1", {}).get("capped") == 10 and d["total"] == 80,
          f"total={d['total']} clamped={d['evidence_clamped']}")
    rc, out = run(["--scores", json.dumps(S85), "--evidence", '{"R1":"X"}', "--gates", G])
    check("P2-2b 非法证据级拒绝", rc == 2, out.splitlines()[0][:80])

    # ── P2-3 越界带上限表 ──
    rc, out = run(["--scores", json.dumps({**S85, "R1": 19}), "--gates", G])
    check("P2-3 越界报错附上限", rc == 2 and "上限" in out, out.splitlines()[-1][:80])

    # ── 回归：benchmark 全量（14 例全覆盖，不得跳过任何用例——静默跳过=假 PASS） ──
    bench = json.load(open(BENCH, encoding="utf-8"))
    for c in bench["cases"]:
        # exit 类用例（gates 防御回归）：只断言退出码
        if "exit" in c["expect"]:
            rc, out = run(["--scores", json.dumps(c["scores"]), "--scenario", c["scenario"], "--gates", json.dumps(c["gates"])])
            check(f"基准{c['id']}", rc == c["expect"]["exit"], f"rc={rc} expect exit {c['expect']['exit']}")
            continue
        args = ["--scores", json.dumps(c["scores"]), "--scenario", c["scenario"], "--gates", json.dumps(c["gates"]), "--json"]
        if c.get("evidence"):
            args += ["--evidence", json.dumps(c["evidence"])]
        rc, out = run(args)
        if rc != 0:
            check(f"基准{c['id']}", False, "rc=" + str(rc))
            continue
        o = json.loads(out)
        ok = o["grade"] == c["expect"]["grade"]
        if "total" in c["expect"] and c["scenario"] == "default":
            ok = ok and o["total"] == c["expect"]["total"]
        check(f"基准 {c['id']}", ok, f"{o['total']}/{o['grade']} expect {c['expect']}")

    # ── M5 待审内容武器化 ──
    rc, out = run(["--scores", json.dumps(S85), "--gates", '{"M1":false,"M2":false,"M3":false,"M4":false,"M5":true}', "--json"])
    o = json.loads(out) if rc == 0 else {}
    check("M5 命中判D", rc == 0 and o.get("grade") == "D" and "M5" in ",".join(o.get("gates_hit", [])), f"{o.get('grade')} gates_hit={o.get('gates_hit')}")
    rc, out = run(["--scores", json.dumps(S85), "--gates", '{"M1":false,"M2":false,"M3":false,"M4":false}'])
    check("gates缺M5被拒", rc == 2, out.splitlines()[0][:70])

    # ── 回归：错误路径 ──
    rc, _ = run(["--scores", json.dumps({k: 1 for k in S85 if k != "R8"})])
    check("缺维rc2", rc == 2)
    rc, _ = run(["--scores", json.dumps({**S85, "R9": 1})])
    check("未知维rc2", rc == 2)

    print(f"== {passed}/{passed + failed} 通过 ==")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
