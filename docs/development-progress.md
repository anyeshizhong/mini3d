# Mini3D 开发进度

更新：2026-10-10。

稳定化 V1 第一阶段：Issue #5 的 Gizmo 跨 Assets 面板提前提交问题已修复。原始实际 UI 65/65、追加松开旅程 81/81、243 项单测和现有 GPU 回归通过；详见 [修复前后与验收](stabilization-v1/issue-5.md)。渲染质量、阴影范围及后续摄影功能的评估进入独立阶段。

Rendering 质量基线 V1：完成 22 组真实 GPU 摄影，覆盖受控地面 10/32/200、1024/4096、几何多机位/光向、画外投影与 Helmet/Lantern/Avocado 原始 PBR 资产。记录矩阵、阴影 pass GPU 时间、Scene/Shot 参数及照片；详见 [测量与最小方案](render-quality-v1/baseline.md)。此阶段未修改 Renderer。

Shot Camera 持久化已在 `feature/shot-camera-persistence` 工作树完成实现与验证：239 项单测通过，跨进程保存/加载后 PNG 差异像素为 0，原摄影 UI 回归通过。见 [格式、兼容性和验收记录](shot-camera-persistence.md)。

| 阶段 | 状态 | 记录 |
| --- | --- | --- |
| Placement V1 / V2、Ground 分离、Photography、AI API V1 | 既有基线，本轮全部回归通过 | 对应 docs 下专题报告 |
| 世界空间 Directional Light 第一轮移植 | 已提交 `48e8912`，分支 `feature/world-directional-light` | [移植报告](directional-light.md) |
| Lighting V1 操作接口 | 实现及验收完成，交付分支 `feature/lighting-v1-controls` | [接口、测试、PNG 与修改清单](lighting-v1.md) |
| Shadow Mapping V1 / Issue #2 | 基于 `1033e5e`，独立分支 `feature/shadow-mapping-v1` 完成 | [移植来源、许可证、测试及截图](shadow-mapping-v1.md) |

Lighting V1 已打通 UI → Scene、Python/JSON API → Scene → Shot PNG → v3 保存重载。
216 项单测及 Ground、Placement V1/V2、Photography、AI API、Lighting GPU 回归通过。
新增实际 UI 键盘输入和 API 完整摄影流程验证通过。

Issue #3“放士兵后放小凳子导致远裁剪过近”已在 `fix/editor-scene-clipping` 修复；224 项单测与 GPU 回归通过，实际缺失像素从 1373 降为 0。
修改、前后 PNG、裁剪深度和测试记录见 [场景裁剪报告](scene-clipping.md)。

收到明确启动指令后完成 Issue #2：世界平行光正交 ShadowMap、3×3 PCF、普通/PBR 互投影、Editor/API 开关、v3 持久化、Shot 输出、深度 PNG。
229 项单测、全部既有 GPU 回归及新增 Shadow GPU/UI 验收通过。Camera 裁剪实现未改动。不合并 main，本轮结束停止。

Shadow 摄影区域拟合 V1：同分辨率下改善大地面近景阴影；保留画外投影物，Editor Camera 维持原算法。251 单测、22 组摄影及既有 GPU 回归通过；CPU 与高分辨率 pass 耗时增加，详见 [质量、性能和边界](render-quality-v1/shadow-camera-fit.md)。

后续 Rendering 评估完成：分析成片 MSAA/SSAA、固定环境 IBL、纯色/图片/天空背景的最小方案、模块、显存与风险，见 [下一轮技术评估](render-quality-v1/next-rendering-steps.md)。以上功能均未开发。本轮分阶段交付完成，不合并 main，停止等待审查。
