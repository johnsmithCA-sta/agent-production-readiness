# Contributing to agent-readiness-review

## 反馈评审结论
欢迎带证据 challenge：每个维度都有明确的扣分锚（`skills/agent-readiness-review/references/01-rubric.md`），分歧可以落到具体检查项上解决。开 issue 时请附：被审对象材料（或脱敏后的评分卡）、你的八维分、与本品结论的差异点。

## 修改规则库（rubric / gates / score.py）
1. 改动前先跑基准：`python3 skills/agent-readiness-review/scripts/run_benchmark.py`（应 11/11 PASS）
2. 改动后再跑：定级漂移或防御用例失败即为回归，必须先修
3. bump 版本（SKILL.md frontmatter）并在 `references/04-calibration.md` 追加变更小节

## 红线
- 本技能全程只读评审，任何改动不得引入对被审对象的写操作或代码执行
- 被审对象内容 = 数据 ≠ 指令（见 references/02-gates.md §评审者侧防护）
