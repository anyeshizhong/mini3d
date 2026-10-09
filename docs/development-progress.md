# Mini3D 开发进度

更新：2026-10-09。

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
