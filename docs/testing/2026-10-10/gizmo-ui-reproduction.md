# 第二轮：摄影编辑器使用旅程

使用实际 Editor/ImGui/OpenGL 循环注入 SDL 输入，39 帧。环境为 EGL、SDL offscreen、软件 OpenGL；使用仓库内 STL 方块和 builtin:ground，无外部模型。没有修改生产代码。

最终共 65 条断言，其中 39 条为逐帧 GL 错误检查；63 条通过，2 条失败对应同一个问题。不是 2 个独立缺陷。

## 确认问题：Gizmo 拖动越过面板后，Esc 无法撤销尚未松手的移动

复现：

1. 选择方块，启用 Move，按住 Gizmo 中央自由移动手柄。
2. 不松左键，在视口内右移约 60 像素，确认模型已经移动。
3. 继续按住左键，将鼠标移到左侧 Assets 面板。
4. 在松开左键之前按 Esc。

预期：取消本次拖动，恢复拖动前的位置，不新增 Undo。

实际：鼠标进入 Assets 面板时，Gizmo 已结束，事务被提前提交；Esc 无法恢复原位。记录如下：

| 帧 | 操作 | 位置 | Gizmo/事务 | Undo |
|---|---|---|---|---|
| 2 | 按下手柄 | [-0.5, -0.5, 0] | 活动 | 0 |
| 3 | 视口内移动 | [-0.5, -0.2175575997, 0] | 活动 | 0 |
| 4 | 左键保持按下，进入 Assets | [-0.5, -0.2175575997, 0] | 已结束 | 1 |
| 5 | Esc | [-0.5, -0.2175575997, 0] | 已结束 | 1 |

实际 ImGui 在帧 4/5 报告 mouse_captured=True，viewport_hovered=False。因此复现经过真实 UI 捕获判断，没有用伪造 UI 状态替代。

原因位置：`mini3d/editor.py:546–550`。UI 捕获鼠标分支直接调用 `self.gizmo.finish()`，会提交尚未松手的 Gizmo。虽然 `536–541` 提供跨面板 Esc 取消路径，但此时 `gizmo.drag` 已清除。建议使普通面板越界只暂停 Gizmo 更新，保持事务直到左键释放/Esc；模态操作和窗口失焦的结束策略应分别考虑。

对照验证：

- 相同 Gizmo 在视口内确实发生移动，然后 Esc 成功恢复位置，Undo=0（帧 34–36）。
- Surface Move 同样移到 Assets 后 Esc，成功恢复位置，Undo=0（帧 9–12）。
- Surface Move 移到 Assets 后松开，正确提交一次 Undo（帧 16–19）。

初版对照曾使用布局更新前的手柄位置，误点到 X 轴；水平拖动没有位移。这是测试夹具问题，已修正为在按下帧重新取得手柄位置。最终结果仅保留上述已确认问题，无夹具失败。

影响：摄影布景时，想在移出视口后按 Esc 放弃构图调整会失效；目前可使用 Undo 恢复，不属于文件丢失或崩溃。

## 通过的摄影旅程

- Camera View 中滚轮、中键拖动均不改变 Shot Camera 或 Editor Camera；返回 Editor View 后滚轮继续正常工作。
- Camera View 输入前后照片逐像素一致。
- Editor Grid 开/关照片逐像素一致。
- A 场景（有摄影相机、显式地面、Grid On）→旧版 B 场景（无相机、无实体、旧 ground_visible=true、Grid Off）：旧摄影相机正确清除，退出 Camera View，不凭空创建地面，Grid Off 恢复。
- 再载入 A：摄影相机参数精确恢复，显式地面与 Grid On 恢复；重新进入 Camera View 后照片与初始照片逐像素一致。
- 全程 OpenGL 无错误。

## 产物与运行

`result.json` 包含每个断言与逐帧姿态/捕获/事务记录；`ui-frame-03/04/05.png` 为缺陷过程截图；`ui-frame-34/35.png` 为视口内移动对照截图。四张 `photo-*.png` 是摄影像素对照。

```bash
PYOPENGL_PLATFORM=egl SDL_VIDEODRIVER=offscreen SDL_AUDIODRIVER=dummy python -B tests/ui_photography_journey_20261010.py
```

原始采集脚本只记录失败、退出 0。归档版本保留原检查逻辑，并在失败时退出 1；未修复版本预期有 2 条失败，修复后应有 65 条通过。结果写入 captures/second-session/ui-study/。


> GitHub 归档说明：本文件保留当时测试记录；仓库中复现入口、证据路径和重新生成方法以 [README](README.md) 为准。历史压缩包未提交，场景及基础资产可运行脚本重新生成。
