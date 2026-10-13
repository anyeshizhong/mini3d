# Project SPQR — Phase 1 罗马街道搭建原型

## Phase 1.1 更新

创建对话框新增 **Vary buildings**、**Variation seed**、**Beyond arch (0-6)**。API 对应可选参数 `variation=False, seed=0, extension_segments=0`；省略时仍是原来的49模块布局。示例启用 `variation=True, seed=17, extension_segments=4`，生成85个可编辑实例、40米直街和末端小广场/三栋建筑。开启延伸会额外添加4个广场模块，最大组合为149个根实例。

建筑使用有限的米白/赭黄/玫红共享模板，并变化宽度、高度、退距、窗位和柱位；固定种子可重复生成，宽度保持在单段范围内。生成后都是普通实体，不提供自动参数重排，也不会重新生成覆盖手工修改。颜色通过可保存的builtin变体标识实现，不直接修改其他实例共享的材质。

天空仍为全屏程序天空；将浮点sin哈希换为整数格点哈希后，本机截图上的多边形云色块消失。GPU格点连续性检查通过，但旧哈希在该简化检查中也通过；驱动精度/编译行为的细分根因尚未完全定位。没有引入体积云或天空网格。

屋顶原先只有两侧单层坡面；现补齐厚度、底面、檐边，并使山墙接合。正常背面剔除仍启用；同时检查两坡正面和底面绕序。

示例仍经 `build_roman_street.build_scene → Mini3DAPI.create_roman_street → PlacementCommands → street → spawn/create_group` 搭建。模板几何和布局规则是Python代码，最终场景是可保存、可编辑的模块集合；这并不等于通用城市生成器。

新增验收：`python -B tests/sky_noise_smoke.py`，`test_spqr_variation.py`。`spqr_smoke.py`包含穿过拱门后的机位、真实导航渲染耗时及draw统计。重载图像允许极少量边界光栅差异（最大通道32、像素比例不超过0.01%），Undo仍要求逐像素相同。本机最终重载差异为103/2073600像素，最大通道25；未宣称完全一致。

SPQR = Scale / Performance / Quality / Richness，也呼应罗马主题。
基线为摄影阶段 `feature/sunset-roman-portrait` 的 `18a4269f143fc3d0be7f48c85a4e5792b3164a51`。
本阶段目标是可编辑、可保存、可加载、可拍照的一条直街。几何是原创的罗马风格低模示意，不声称历史复原精度。

## 使用

```powershell
python -B -m mini3d --scene examples/roman_street/street.json
```

也可以从空场景开始：`python -B -m mini3d --empty`，在 Arrange 左侧点击 **+ Roman Street...**，或 **Add → Roman Street...**。
默认 6 段，每段 4 m，共 24 m；道路宽 6 m。可设 2–12 段（8–48 m）、4–10 m 路宽、街道中心和朝向。
单位为米、Z 向上；朝向 0 沿 +Y，UI 用度，Python/JSON API 用弧度。
中心 Z 是路面高度。人行道高 0.18 m，房屋与细节落在人行道上。

创建会追加普通实例，不清空当前场景。默认 49 个可编辑根实例，上限 97 个。
每栋房屋作为一个整体模块，墙、门窗和屋顶属于其共享模板。门窗是封闭立面示意，没有室内、碰撞或步行导航系统。
生成后不会保持参数化关联：继续使用普通选择、Gizmo 和 Inspector 修改模块，不会自动重新生成或覆盖人工编辑。

1. 点选房屋，使用 G/R/S 或 Inspector 改变位置、旋转、缩放；Ctrl+D 复制，Delete 删除。
2. Outliner 中选择整条街道组，或 Roads / Buildings / Details 分组整体调整。组是现有平面成员集合，不是父子变换树。
3. Ctrl+Z 一次撤销整次街道添加，Ctrl+Y 恢复相同 ID 和分组。后续编辑各自进入现有历史。
4. 可锁定道路后继续向其真实表面拖入资产；锁定防止误选，不妨碍表面摆放。
5. Ctrl+S 保存到 `scenes/editor_scene.json`，Ctrl+O 载入。保存的是普通 v3 场景；所有街道资产均为内置资源，无下载或绝对模型路径。
6. 用现有 Shot 流程创建/更新相机、进入 Camera View、Capture PNG。示例已保存街景机位，直接进入 Camera View 即可拍照。

内置模块也出现在 Assets，可独立拖入、双击添加或通过 API spawn。

| 标识 | 尺寸与方向 |
| --- | --- |
| `builtin:roman-road` | 6×4 m，X 宽 Y 长，路面 Z=0、厚度向下 |
| `builtin:roman-sidewalk` | 2×4 m，高 0.18 m |
| `builtin:roman-shop` | 临街单层店屋，正面朝 −Y，4 m 宽、5 m 深 |
| `builtin:roman-house` | 临街两层房屋，正面朝 −Y，4 m 宽、5 m 深 |
| `builtin:roman-column` | 独立柱子，高约 2.8 m |
| `builtin:roman-arch` | 中间真实拱洞，沿 X 横跨道路 |
| `builtin:roman-amphora` | 陶罐，高约 0.7 m |

## Python / JSON / IPC

```python
from mini3d.api import Mini3DAPI
api = Mini3DAPI()  # 也可绑定现有 Editor
street = api.create_roman_street(segments=6, road_width=6.0,
                               origin=[0, 0, 0], facing=0.0)
api.save_scene('scenes/my-street.json')
```

```json
{"command":"create_roman_street","args":{"segments":6,"road_width":6,"origin":[0,0,0],"facing":0}}
```

通过现有 `EditorClient.call('create_roman_street', ...)` 使用同一 IPC 白名单。
返回总组 `group_id`、`member_ids`、`groups` 分类组、`entity_count`、`length`、`width`、原点和朝向。
创建自带事务，不能嵌入 JSON `transaction`；输入在修改前验证，执行失败回滚场景，ID 计数器沿用既有不倒退规则。
API 只创建并选择街道，保留 workspace、编辑机位、摄影机和灯光。UI 另外切回 Arrange 并框取新街道。
摄影相机沿用 `18a4269` 的构图衔接规则：Camera → Editor 继承构图，调整后回 Camera 应用新构图并保留摄影参数。

## 实现与范围

`roman_assets.py` 生成固定几何，`AssetCache` 缓存模板；同类实例共享 Mesh/材质，模块内按材质合并细节。
`street.py` 仅计算有上限的直街布局，通过 `PlacementCommands.spawn/create_group/transaction` 创建实例。
Editor UI、API、IPC 进入同一命令，沿用 Scene / Placement / Shot / scene_io。
未修改存档版本、渲染器、阴影算法或摄影流程，未增加依赖。

本阶段不包含无限世界、地形编辑、CSM、GI、路网、程序化城市、历史数据库、GPU instancing、LOD 或自动避让。
场景规模上限仅限制一次创建；重复追加仍会增加成本。现有命令快照和逐实例 draw 成本仍存在，不能据此承诺大型城市帧率。

## 验收

```powershell
python -B -m unittest discover -s tests -p 'test_*.py'
python -B tests/spqr_smoke.py --output captures/spqr-acceptance
python -B tests/live_view_api_smoke.py --output captures/spqr-view-acceptance --scene examples/roman_street/street.json
```

GPU 验收需桌面 OpenGL 3.3；输出目录应为新的目录。单元测试保护事务原子性、编辑、缓存共享、保存加载、参数边界与已有摄影兼容。
GPU 验收输出街景与全景、重载对照和实际资源/耗时统计；实际测量不等同于 FPS 保证。
示例可由 `python -B tools/build_roman_street.py` 重建。

## Phase 2 建议（尚未实现）

先用这条街道验证搭建手感，再考虑模块对齐/吸附和少量建筑变体。
基于真实 profiling 决定是否优化批量命令和重复模块绘制；待需求明确再评估区块管理。
历史资料和外部资产应在比例、来源及许可核实后逐步接入，不扩展成本期自动城市系统。
