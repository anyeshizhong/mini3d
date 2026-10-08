# Default Ground 职责分离与验收

2026-10-08，分支 `feature/ai-api-v1`。本次替代 `bd41b2b` 的默认 Ground 深度偏移修补；没有新增摄影效果、ECS、reversed-Z、无限网格 shader 或重写 Renderer。

## 调用链审计与架构变化

| 职责 | 修复前 | 修复后 |
| --- | --- | --- |
| 创建 | `Editor.__init__ → create_ground` 自动生成边长 2000 的实体 | `Scene` 只初始化数学 `PlacementPlane`；没有默认 Ground Mesh |
| 场景渲染 | `Scene.get_flat_render_list` 隐式追加 Ground | 只遍历 `root_entities`，旧 `scene.ground` 槽不参与遍历 |
| 深度 | Ground 用普通材质写深度；后加 Polygon Offset 仍在近景失败 | 移除 Ground 特殊偏移分支；没有默认地面像素或深度写入 |
| 网格 | 网格混在 render 内，曾有 Z 偏移并写深度 | `GLRenderer.render_editor_grid` 独立有限 GL_LINES pass；读取场景深度、`glDepthMask(False)`，恢复调用方状态，无 Z 偏移 |
| 选择 | 实体 picking 排除 Locked 和特殊 ground ID | `pick_entity` 只查真实场景实体，排除 Locked；数学平面没有可选 Entity |
| 放置 | 场景 Mesh → 默认 Ground Mesh → fallback | 场景 Mesh（包含 Locked）→ 数学平面射线交点 → 调用方 fallback |
| 存档 | `ground_visible` 控制隐式实体 | v1/v2/v3 均可加载；忽略旧 helper 标记，不生成实体；v3 新增可选 `placement_plane` 设置 |
| 真实地面 | 默认 helper 不能普通编辑 | `Add → Ground Mesh` 或 API `spawn('builtin:ground')` 显式创建 10×10 地面，普通 Stable ID、命令历史、保存载入和渲染 |

数学平面默认 Z=0，保留原 AI API 的有限边长 2000、越界报错语义。它没有 Mesh、材质、显隐或 GPU 资源；Grid 显隐不影响放置。射线平行、交点在背后、越界或平面 disabled 时，才进入最后的 fallback。有效真实 Mesh 交点优先，即便它位于 Z=0 以下。Surface Drag 没有有效命中时保持最后有效位置。

显式 Ground 使用已有 AssetCache 和 `PlacementCommands.spawn`，序列化资源标识为 `builtin:ground`。没有绕过命令写 transform 或 root 列表；实体可选中、变换、锁定、复制、撤销和删除。用户导入的地面模型也仍是正常几何。

`get_scene_state()['ground']` 保留 `visible/z/size` 键，其中 `visible=False` 表示默认无实体地面；新增 `placement_plane` 字典。`place_on_ground` 的签名、锚点算法和 Commands 路径不变。旧场景中显式保存的普通地面资产保留，只忽略隐式 helper 的 `ground_visible`。文件格式仍为 v3，未增加不相关的相机存档功能。

## 实际图像与深度验证

使用本机 Intel UHD Graphics 620、真实 OpenGL/FBO；Rome River Side 原始比例和 100 倍比例分别测试。固定相机数据完整写入 `result.json`；每组含两个远景、两个近景。

对每个姿态生成：

1. `reference`：仅模型的场景，不含 helper 或网格。
2. `before`：在测试内重建旧版巨大 Ground + Polygon Offset(1,1)，相机、模型和 Renderer 其余条件相同。
3. `after`：新的真实 Editor Scene，关闭 Grid。
4. `grid-on`：相同 Scene，打开 Grid。

断言不是“未报错”或“画面非空”：**after RGB 和 depth 必须与 reference 逐像素相同；grid-on 的 depth 必须与 after 完全相同。** 远景还要求 Grid 确实产生可见线条；近景网格可以被道路等真实几何正常挡住。

| 原始比例姿态 | 旧方案与参考不同的模型像素 | 新方案与参考不同的模型像素 | Grid 引起的深度变化像素 |
| --- | ---: | ---: | ---: |
| far-river | 0 | 0 | 0 |
| far-reverse | 0 | 0 | 0 |
| near-road | **51,731** | **0** | **0** |
| near-temples | 0 | 0 | 0 |

旧方案是已经加过偏移的版本，因此远景显示正常而近景仍失败。原始比例 near-road 的 camera position 为 `[0.74868634,-0.00748045,0.34766265]`，near≈0.0000777431，far≈4.31120661。本次保持 Camera 算法和参数不变。100 倍比例的四个姿态也全部与模型参考吻合；这些姿态未复现旧方案的遮挡，报告未将它们计为“修复的像素”。

实际启动 Editor，保存近景 Grid Off/On 截图并查看；道路、桥、河面、建筑表面显示完整。还实际绘制了显式 Ground Mesh，并断言它确实改变图像，证明没有禁止用户地面模型。

## 放置、锁定与脚底

从实际 top-view 图像选择一处道路和神庙两级台阶，锁定整个 Rome 环境后执行真实 triangle raycast。普通 picking 无法选中环境，placement query 仍命中它；不是回落到 Z=0。使用现有 Roman Legionnaire，原始环境比例下士兵实例 scale=0.0006，100 倍环境下为 0.06。

| 命中表面 | 命中世界 Z | Bounds Bottom 世界 Z |
| --- | ---: | ---: |
| road | 0.026845396498 | 0.026845396498 |
| step-low | 0.106046194445 | 0.106046194445 |
| step-high | 0.118720490182 | 0.118720490182 |

旋转输入含 pitch/roll；重新放置后为 `[0,0,0.7]`，保持直立。完整层级包围盒的底部中心对齐命中点，实例局部原点没有被误当成脚底，原 Mesh 数据不变。另有嵌套、偏移局部原点、非均匀缩放的自动测试。

## 测试记录

- **197 项自动测试通过**，其中新增 6 项职责分离回归：无隐式几何、Grid/查询独立、锁定/解锁、Mesh 优先、平行/背后/越界/fallback、偏移原点脚底、显式 Ground 命令与存档、v1/v2/v3 旧场景标记兼容。
- `ground_separation_smoke.py`：上述近/远景逐像素比较、Grid 深度不变及状态恢复、真实道路/台阶、锁定后放置、真实资产旧 v3 reload、显式地面实际渲染、实际 Editor 窗口。
- 摄影三张对照（Grid On / Off / mesh-only reference）的 PNG 像素完全相同。默认地面与网格均不进入成片。
- `photo_smoke.py` 通过：真实 UI 按钮、4 镜头/画幅、6 PNG、预览与成片一致、构图线排除、Editor/Shot Camera 独立。
- `placement_smoke.py` 通过：实际 UI 拖入 Roman、Ground Plane fallback、Side Table 贴面、Gizmo、Inspector、锁定、复制、Undo/Redo、保存载入。
- `ai_api_smoke.py` 通过：无 Editor UI 的 40 人 Formation → 移动旋转 → 保存/新实例 reload → 50mm 16:9 PNG → JSON state。去掉灰色默认地板后，旧的全图标准差指标失去意义；现在检查相对清屏色的模型前景覆盖和前景纹理细节，图片已查看。

```powershell
& F:/gymenv/python.exe -B -m unittest discover -s tests -p 'test_*.py'
& F:/gymenv/python.exe -B tests/ground_separation_smoke.py
& F:/gymenv/python.exe -B tests/ground_separation_smoke.py captures/ground-separation-scale100 100
& F:/gymenv/python.exe -B tests/photo_smoke.py captures/ground-separation/photo-regression
& F:/gymenv/python.exe -B tests/placement_smoke.py captures/ground-separation/placement-regression
& F:/gymenv/python.exe -B tests/ai_api_smoke.py captures/ground-separation/api-regression
```

## 截图与产物

本地目录 `captures/ground-separation/`：

- `near-road-before.png` / `near-road-after.png`：主要近景问题前后。
- `far-river-before.png` / `far-river-after.png`：远景对照。
- `*-reference.png` / `*-grid-on.png`：纯模型参考与 Grid 对照。
- `editor-grid-off.png` / `editor-grid-on.png`：真实 Editor。
- `soldier-road.png`、`soldier-step-low.png`、`soldier-step-high.png`：真实几何脚底验证。
- `explicit-ground-present.png`：显式普通地面确实参与渲染。
- `photo-grid-on.png`、`photo-grid-off.png`、`photo-reference.png`：摄影像素对照。
- `scene.json`、`result.json`：旧版兼容测试场景与数值记录。

100 倍对照位于 `captures/ground-separation-scale100/`。生成图像、测试场景和用户 GLB 不纳入 Git 提交。

## 修改文件清单

| 文件 | 修改 |
| --- | --- |
| `mini3d/placement_plane.py`（新增） | 数学平面、有限范围、射线交点、设置序列化 |
| `mini3d/scene.py` | 移除隐式 Ground 遍历；初始化查询平面 |
| `mini3d/placement.py` | Mesh/plane/fallback 路径；create_ground 返回普通实体 |
| `mini3d/picking.py` | 选择只依据实例锁定，不再保留 ground ID 特例 |
| `mini3d/gl_renderer.py` | 独立、不写深度的有限线网格 pass；去除网格 Z 偏移 |
| `mini3d/material_renderer.py` | 删除 Ground Polygon Offset 特殊分支 |
| `mini3d/editor.py` | 不创建隐式 Mesh、显式添加地面命令、旧场景迁移 |
| `mini3d/editor_ui.py` | Editor Grid 开关、Add → Ground Mesh |
| `mini3d/gltf_loader.py` | 显式 builtin:ground 的既有缓存/实例化入口 |
| `mini3d/api.py` | 保留 V1 接口并使用数学平面；查询兼容字段 |
| `mini3d/commands.py` | 更新职责说明，无命令架构变更 |
| `tests/test_ground_separation.py`（新增） | 6 项架构、查询、锚点、存档回归 |
| `tests/ground_separation_smoke.py`（新增） | 图像、深度、摄影、真实资产放置与 Editor 验收 |
| `tests/rome_visibility_smoke.py` | 旧入口转发到新验收，历史偏移实验保留在 Git 历史 |
| `tests/test_commands.py`、`test_placement.py`、`test_placement_assets.py`、`test_surface_drag.py` | 更新预期为查询平面，而非隐式 Entity |
| `tests/placement_smoke.py` | fallback 命中不再返回 Ground Entity |
| `tests/ai_api_smoke.py` | 使用真正的模型前景断言，而非依赖灰色地板 |
| `readme.md`、`docs/ai-api-v1.md`、`docs/rome-visibility.md`、本文 | 当前用法、兼容行为、历史诊断和验收证据 |

## 仍未解决的问题与边界

- 用户主动创建巨大实体地面并与模型重叠时，仍遵循正常深度遮挡；本次不解决所有真实 Mesh 间的共面冲突或极端尺度精度问题。
- Bounds Bottom 是整体世界 AABB 的单点锚定，不是双脚接触/碰撞解算；跨阶、斜坡或包含底座的角色可能仍有局部悬空或相交。
- 网格是有限线条，受真实几何深度遮挡，近景可全部藏在道路下面；不是无限网格。
- 数学平面保留 V1 的有限范围；不是任意距离的无限放置平面。
- 无默认地板的照片背景是现有清屏色；需要地板时显式添加 Ground Mesh。Photo 功能、灯光和相机存档限制保持原状。
- 实际像素结论来自本机 Intel GPU 和记录的固定姿态；没有声称涵盖所有驱动和所有模型。
