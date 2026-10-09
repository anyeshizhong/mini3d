# Mini3D 开发进度

更新：2026-10-09。

| 阶段 | 状态 | 记录 |
| --- | --- | --- |
| Placement V1 / V2、Ground 分离、Photography、AI API V1 | 既有基线，本轮全部回归通过 | 对应 docs 下专题报告 |
| 世界空间 Directional Light 第一轮移植 | 已提交 `48e8912`，分支 `feature/world-directional-light` | [移植报告](directional-light.md) |
| Lighting V1 操作接口 | 实现及验收完成，交付分支 `feature/lighting-v1-controls` | [接口、测试、PNG 与修改清单](lighting-v1.md) |

Lighting V1 已打通 UI → Scene、Python/JSON API → Scene → Shot PNG → v3 保存重载。
216 项单测及 Ground、Placement V1/V2、Photography、AI API、Lighting GPU 回归通过。
新增实际 UI 键盘输入和 API 完整摄影流程验证通过。

另行诊断的“放士兵后放小凳子导致远裁剪过近”尚未修复，不属于 Lighting V1 范围。
本轮没有自动启动其他移植任务；不合并到 main。
