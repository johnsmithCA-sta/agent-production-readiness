#!/usr/bin/env python3
"""v0.1.1 修复探针 + 全量回归。运行：python3 evals/test_v0_1_1_probes.py"""
import json
import subprocess
import sys

G = '{"M1":false,"M2":false,"M3":false,"M4":false}'
S85 = {"R1": 15, "R2": 13, "R3": 14, "R4": 9, "R5": 9, "R6": 13, "R7": 7, "R8": 5}


def run(args):
    r = subprocess.run(["python3", "scripts/score.py"] + args, capture_output=True, text=True)
    return r.returncode, (r.stdout.strip() or r.stderr.strip())


def main():
    passed = failed = 0

    def check(name, ok, detail=""):
        nonlocal passed, failed
        print(("PASS" if ok else "FAIL"), name, ("| " + detail) if detail else "")
        passed += ok
        failed += (not ok)

    # ── P0-1 gates 严格校验 ──
    rc, out = run(["--scores", json.dumps(S85), "--gates", '{"M1":false,"M2":"false","M3":false,"M4":false}'])
    check("P0-1a 字符串false被拒绝", rc == 2 and "布尔" in out, out.splitlines()[0][:80])
    rc, out = run(["--scores", json.dumps(S85), "--gates", '{"M1":false}'])
    check("P0-1b 缺键被拒绝", rc == 2 and "缺键" in out, out.splitlines()[0][:80])
    rc, out = run(["--scores", json.dumps(S85), "--gates", G, "--json"])
    check("P0-1c 正常gates通过", rc == 0, "")

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

    # ── 回归：benchmark 全量 ──
    bench = json.load(open("evals/benchmark.json"))
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

    # ── 回归：错误路径 ──
    rc, _ = run(["--scores", json.dumps({k: 1 for k in S85 if k != "R8"})])
    check("缺维rc2", rc == 2)
    rc, _ = run(["--scores", json.dumps({**S85, "R9": 1})])
    check("未知维rc2", rc == 2)

    print(f"== {passed}/{passed + failed} 通过 ==")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
