# Mini3D V2 文档索引

正式 V2 发布基线为 `v2.0.0` / `2de85ed7e30c63ea86be4f8ec8a201a8b356621a`。当前用法与验证从以下入口查阅；阶段报告保留实验时的代码、参数和结果，不承担当前命令的权威入口。

| 当前入口 | 内容 |
| --- | --- |
| [V2 功能](V2-FEATURES.md) | Placement、Rendering、Photography、AI API 和启动方式 |
| [架构](ARCHITECTURE.md) | 模块边界、核心入口及数据流 |
| [Bug 与限制](V2-BUGS.md) | 已修复问题、回归证据、尚存质量限制 |
| [正式验证](V2-VALIDATION.md) | 发布候选原始测试与 GPU 验收 |
| [测试覆盖](TEST-COVERAGE.md) | 77 份基线脚本逐文件审计与重复关系 |
| [测试执行说明](../tests/README.md) | 当前单测、37 组执行器、研究与基准入口 |
| [工程整理记录](testing/v2-engineering/changes.md) | 每批迁移/删除继承关系与实际验收 |

## 功能设计与历史证据

Placement [V1](placement-v1.md) / [V2](placement-v2.md)、[AI API](ai-api-v1.md)、[摄影持久化](shot-camera-persistence.md)、[光照](lighting-v1.md)、[方向光](directional-light.md)、[阴影](shadow-mapping-v1.md)、[真实资产阴影](shadow-assets.md)、[Scene裁剪](scene-clipping.md)、[Ground分离](ground-separation.md)、[Rome整合](rome-integration.md) 是具体能力和故障的设计/验收记录。参数接口以正式 V2 与当前测试脚本为准。

[Renderer V2](renderer-v2/)、[Q1](renderer-v2/q1/)、[Q2](renderer-v2/q2/)、[Render Quality V1](render-quality-v1/)、[Stabilization V1](stabilization-v1/)、[摄影/阴影研究](testing/) 保留带版本的原图、Scene、原始测量和失败前后证据；Q2 Blender 场景、HDR 和许可文件不得当作缓存清理。文档主题相近并不表示实验相同，未发现可直接删除的字节相同 Markdown。

[开发进度](development-progress.md)、[Editor审计](editor-audit.md)、[V2 Consolidation审计](V2-CONSOLIDATION-AUDIT.md)、[Rome旧可见性实验](rome-visibility.md) 是当时的决策记录。已退休的命令或 Worktree 路径保留为历史事实；现行入口与迁移映射见测试执行说明。

本机资料政策见 [captures](../captures/README.md) 和 [archives](../archives/README.md)。私人清单、绝对路径和未提交资料仅在本机忽略目录保存，不能推送公开仓库。
