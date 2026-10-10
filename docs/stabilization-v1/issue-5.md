# Issue #5 修复验收 — 2026-10-10

修复分支：`fix/gizmo-panel-drag-v1`，直接基于摄影审计提交 `54d19e775dd88e61c76e0e2cbe4c3b54fedb2433`；其祖先包含 Shot Camera 功能提交 `7cb7719868b4fbdfe16ff89b4e2b6db092b44747`。根工作区和已有摄影工作树的未提交资产、manifest、脚本均保留；开发在独立 worktree 中进行。

## 修复前后

先在未修改的测试基线执行原始实际 SDL/ImGui/OpenGL 复现脚本，退出 1，65 项检查中 63 通过、2 失败。失败恰好是跨 Assets 后 Esc 的位置恢复和 Undo 检查。

| 事件 | 修复前 | 修复后 |
| --- | --- | --- |
| 开始拖动 | `[-0.5,-0.5,0]`，事务活动，Undo 0 | 相同 |
| 视口内移动 | `[-0.5,-0.20401240470448034,0]`，事务活动，Undo 0 | 相同 |
| 保持左键进入 Assets | 提前结束事务，Undo 1 | 暂停几何更新，事务活动，Undo 0 |
| 在 Assets 按 Esc | 仍为移动后位置，Undo 1 | 精确恢复 `[-0.5,-0.5,0]`，事务结束，Undo 0 |

原始检查和逐帧状态：[修复前](ui-before.json)、[修复后](ui-after.json)。实际 GPU UI：[前](gizmo-before.png)、[后](gizmo-after.png)。Inspector 在 UI 绘制后才接收本帧事件，因此 Esc 帧的输入框文本有一帧延迟；位置/事务以逐帧状态和最终渲染为准。

## 修改范围与策略

`Editor.handle_event()` 区分普通面板鼠标捕获和模态窗口。普通 UI 捕获只暂停几何更新，Gizmo 与 Surface Move 均保留原有事务，直到左键释放或 Esc。捕获区域中的下一次 motion 若报告左键已松开，也能结束漏收 release 的手势。

释放事件仍在 UI 捕获前处理，重复 release 不重复提交。Esc 保留既有跨 UI 捕获的手势取消优先级；普通快捷键仍受输入框 keyboard capture 阻挡。Camera View 隔离、模态窗口及窗口失焦的既有提交策略保留。没有重构手势、Gizmo 或事务系统。

生产修改只有 `mini3d/editor.py`。测试修改为 `tests/test_editor.py`、`tests/ui_photography_journey_20261010.py`，新增回归运行器 `tests/stabilization_regressions.py`。

## 结果

环境：Windows，Python 3.8.20，pygame 2.6.1，Intel UHD Graphics 620，OpenGL 4.6.0 / driver 27.20.100.8682。

- 原始实际 UI **65/65** 通过，保留原有检查内容。
- 追加跨面板松开旅程后 **81/81** 通过；包括事务保留、几何暂停、只提交一次、重复松开、Undo/Redo 恢复。新增项不是另一个独立的 81 项测试集。[记录](ui-release.json)
- **243 项单元测试全部通过，无跳过**，在原 239 项之上增加 4 项输入路由测试。[日志](unit.log)
- Ground、Placement V1/V2、Photography、AI API、Lighting/API/UI、Scene Clipping、Shadow/UI、Shot Camera 跨进程持久化实际 GPU 回归全部通过。[运行记录](regressions/regressions.json)
- Scene 保存、重开、Editor 导航后的 Shot PNG 逐像素一致；实际 UI 中 Surface Move 跨面板取消/松开、Camera View 输入隔离、Grid 和 A→旧 B→A 继续通过。

首次 Shadow 回归因新输出目录缺少 `baseline-off.png`、`baseline-studio.png` 而退出 1，尚未执行视觉断言。补齐隔离的 `1033e5e` checkout 并实际生成基线后，重跑 Shadow 回归退出 0；原失败日志保留，重跑结果另记，未用当前 Renderer 伪造旧基线。[初始日志](regressions/shadow.log)、[基线生成](regressions/shadow-baseline.log)、[重跑](regressions/shadow-retry.log)

## 复现

```powershell
F:/gymenv/python.exe -B tests/ui_photography_journey_20261010.py --output captures/stabilization-v1/ui-original
F:/gymenv/python.exe -B tests/ui_photography_journey_20261010.py --panel-release --output captures/stabilization-v1/ui-release
F:/gymenv/python.exe -B -m unittest discover -s tests
F:/gymenv/python.exe -B tests/stabilization_regressions.py docs/stabilization-v1/regressions
```

完整回归运行器要求原始可选本地模型可用，以及 `captures/shadow-baseline` 指向独立 `1033e5e` checkout，供旧 Shadow 脚本采集关闭阴影/Studio 对照。Linux headless 的原脚本运行方式见摄影审计 README；本轮使用 Windows 原生 WGL，没有生成式截图。

本阶段没有新发现的生产兼容性问题。渲染画质将在后续独立阶段测量；本报告不把功能回归通过解释成画质问题全部解决。
