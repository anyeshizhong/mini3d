# Codex 连接正在运行的 mini3D Editor

## 现有实现审查

核实 2026-10-11 远端 `main` 为 `2de85ed7e30c63ea86be4f8ec8a201a8b356621a`。
`Mini3DAPI(renderer, editor=app)` 已支持绑定现有 Editor；Runtime 原本就这样创建 `app.api`，共享 Scene、PlacementCommands 和 ShotCamera。
但是 `api_dispatch.dispatch/dispatch_json` 原本只有同进程调用，没有 HTTP、Socket、命名管道、MCP 或主线程请求队列。
`Mini3DAPI()` 无参数会创建独立的无窗口 Editor 状态，不会连接用户当前实例。

本次只补传输和 Runtime 调度；原有 Transform、Lighting、Camera、Capture、保存载入、Undo/Redo、transaction 全部继续由原白名单 Dispatcher 执行。
原 `get_scene_state()` 的字段及持久化语义保持兼容。新增 `get_editor_camera()` 查询导航相机及 viewport/camera_view，原 `get_shot_camera()` 查询摄影机。
新增 `screenshot(path)` 读取当前 Editor 窗口（包含 UI）的已绘制帧；原 `capture(path)` 继续导出干净的 Shot Camera 照片，不改变其摄影行为。

窗口最小化／遮挡时默认窗口缓冲区可能无法提供有效截图，现已改为读取 Runtime 自有的完整 Editor 帧 FBO，窗口显示与截图使用同一帧。修复和 GitHub 新 UI 移植见 [验收记录](editor-screenshot-fix.md)。

## 从 VS Code 中连接

更新前已启动的旧编辑器需要保存场景并重启一次；无法让未加载 IPC 代码的旧进程自动支持通信。
正常启动 `python -B editor_app.py` 默认启用 IPC，`--no-ipc` 可关闭。无需启动第二个编辑器。
从项目根目录调用客户端。客户端仅用标准库，可以使用 VS Code 自己的 Python；运行编辑器和 GPU 回归时需使用装有项目依赖的 Python 环境。

```powershell
python -B -m mini3d.ipc_client --list
'{"command":"get_scene_state"}' | python -B -m mini3d.ipc_client
'{"command":"list_entities"}' | python -B -m mini3d.ipc_client
'{"command":"get_editor_camera"}' | python -B -m mini3d.ipc_client
'{"command":"get_shot_camera"}' | python -B -m mini3d.ipc_client
'{"command":"get_lighting"}' | python -B -m mini3d.ipc_client
'{"command":"screenshot","args":{"path":"captures/current-editor.png"}}' | python -B -m mini3d.ipc_client
```

有多个实例时默认连接报错。使用 `--instance <完整 instance_id>` 明确选中目标窗口。不会依据最近的场景文件或启动第二个 Editor 猜测当前实例。
`--list` 输出 instance ID、PID、标题、工程路径及端口，不输出访问 token。
需要在多个调用之间固定同一个实例时，使用显式 `--instance`，或保留同一个 `EditorClient`：

```python
from mini3d.ipc_client import connect
client = connect(instance_id="从 --list 获取的完整实例 ID")
state = client.call("get_scene_state")
assert state["ok"], state
soldier_id = state["result"]["primary_selection_id"]
latest = client.call("get_entity", entity_id=soldier_id)
assert latest["ok"], latest
position = latest["result"]["position"]
position[0] += .5
print(client.call("set_transform", entity_id=soldier_id, position=position))
print(client.call("screenshot", path="captures/api-moved.png"))
```

CLI 同时支持 `--file command.json`，读取 UTF-8（可带 BOM）的原 Dispatcher 命令。成功退出 0，错误退出 1。
客户端不会导入 Editor、pygame、OpenGL，不会创建场景或 GL context。

## 最小本地 IPC 与主线程安全

- 标准库 HTTP，绑定 `127.0.0.1` 的随机端口，仅 `POST /dispatch`；body 完全沿用 `{"command":...,"args":...}`。
- 每次启动生成新 instance ID 和随机 Bearer token；发现文件在当前用户临时目录 `mini3d-ipc/<instance_id>.json`。客户端读取该目录，主线程只读探测排除崩溃留下的失效记录；正常退出删除自己的记录。
- 不输出 token，不接受浏览器 Origin 请求，无 CORS、远程绑定或任意 Python 执行。授权本地客户端拥有原 AI API 的文件保存/载入能力；不是给不受信任进程使用的沙箱。
- Windows 使用用户临时目录继承的访问权限；Unix 创建发现文件时使用 `0600`。不会写入项目场景、Git 或用户配置。
- HTTP 工作线程只解析 JSON/校验访问 token/入队等待，不读取 Scene，不执行 API 或 GL。
- Runtime 在 UI 与鼠标事件处理后、Scene 更新渲染前，主线程处理普通请求；窗口 screenshot 单独在 ImGui 绘制后、swap 前处理，因此前一条已完成 Transform 的结果能出现在截图里。
- 队列每阶段最多 32 条，每帧每阶段最多执行 8 条；单条昂贵的 Capture/导入仍同步执行，会按原 API 成本阻塞该帧，不宣称无限实时性能。
- 用户 Gizmo、Surface Move、Inspector 编辑事务未完成时允许只读查询，所有外部写入返回 `EditorBusy`；不会结束用户手势或合并其撤销条目。外部 placement 批量仍使用原 Commands transaction。
- 排队期限默认 10 秒；尚未开始执行的超时请求取消，不会稍后突然修改场景。已开始的调用不能安全中断，超时报 `RequestTimeout` 且 `outcome_unknown=true`；客户端不能自动重试写入，应读取状态确认结果。退出返回 `EditorClosed`，满队列返回 `QueueFull`。
- UI、保存载入、摄影及 API 共用原 Scene/Commands/Renderer；不增加第二套 history、serializer、摄影管线或渲染 context。

## 验收

### 用户亲手移动的验收入口

在**当前编辑器**选中士兵。VS Code 终端执行（如果多个实例，加 `--instance`）：

```powershell
python -B tools/accept_live_editor.py --output captures/my-live-acceptance
```

脚本打印实例/PID/实体 ID 和初始坐标。用户在 Editor 用 Gizmo 或 Inspector 手动移动士兵，松开鼠标提交。
脚本读取同一实体最新坐标，随后通过已有 `set_transform` 将 X 加 0.5；编辑器同步显示。
输出 `before.png`、`manual.png`、`api-moved.png`、`results.json`，保留 API 移动后的编辑器画面供用户检查。
默认等候 180 秒；没有观察到手动移动时不会发出写操作。该入口只连接已有实例。

### 已执行的自动联调

```powershell
python -B -m unittest discover -s tests -p 'test_*.py'
python -B tests/live_editor_ipc_smoke.py --output captures/my-new-ipc-smoke
```

真实士兵资产、真实 SDL/ImGui/OpenGL Editor 子进程和另一个客户端进程。该自动测试专门启动一个测试 Editor，使用注入的 SDL 鼠标事件走原 `Editor.handle_event` 和 Gizmo；不是声称用户已亲手完成移动。
2026-10-11 实测结果：287 项单测通过；跨进程 GPU 联调通过。原 `editor_smoke.py`、`editor_integration_smoke.py`、`unified_api_ui_smoke.py` 也通过，覆盖 UI 输入、Inspector、Gizmo、相机、窗口缩放及摄影回归。
士兵由 `[0, 0, 0.10415195703506464]` 经鼠标事件移动到
`[0.2105961946850765, 0.1864742845294809, 0.16352971630334134]`，客户端读取完全相同坐标，
API 再移动到 `[0.9605961946850765, 0.4364742845294809, 0.16352971630334134]`。
视口共有 220791 个颜色通道发生变化；共享 Undo/Redo、Lighting、Camera、4x MSAA、Capture、场景/摄影机保存恢复均通过。
最终证据目录：`captures/live-ipc-20261011-final/`。自动化不能替代上方用户亲手验收。
