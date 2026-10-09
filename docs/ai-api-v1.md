# Mini3D AI API V1

分支 `feature/ai-api-v1` 基于 `feature/placement-v2` 的 `37c14d3`。这是同进程的 Python/JSON 命令接口，外部程序无需启动或操作 Editor UI。没有网络服务、自然语言解析或 AI 模型调用。

## 文件和边界

- `mini3d/api.py`：Mini3DAPI；所有 Placement 修改委托给现有 PlacementCommands，查询返回独立 dict/list、标量和稳定 ID。
- `mini3d/api_dispatch.py`：显式命令白名单、命名参数校验、结构化 JSON 成功/错误结果及原子批处理。
- `tests/test_api.py`、`tests/test_api_dispatch.py`：无窗口自动测试。
- `tests/ai_api_smoke.py`：真实桌面 OpenGL、完全不用 Editor UI 的拍照验收。

API 内部复用 Editor **状态对象**及已有 v3 保存载入方法，不调用 `editor.run`、EditorUI 或文件选择器；构造不会创建窗口或启动 Tk 进程。这样没有另建 Scene serializer、历史栈、Renderer 或 Photo 架构。所有渲染仍使用原 GLRenderer/ShotCamera/capture_png。

## API

Lighting V1 新增 `get_lighting()`、`set_lighting(mode=None, direction=None, diffuse=None, ambient=None)`，
并在 `get_scene_state()` 中增加 `lighting`。JSON dispatcher 支持两方法；光照写入禁止放入 Placement
事务。完整验证规则、返回值及摄影示例见 [Lighting V1](lighting-v1.md)。

Ground 职责分离后，`place_on_ground` 的签名、Bounds Bottom 行为、有限范围和 Commands 路径保持兼容；目标改为数学 Placement Plane。`get_scene_state()['ground']` 保留 `visible/z/size` 字段，其中 `visible=False` 表示没有隐式实体地面，新增 `placement_plane` 描述查询平面。Grid 开关不影响放置或 Capture。需要实体地面可用 `spawn('builtin:ground')`，它拥有普通 Stable ID，并支持原有变换、复制、锁定、撤销和保存载入。照片不再自动带灰色地板。

```python
from mini3d.api import Mini3DAPI
api = Mini3DAPI()  # 建场景/查询/保存无需窗口或 GL；不能在此状态下 capture
```

| 方法 | 行为 / 返回 |
| --- | --- |
| `list_entities(include_bounds=False)` / `get_entity(entity_id, include_bounds=False)` | 实例 dict，包括 stable ID、资源路径、TRS、显隐、锁与 placement metadata；可选精确几何 AABB |
| `list_groups()` / `get_group(group_id)` | group_id、name、member_ids 的快照 |
| `get_scene_state(include_bounds=False)` | Entities、Groups、选择 ID、Ground、Shot Camera 和历史计数 |
| `spawn(asset_path, name=None, position=None, rotation=None, scale=None, placement_type=None, anchor='bounds_bottom', keep_upright=None)` | 返回实例 dict，ID 在 `entity_id` 字段；不自动贴面 |
| `delete(entity_id)` / `duplicate(entity_id, name=None)` | 删除结果 / 新实例 dict，共享资源，遵守 Locked 规则 |
| `set_transform(entity_id, position=None, rotation=None, scale=None)` | 设置实例绝对 TRS |
| `transform_many(entity_ids, translation=None, rotation=None, scale=None, pivot=None)` | 复用 V2 的整体世界增量变换，默认 Selection Center，跳过 Locked；返回实际修改的实例列表 |
| `place_on_ground(entity_id, x=None, y=None, anchor=None)` | 锚点放到有限数学 Placement Plane；默认保持当前锚点 XY，重复调用不漂移，越界报错 |
| `place_at(entity_id, position, normal=(0,0,1), anchor=None, keep_upright=None)` | 将所选 anchor 对齐调用方提供的 surface 点；不是 root pivot 的绝对赋值，不做额外 raycast/碰撞 |
| `lock(entity_id)` / `unlock(entity_id)` | 返回更新后的实例 dict |
| `create_group(member_ids, name=None)` | 返回 SceneGroup dict |
| `create_rectangular_formation(source_id, rows, columns, spacing_x, spacing_y, facing=None, include_source=True)` | 返回 Formation Group dict；默认 40 人包含原士兵，Undo 保留原士兵 |
| `undo()` / `redo()` | `{"changed": true/false}` |
| `transaction(label='API placement')` | Python context manager，一次批量编辑一条 Undo，失败回滚 |
| `save_scene(path)` / `load_scene(path)` | 复用 v3 格式；保存返回 path/version，载入返回 scene state |
| `create_shot_camera(position=None, target=None, focal_mm=50, aspect='16:9', near=.01, far=1000)` | 唯一 Shot Camera；position/target 同时提供时使用显式 pose；均省略时按镜头自动框取可见实例 |
| `get_shot_camera()` | 相机参数 dict；尚未创建时返回 None |
| `set_lens(focal_mm)` / `set_aspect(aspect)` | 原有 24/35/50/85 mm 和 16:9、3:2、4:3、1:1；返回相机 dict |
| `capture(path)` | PNG 路径、格式和相机 dict；要求调用线程具有有效 OpenGL context，并在构造 API 时提供 renderer |

世界 Z 向上，实例 rotation/facing 是弧度，camera.rotation 的查询结果是正交 3×3 矩阵。没有 name-based lookup。返回数组转换为普通 list，修改返回值不改变内部场景。`include_bounds=True` 需要扫描几何，密集场景查询会更慢。

## Python 示例

```python
from mini3d.api import Mini3DAPI

api = Mini3DAPI()
with api.transaction("Spawn and ground"):
    soldier = api.spawn("model/05_roman_soldier/roman_legionnaire.glb", scale=[.06] * 3)
    api.place_on_ground(soldier["entity_id"], x=0, y=0)

group = api.create_rectangular_formation(soldier["entity_id"], 5, 8, 1.2, 1.4)
with api.transaction("Move and rotate formation"):
    api.transform_many(group["member_ids"], translation=[2, 1, 0])
    api.transform_many(group["member_ids"], rotation=[0, 0, .25])
api.save_scene("captures/api-scene.json")
print(api.get_scene_state())
```

拍照由调用方显式创建真实 context，并在销毁 context 前使用 renderer：

```python
import pygame
from mini3d.api import Mini3DAPI
from mini3d.gl_renderer import GLRenderer

pygame.init()
pygame.display.set_mode((640, 360), pygame.OPENGL | pygame.DOUBLEBUF)
renderer = GLRenderer(640, 360)
try:
    api = Mini3DAPI(renderer=renderer)
    api.load_scene("captures/api-scene.json")
    api.create_shot_camera(focal_mm=50, aspect="16:9")
    result = api.capture("captures/api-photo.png")
    print(result)
finally:
    if hasattr(renderer, "material_renderer"):
        renderer.material_renderer.close()
    pygame.quit()  # 释放调用方拥有的 context 及其余 GL 资源
```

该 SDL 窗口是渲染 context，不是 Editor UI。未声称支持无显示服务器的 headless 渲染。API 不替调用方创建、切换或销毁 GL context，renderer 应在整个 context 生命周期内复用；所有调用按单线程顺序执行。

## JSON Dispatcher

```python
from mini3d.api_dispatch import dispatch, dispatch_json

result = dispatch(api, {"command": "get_entity", "args": {"entity_id": "ent_000001"}})
text = dispatch_json(api, '{"command":"get_scene_state"}')
```

成功返回 `{"ok": true, "result": ...}`；失败返回 `{"ok": false, "error": {"type": "ValueError", "message": "..."}}`。只调用白名单方法，不使用 eval，不允许访问 `_app`、`_entity` 或其他内部成员。错误 JSON、未知方法/参数和驱动错误均返回可序列化错误结果；中断及退出异常不吞掉。

```json
{
  "command": "transaction",
  "args": {
    "label": "Place and lock",
    "commands": [
      {"command": "place_on_ground", "args": {"entity_id": "ent_000001", "x": 2, "y": 3}},
      {"command": "lock", "args": {"entity_id": "ent_000001"}}
    ]
  }
}
```

先校验批处理命令的方法和参数签名，再执行；某一步业务校验失败则整体回滚。JSON 批处理使用已有 ID，没有变量替换或临时名称引用。

## 验证结果

2026-10-08：**191 项单元测试通过**，含 14 项 API/dispatcher 测试。覆盖 ID 查询、独立 JSON 快照、Commands 委托、Ground/Anchor、锁定、资源共享、事务失败回滚、不复用 ID、Formation/整体变换、save/load、相机验证、无 context 明确拒绝 capture、dispatcher 白名单及批处理原子性。

实际运行 `tests/ai_api_smoke.py`，OpenGL 使用 Intel UHD Graphics 620：

1. 仅通过 API 创建 Roman、显式 scale=.06、place_on_ground。
2. 创建 5×8 Formation，40 个唯一 ID；Undo 留下源士兵，Redo 恢复相同组和成员。
3. 整体移动与旋转，保存 Scene；新建另一个 Mini3DAPI，重新载入并逐项对比实体和组。
4. 创建独立 50mm、16:9 Shot Camera，输出真实 **1920×1080 PNG**。
5. 通过 JSON dispatcher 查询最终 40 人 scene state，写入 `state.json`。
6. 检查 PNG 尺寸、像素内容与 GL 错误，并断言整个进程没有导入 `imgui`；成片已查看，没有 Editor UI、Gizmo 或网格。

产物：`captures/ai-api-v1/scene.json`、`state.json`、`result.json`、`formation-50mm-16x9.png`。原始模型及 captures 不在本次 Git 提交中。

```powershell
& F:/gymenv/python.exe -B -m unittest discover -s tests -p 'test_*.py'
& F:/gymenv/python.exe -B tests/ai_api_smoke.py
```

## 当前限制

- API 是同进程、单线程的薄包装，内部复用 Editor 状态类，所以运行环境仍使用现有依赖和资产 manifest；没有启动 UI，也未抽取或重构现有 serializer。
- Placement transaction 不包含文件 I/O 或 Camera 状态。活动事务内拒绝 save/load、相机编辑及 capture，避免文件或相机操作破坏回滚语义。Formation 自带事务，按 V2 规则不嵌套到另一个事务；Undo/Redo 也必须在事务结束后调用。
- Shot Camera 只有一台，重复创建覆盖；Scene v3 现在保存并恢复 Shot Camera，reload 后可直接 get_shot_camera/capture，无需重新创建。旧场景缺少该字段或值为 null 时清除已有摄影相机；非法数据在替换当前场景前拒绝。显式相机 pose 使用调用方的 near/far；自动取景由既有 OrbitController 计算裁剪范围。详见 [持久化格式与验收](shot-camera-persistence.md)。
- Ground 是有限平面；`place_at` 信任调用方给定的点，不寻找最近表面。仍无地形跟随、碰撞、多点接触、更多 Formation 或单位自动换算。
- 截图同步进行，需要桌面 OpenGL、正确线程和有效的 caller-owned renderer；没有 HTTP/WebSocket/MCP、异步队列或 headless backend。输出是本地 PNG 路径，不是 base64 图像。
- 大模型场景性能保持 V2 现状；没有增加 Instancing、阴影、物理、动画或 Renderer 优化。
