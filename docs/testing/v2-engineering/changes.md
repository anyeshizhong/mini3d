# V2 工程资料整理记录

基线为正式 `v2.0.0` / `2de85ed7e30c63ea86be4f8ec8a201a8b356621a`。
逐文件覆盖、输入、断言及调用关系见 [审计](../../TEST-COVERAGE.md) 和 [整理前机器清单](coverage-before.json)。每批独立提交；按逆序 revert 可回退，原始证据保持原位。

## 批次一：共享摄影 Fixture 与冗余入口

- `tests/photography_fixture.py` 原样继承 `photographer_session.asset`，Q1/Q2、阴影运动、性能与研究脚本直接使用共享 Fixture；手动摄影流程仍可运行。
- 删除 `rome_visibility_smoke.py`：无独有断言的转发；`ground_separation_smoke.py` 的 CLI 已执行同一 GPU 和 Editor 验收。
- 删除 `stabilization_regressions.py`：无独有断言的旧 13 项执行清单，由 `tools/validate_v2.py --suite core` 的 26 项继承；历史阴影基线用 Git `1033e5e` 快照，避免依赖旧 Worktree。

验证：277 项单测通过；32 份单测文件字节、277 个测试 ID、所有保留断言 AST、54 份生产文件哈希保持；原 asset 函数 AST 与 10 个生成 glTF 字节相同。完整统一执行器 37 组全部通过，Q1/Q2 26 张 PNG 字节一致，Rome＋40、121 帧阴影运动及 caster depth 均执行成功。
本机结果：`captures/v2-test-engineering-20261011/fixture-batch/runs.json`；模型对照：同目录上层的 `fixture-equivalence/results.json`。结果及私人清单保持忽略状态。
