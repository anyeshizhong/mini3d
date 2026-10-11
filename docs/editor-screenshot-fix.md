# IPC 截图修复与新 UI 移植（2026-10-11）

## 故障与复现

用户当前实例的 Scene API 可读写，但 `screenshot()` 连续返回成功并输出近乎全黑的 PNG，无法检查真实画面。
原 Runtime 在 ImGui 绘制后直接 `glReadPixels` 读取默认窗口帧缓冲区，没有独立的完整编辑器帧副本。

已在同一台机器用真实 OpenGL 复现：1440×900 窗口正常显示时有 3,866,968 个非零颜色通道；通过 SDL 最小化窗口后，原截图只剩 3 个非零通道，几乎整张全黑。
这证明旧截图路径在最小化状态不可靠；未据此断言用户当时一定最小化了窗口。
默认帧缓冲区的像素归属由窗口系统控制，而 FBO 的像素由 OpenGL 拥有，参见 [Khronos pixel ownership](https://wikis.khronos.org/opengl/Per-Sample_Processing/Pixel_ownership_test)。

## 修复

- 复用原 `RenderTarget`，增加一个完整 Editor 帧的离屏目标。UI 和已有 Scene viewport 合成到此 FBO，然后将同一帧 blit 到窗口。
- `screenshot()` 显式选择该 FBO 的 `GL_COLOR_ATTACHMENT0` 读取，恢复调用前的 read framebuffer/read buffer；不再依赖默认窗口缓冲区。
- 仍由原编辑器主线程、原 GL context、原 GLRenderer 执行；没有第二个 Editor 或 Scene，没有重复渲染场景。
- 正常窗口、最小化窗口、缩放后的窗口都读取当前生成的编辑器帧；未完成首帧及完全黑的读回会明确返回错误。
- 原 `--screenshot` 复用同一读取函数。干净 Shot Camera Capture 管线保持原有实现。
- 代价：多一个随窗口尺寸变化的 RGBA8/depth-stencil 目标以及一次全窗口 GPU blit；只在请求截图时进行 CPU 读回和 PNG 写入。

修复前证据：`captures/screenshot-probe-before/`；修复后同条件截图：`captures/screenshot-probe-after/`。
修复后最小化时仍有 3,866,968 个非零颜色通道，与正常显示时一致。

## GitHub 新 UI

移植自 `origin/feature/editor-ux-workspaces-20261011`，截至 `e611a195b835456b5d54b3faa766aa8263f32a19`：

- `b9cb480`：Arrange / Lighting / Shot 工作区。
- `5657944`：直接添加 Ground Mesh；Formation 默认折叠，优先显示实体 Transform。
- `87edf5c`：较窄视口的工具布局、Scene 搜索。
- `b8bb0d0`：设计和使用验收说明。
- `e611a19`：工作区切换单测。

仅移植 upstream 改动的 `mini3d/editor_ui.py`、`docs/editor-ui-workspaces.md`、`tests/test_editor_ui_workspaces.py`。
移植前工作区改动备份：`captures/ui-port-20261011/before-port.zip`；原始差异：`upstream-ui.patch`。
保留原作者 UI 行为和已有 IPC；没有替换 API、历史栈、serializer 或摄影实现。

## 验证

292 项单测通过。原 `editor_smoke.py`、`editor_integration_smoke.py`、`unified_api_ui_smoke.py` 均通过。
跨进程士兵 Gizmo 移动／实时读取／API 移动／Undo/Redo／Lighting／Shot／MSAA／保存恢复通过，证据：`captures/live-ipc-ui-screenshot-final/`。

新增真实 GPU/IPC 回归：

```powershell
python -B tests/editor_screenshot_smoke.py captures/my-new-screenshot-run
```

覆盖正常与最小化 Arrange、最小化 Lighting/Shot、900×700 缩放、读取时另一个 FBO 已绑定、GL read state 恢复，以及干净 Capture 之后的编辑器截图。
已执行结果：`captures/editor-screenshot-regression-01/results.json`。
已目视确认截图包含新 UI 与当前 Scene。用户亲手检查新 UI 的可用性仍需实际操作，这些自动测试不代表该人工验收已完成。

截图修复当时尚未处理 Editor View/Camera View 差异与 40 士兵卡顿。后续改进和剩余限制见[画面与性能改进](editor-quality-improvements.md)。文中 captures 目录是本地验证输出，不随源码提交；对应测试脚本可重新生成证据。
