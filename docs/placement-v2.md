# Placement V2 实现与验收

基于 `feature/placement-system` 的 `75c3998` 创建 `feature/placement-v2`。开始前运行 V1 全部 **128 项单元测试和 7 个 smoke 脚本，全部通过**，然后建立起始 checkpoint `f7d86ea`。实现及验证日期：2026-10-07 至 2026-10-08。

## 修改文件

| 文件 | 职责 |
| --- | --- |
| `mini3d/surface_drag.py`（新增） | UI 无关的 SurfaceDrag 手势，复用 V1 表面 raycast 与 placement 命令 |
| `mini3d/formation.py`（新增） | 平面矩形阵型生成，验证参数、共享实例资源、创建分组 |
| `mini3d/commands.py` | 选择、Multi Transform、Group/Ungroup、组重命名；历史包含成员与选择状态 |
| `mini3d/scene.py` | SceneGroup、稳定 Group ID、多选状态及无效引用清理 |
| `mini3d/editor.py` | 输入仲裁、命令接线、整体编辑、Scene v3 保存载入 |
| `mini3d/editor_tools.py` | Selection Center 和多选 World Gizmo，单选保留 World/Local |
| `mini3d/editor_ui.py` | Surface Move、Shift 多选、分组管理、最小 Formation 输入 |
| `tests/test_placement_v2_commands.py`、`test_surface_drag.py`、`test_multi_gizmo.py`、`test_formation.py`、`test_placement_v2_editor.py`（新增） | 核心、输入、事务、分组、阵型和持久化测试 |
| `tests/placement_v2_smoke.py`、`placement_v2_performance.py`（新增） | 实际窗口验收和性能观察 |
| `tests/test_placement_editor.py` | 保存格式断言更新为 v3，保留原 V1 测试 |
| `readme.md`、本文 | 使用方法、行为约定、实际结果与限制 |

本阶段没有修改 Photo 实现、Renderer 源码或架构，没有引入新依赖、模型、UI 框架或 V3 功能。

## Command API

既有 V1 命令保留，新增：

```python
commands.set_selection(ids, primary_id=None, group_id=None)
commands.select_group(group_id)
commands.transform_many(ids, translation=None, rotation=None, scale=None,
                        pivot=None, initial=None)
commands.create_group(member_ids, name=None)
commands.rename_group(group_id, name)
commands.ungroup(group_id)
commands.create_rectangular_formation(source_id, rows, columns,
    spacing_x, spacing_y, facing=None, include_source=True)
drag = commands.begin_surface_drag(entity_id)
drag.update(camera, screen_pos, viewport_rect)
drag.finish()             # Mouse Up
# drag.finish(cancel=True)  # Esc
```

所有接口不依赖 Editor 或 ImGui。`transform_many` 接收世界位移、XYZ 欧拉弧度的旋转增量、正值缩放因子；默认 pivot 为可编辑成员位置均值。`initial` 是以 ID 为键、包含 `position/rotation/scale` 的起始快照，供 Gizmo 每帧从鼠标按下状态计算，避免累积误差。Locked 成员跳过，不使整次操作失败。

SurfaceDrag 开启一个 `Surface Drag` transaction，复用 `raycast_surface(..., exclude=entity, fallback=None)` 和 `place_on_surface`。未命中时保留最后有效位置，不跳到 Camera Target；隐藏 Ground 后也遵守这一规则。锁定对象仍是表面，人物继续保持 Z-up，Pivot/Bounds Bottom 均沿用 V1。鼠标经过 UI 时暂停更新，松开提交，Esc 即使在面板上也会取消；窗口失焦结束手势。

## Multi Selection 与 Group 数据结构

Scene 保存 `selected_ids: list[str]`、`primary_selection_id`、`selected_group_id`。`Scene/Commands.selected_entities` 和 `primary_selection` 按 ID 解析，`editable_selection` 排除 Locked；Editor 的 `selection` 是 primary 的兼容只读别名。名字不是选择键。

普通左键替换选择，Shift+左键切换成员，空白清空；Outliner 支持相同的 Shift 操作，并允许管理 Locked 实例。只给 primary 绘制轮廓，其余由 Outliner 高亮及选择数量表示。多选 Gizmo 使用 World，中心为可编辑成员根位置均值。显式选择的隐藏组成员仍参与整体变换。单选继续使用原 World/Local 行为。

```python
SceneGroup(group_id="grp_000001", name="Legion_Formation_001",
           member_ids=["ent_000001", "ent_000002"])
```

`Scene.groups` 是平面的 SceneGroup 列表；`find_group_by_id` 按稳定组 ID 查找。Group 只保存 Entity ID 集合，不改 glTF parent/children；不允许空成员、重复成员、无效 ID 或嵌套 Group。组名可以在 Inspector 输入并按 Enter 提交。Ungroup 只删除组定义；删除实体时从各组移除其 ID，空组移除，Undo 恢复这些关系。允许多个平面组引用同一实例，没有嵌套关系。

## Formation 算法与操作

选中一个可复制、未锁定实例，在 Inspector 设置 Rows、Columns、Spacing X/Y，点击 Create Formation。默认 5×8、间距 1.2/1.4，长度单位为引擎原始单位。算法为：

```text
origin = source.position
yaw = facing（指定时）或 source.rotation.z
position[row, col] = origin + Rz(yaw) × [col * spacing_x, row * spacing_y, 0]
```

这是以源实例为第一行第一列的矩形，不是以源实例居中的矩形；阵型局部 XY 随 yaw 旋转。保留源的 scale、rotation、placement 类型、anchor 和 keep_upright，显式 facing 只改变 yaw。复制实例获得独立 TRS 数组和新 ID，共享 Mesh/Material/Texture 及已有 GPU 缓存。

按用户确认，默认 `include_source=True`：**40 人包括原士兵，新增 39 个实例；Undo 后保留操作前的原士兵**。`include_source=False` 创建 40 个全新副本，源实例不进组，Undo 删除这 40 个副本。命令返回自动创建并选中的 `Legion_Formation_###` SceneGroup。

模型不自动换算单位。Roman 原始高度约 25.96，直接用 1.2 间距会重叠。实际验收显式把士兵实例 scale 设为 `[.06, .06, .06]`，重新贴地后再生成阵型；没有修改原始 Mesh。需要原始尺度时应相应增大间距。

## Undo/Redo 与 Save/Load

Surface Drag、一次 Multi Gizmo/Inspector 编辑、Group、Ungroup、Formation 各形成一次操作记录。选择本身不单独入历史，事务前后的选择、primary、组 ID 与成员会随操作恢复。历史不复制 Mesh/纹理/GPU 数据；Entity/Group ID 计数器在 Undo、删除和失败回滚后不倒退。连续 100 次 SurfaceDrag 更新验证只有一条 Undo；Esc 恢复手势开始前状态。

Scene JSON 升级到 **version 3**，在原 objects/相机/显示设置之外增加：

```json
{
  "groups": [{"group_id": "grp_000001", "name": "Formation", "member_ids": ["ent_000001"]}],
  "next_group_id": 2,
  "selected_ids": ["ent_000001"],
  "primary_selection_id": "ent_000001",
  "selected_group_id": "grp_000001"
}
```

实体 ID、组 ID、成员、TRS、Locked、摆放元数据及两类 ID 计数器均保存。v1/v2 无 Groups 的文档正常加载为空组；原来没有 ID 的 v1 分配 ID。先在临时 Scene 验证全部数据，再替换当前场景，坏组引用或非法选择不会破坏当前状态。载入成功清空历史；不会把历史或模型二进制写入 JSON。

## 自动测试与实际 5×8 验收

最终自动测试 **177 项全部通过**。覆盖 100 次表面拖动、一条 Undo、Esc、无命中、自身排除、Locked 表面、多选与名字无关、整体 Move/Rotate/Scale、隐藏与锁定成员、分组不改变模型层级、40 人唯一 ID 与共享资源、事务回滚、Undo/Redo、向后兼容和原子加载。

既有 7 个真实窗口 smoke 脚本也全部通过：Editor 基础、GLB 完整接线、Photo、Tk 文件选择器、STL、三个旧示例、Placement V1。Photo 仍验证四种镜头/画幅、六张 PNG、干净预览一致及相机独立。

`tests/placement_v2_smoke.py` 在实际可见 Editor 窗口中，通过 SDL 鼠标/键盘事件和真实 ImGui 控件完成 171 帧流程；模型加载、FBO、材质与 Gizmo 均使用原实现：

1. Roman 从 Assets 拖入 Ground，显式调整测试实例尺寸，Surface Move 连续拖动，再 Undo/Redo，位置准确恢复。
2. Box 连续复制三次，Outliner Shift 多选四个对象，实际 Gizmo 整体移动、旋转，Group 后保存载入，成员 ID 与位置保持。
3. 拖入现有 Bottle；场景同时保留锁定 Side Table。选择 Roman，通过 Formation 控件生成 **5×8=40 人**，断言方向、间距、唯一 ID、独立 TRS 与共享 Mesh/Material/Texture。
4. Ctrl+Z 一次恢复原士兵，Ctrl+Y 一次恢复原阵型 ID/组/位置；再对整个 40 人阵型实际拖动 Move、Rotate。
5. Orbit/Pan/Zoom 正常响应，最终保存并载入，组与全部位置不变，GL 无错误。最终场景含 40 士兵及 6 个辅助实例。

本地产物在 `captures/placement-v2-validation/`：`placement-v2-editor.png`、`surface-drag.png`、`multi-group.png`、`placement-v2-scene.json`、`placement-v2-result.json`、`performance.json`。这些继续按 captures 规则忽略，不上传模型资源。

```powershell
& F:/gymenv/python.exe -B -m unittest discover -s tests -p 'test_*.py'
& F:/gymenv/python.exe -B tests/placement_v2_smoke.py captures/placement-v2-validation
& F:/gymenv/python.exe -B tests/placement_v2_performance.py captures/placement-v2-validation/performance.json
```

## 1 / 40 / 100 人性能观察

实际 OpenGL context 报告 **Intel UHD Graphics 620，OpenGL 4.6 / 27.20.100.8682**，Python 3.8、Pygame 2.6.1、1440×900 Editor。机器也安装 MX130，但本次测量 context 使用 Intel。每档 3 帧预热、8 帧采样，同一个 GL context；计时含同步 GPU 完成。Picking 为 5 次精确三角形测试，单次 Gizmo 数据是整个选择的一次 update。

| Roman 数量 | 帧中位耗时 | 场景渲染中位耗时 | Picking 中位耗时 | Gizmo update | 阵型创建耗时 |
| --- | --- | --- | --- | --- | --- |
| 1 | 13.53 ms | 5.47 ms | 47.54 ms | 0.54 ms | — |
| 40 | 136.71 ms | 109.84 ms | 41.98 ms | 19.56 ms | 781 ms |
| 100 | 367.69 ms | 298.99 ms | 83.67 ms | 57.95 ms | 4926 ms |

帧耗时包含 UI、primary 描边和 GPU finish，不含 swap/vsync/60 FPS clock 等待，因此不是直接测得的显示 FPS。此前一次同机测量为 13.22 / 145.18 / 379.74 ms，创建 100 人约 5.52 秒，体现测量波动。五条 Picking 射线的命中数量不同，不能把这些数值当作严格同一查询的扩展性基准。

三档始终为 **7 个 mesh cache（6 Roman + Ground）、2 个 texture cache**；从 1 到 40、100，新增 buffer/texture 上传均为 **0**。Gizmo 在三档都完成更新并成功 Undo，窗口循环没有崩溃。40/100 人明显卡顿，100 人创建会同步阻塞约 5 秒；没有把这种低帧率描述为流畅。按要求仅测量和记录，没有做 Renderer 或历史栈性能优化。

## 已知问题与 V3 建议

- Surface Move 只支持单个实例；多选、Group 用整体 Gizmo，不做自动地形跟随。AABB Bottom 仍是单点锚定，不是脚骨骼/多点接触或碰撞求解。
- 非均匀世界缩放维持 TRS 近似，不产生 shear；多选 Local 没有单独语义，统一 World。Inspector 显示 primary，变换增量应用于所有可编辑成员。
- 大模型重复绘制昂贵，40/100 人低帧率；精确 Picking 和同步 Formation 创建也有停顿。命令原子快照及逐次 Scene.update 可能增加批量成本，需后续 profile，当前不优化。
- 历史在内存，无容量上限、不跨 load 保存、事务不嵌套。Group 是平面 ID 集合，可重叠，不含独立 TRS、父子组或复杂成员编辑器。
- 模型单位手动处理，Formation 仅平面矩形，不避碰、不贴起伏地形；只绘制 primary 的选中轮廓。资产 JSON 仍引用外部模型，换机器需要相应文件。
- Photo 原有 Shot Camera 不进入 Scene 保存的限制保持不变。此次没有下载或上传 01–05/07 模型，也没有改用户的 `3.py`、`.vscode/` 或既有 pycache 改动。

V3 建议先分析真实绘制/批量命令/Picking 的耗时，再分别评估显式单位预设、低面数显示代理或 LOD、历史容量策略及组成员管理。是否开展实例化绘制、更多阵型或 AI API 应另立范围；本次均未实现，也没有增加灯光、动画、物理等系统。
