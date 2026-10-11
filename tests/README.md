# V2 测试入口

从正式项目根目录使用已有 Python 环境运行。依赖仍为项目 `requirements.txt`，不需要新增运行时。GPU/UI 入口需要真实桌面 OpenGL；可选模型需按 `model/manifest.json` 登记安装，缺模型必须报告，不能以替代资产冒充验收。

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B tools/validate_v2.py --suite all --output captures/my-new-v2-run
```

输出目录必须是新目录。`validate_v2` 接口保持 `--suite core|quality|rome|all --output`：core 为单测和编辑器/Placement/光照/摄影/API/GPU回归，quality 为 Renderer、CPU cache、Q1/Q2，rome 为真实 Rome＋40、Editor、附加模型、性能、阴影运动和 caster depth。all 共 37 组入口，包含 277 项单测。执行器顺序运行，自动生成 Git `1033e5e` 历史阴影快照，不依赖旧 Worktree。退出码和 `runs.json.passed` 共同作为结果；Q1/Q2 共 26 张 PNG 必须与原图字节一致。

| 位置 | 用途 | 执行方式 |
| --- | --- | --- |
| 根目录 `test_*.py` | 32 份长期单元回归，277 个测试身份 | unittest discover；统一执行器 core/all |
| 根目录其他回归脚本 | 真实 GL/UI/API、原始照片对照、缺陷与限制复现 | validate_v2；逐文件参数见脚本 CLI 和覆盖清单 |
| `lighting_fixture.py` / `photography_fixture.py` | 共享原始 PBR/几何资产生成，不是独立验收入口 | 回归脚本导入 |
| `render_smoke.py` | 历史示例导航循环 Fixture | demo_equivalence 导入，也可直接运行 |
| [benchmarks/](benchmarks/README.md) | 3 份性能基准；保留独立正确性断言和原始计时 | CPU cache 和真实 Shadow Fit 仍由统一执行器调用 |
| [research/](research/README.md) | 5 份研究/摄影采集，以及统一手动 Scene 启动器 | 显式输入与新输出目录，分别记录实验条件 |

额外 4 项组合工作流不在 `test_*.py` 的 277 项中，应独立运行：

```powershell
python -B tests/audit_placement_20261010.py --output captures/my-new-composition
```

整理前每份脚本的输入、调用者、独有断言和历史故障覆盖见 [完整覆盖](../docs/TEST-COVERAGE.md)，迁移映射与实测见 [批次记录](../docs/testing/v2-engineering/changes.md)。Placement V1/V2 使用不同尺度/事件，UI 与 API 使用不同边界，CPU oracle 与 GPU 像素互补，不能根据文件名相似移除。

阴影运动脚本继续留在根目录。它记录动态 fit、固定 fit、世界空间 probe/depth 差异；成功执行代表限制可复现，不代表已修复摄影机移动时的阴影抖动。纯性能结果只在同资产、参数、硬件条件下比较，不以异机耗时替代正确性阈值。
