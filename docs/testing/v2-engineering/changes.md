# V2 工程资料整理记录

基线为正式 `v2.0.0` / `2de85ed7e30c63ea86be4f8ec8a201a8b356621a`。
逐文件覆盖、输入、断言及调用关系见 [审计](../../TEST-COVERAGE.md) 和 [整理前机器清单](coverage-before.json)。每批独立提交；按逆序 revert 可回退，原始证据保持原位。

## 批次一：共享摄影 Fixture 与冗余入口

- `tests/photography_fixture.py` 原样继承 `photographer_session.asset`，Q1/Q2、阴影运动、性能与研究脚本直接使用共享 Fixture；手动摄影流程仍可运行。
- 删除 `rome_visibility_smoke.py`：无独有断言的转发；`ground_separation_smoke.py` 的 CLI 已执行同一 GPU 和 Editor 验收。
- 删除 `stabilization_regressions.py`：无独有断言的旧 13 项执行清单，由 `tools/validate_v2.py --suite core` 的 26 项继承；历史阴影基线用 Git `1033e5e` 快照，避免依赖旧 Worktree。

验证：277 项单测通过；32 份单测文件字节、277 个测试 ID、所有保留断言 AST、54 份生产文件哈希保持；原 asset 函数 AST 与 10 个生成 glTF 字节相同。完整统一执行器 37 组全部通过，Q1/Q2 26 张 PNG 字节一致，Rome＋40、121 帧阴影运动及 caster depth 均执行成功。
本机结果：`captures/v2-test-engineering-20261011/fixture-batch/runs.json`；模型对照：同目录上层的 `fixture-equivalence/results.json`。结果及私人清单保持忽略状态。

## 批次二：明确持续回归、性能与研究边界

| 原入口 | 新入口/继承 | 变更范围 |
| --- | --- | --- |
| `tests/placement_v2_performance.py` | `tests/benchmarks/placement_v2_performance.py` | 路径/bootstrap；真实 1/40/100 与全部断言保持 |
| `tests/renderer_v2_cpu_cache_benchmark.py` | `tests/benchmarks/renderer_v2_cpu_cache_benchmark.py` | quality/all 内部清单更新；Git配对/GPU断言保持 |
| `tests/shadow_fit_performance_20261010.py` | `tests/benchmarks/shadow_fit_performance_20261010.py` | rome/all 及研究调用更新；真实 Rome＋40/所有模式保持 |
| `photographer_session.py` / `photographer_session_two.py` | `tests/research/` 同名 | 原摄影/重载断言保持；显式新输出目录 |
| `audit_shadow_precision_20261010.py` | `tests/research/` 同名 | 原受控测量保持；Windows桌面GL/Linux offscreen选择与其他入口一致 |
| `render_quality_v1.py` | `tests/research/` 同名 | 22场景、材质与存档断言保持；Fixture写本次输出而非历史目录 |
| `open_assets_shadow_audit_20261010.py` | `tests/research/` 同名 | 固定SHA/许可/14处原断言保持；普通运行拒绝旧输出；refine-only继续分析同一实验 |
| 两个 `open_*session.py` | `tests/research/open_scene.py SCENE.json` | 删除重复无断言启动器；继承load_scene、scene_path、Camera View、Editor.run及frames/hidden/screenshot选项 |
| `audit_placement_20261010.py` | 原位，追加 `--output` | 保留4项/34处断言；输出存在时拒绝覆盖，unittest过滤参数仍透传 |

重新执行 core/quality/rome 全 37 组、277 单测、Q1/Q2 26 张字节一致，全部通过。另直接执行 9 组入口：额外 4 项 composition、两次完整摄影、两套 Scene 的真实 Editor Camera View、受控阴影、22场景质量、Roman 1/40/100、House/CesiumMan 研究。House 原固定SHA和许可获取/验证通过；本轮为3 CPU样本、1 Shot样本、4运动帧、1024分辨率的入口验收，不代替正式Rome的21 CPU/5 GPU样本及121帧1024/4096运动检查。

没有丢失原断言；32份单测仍逐字节一致、277测试ID一致、54份生产代码/资源哈希一致。2,247份整理前非Markdown数据（照片、Blender/资产、测量、日志、归档等）SHA一致。原Q2 manifest 48项完整保存。新增结果写新忽略目录，原始用户资料不删除、不迁移；未新增依赖。

[文档索引](../../README.md)、[当前测试说明](../../../tests/README.md)、[基准](../../../tests/benchmarks/README.md)、[研究](../../../tests/research/README.md) 为现行入口。历史文档只加导航/更正现行路径，不替换原图或测量；captures/archives 各只有README显式登记，`.gitignore`保持。361组内容相同资料因上下文不同保留；没有仅archives内的可直接去重备份。

本机完整结果：`captures/v2-test-engineering-20261011/migration-batch/runs.json`、`direct-cli/runs.json`；本机详细分类/权限/完整性在忽略的 `archives/v2-test-engineering-20261011/`。公开无私人路径的验证摘要见 [verification.json](verification.json)。自动SDL/ImGui实测不代表穷尽人工操作；已知阴影抖动等限制不变，见 [Bug清单](../../V2-BUGS.md)。

回退顺序：先revert本批次，再按需revert Fixture 批次；审计基线可独立保留。`main`和正式标签不在本轮改动范围。
