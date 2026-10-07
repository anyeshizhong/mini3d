# Placement V1

分支：`feature/placement-system`，基于 `feature/editor-viewport` 的 `7ec7567`。验证环境：Windows、`F:/gymenv/python.exe`、Python 3.8、Pygame 2.6.1、pyimgui 2.0，2026-10-07。

## 文件与调用关系

- `mini3d/commands.py`：PlacementCommands，所有实例编辑共用的命令入口与历史。
- `mini3d/placement.py`：内置 Ground、SurfaceHit、表面 raycast、纯 Anchor/直立计算。
- `mini3d/scene.py`：稳定实例 ID、按 ID 查找、摆放元数据、独立于 Asset 的 Ground。
- `mini3d/picking.py`：选择和放置共享精确三角形遍历；两者分别决定是否排除 Locked。
- `mini3d/editor.py`：接通命令、输入仲裁、单次拖入事务、场景 v2 持久化。
- `mini3d/editor_tools.py`、`mini3d/editor_ui.py`：World/Local、锁定状态、Inspector/Gizmo 事务；不直接修改 Entity transform。
- `model/manifest.json`：Roman 的 Character 默认值；非 UI 命令调用也使用该已知模型默认规则。
- `mini3d/gl_renderer.py`：仅对有 Ground 的场景将辅助网格线轻微上移，消除共面闪烁；没有改变 Renderer 架构、材质管线或 Ground 几何。
- 新增 `tests/test_commands.py`、`test_placement.py`、`test_placement_assets.py`、`test_placement_gizmo.py`、`test_placement_editor.py`、`placement_smoke.py`。调整原 Editor/STL 测试的默认 Bottom 预期，并检查真实 Inspector 拖动只产生一次历史。

调用方向：EditorUI / Gizmo / Editor → PlacementCommands → Scene；表面放置由 PlacementCommands 调用 placement 的纯几何计算。未来客户端可直接使用同一个 Commands 对象，无需依赖 ImGui、窗口或 OpenGL 上下文。

```python
from mini3d.scene import Scene
from mini3d.gltf_loader import AssetCache
from mini3d.commands import PlacementCommands
from mini3d.placement import create_ground, SurfaceHit

scene = Scene()
scene.ground = create_ground()
commands = PlacementCommands(scene, AssetCache())
with commands.transaction("Place character"):
    soldier = commands.spawn("model/05_roman_soldier/roman_legionnaire.glb")
    commands.set_transform(soldier.entity_id, scale=[.06, .06, .06])
    commands.place_on_surface(soldier.entity_id, SurfaceHit([2, 0, 0], [0, 0, 1]))

commands.undo()  # 一次撤销整个事务
commands.redo()
copy = commands.duplicate(soldier.entity_id)
assert copy.entity_id != soldier.entity_id
commands.lock(soldier.entity_id)
commands.unlock(soldier.entity_id)
commands.delete(copy.entity_id)
```

`spawn(asset_path, name=None, position=None, rotation=None, scale=None, placement_type=None, anchor='bounds_bottom', keep_upright=None)` 创建实例。单独调用 spawn 不寻找表面；需要自动贴面时把 spawn 与 place_on_surface 放入同一事务。坐标和缩放采用引擎原始单位，rotation 为 XYZ 欧拉弧度（矩阵顺序 Rz·Ry·Rx）。Inspector 以度显示角度。

`set_transform`、`place_on_surface`、`duplicate`、`delete`、`lock`、`unlock`、`set_metadata` 均接受实例对象或稳定 ID。`begin_transaction` / `commit_transaction` / `cancel_transaction` 用于连续手势；`transaction(label)` context manager 用于批量命令。禁止嵌套事务；无变化不写历史，失败操作回滚，新的有效操作清除 redo。

历史快照只复制实例 TRS 和元数据，保留根实例对象及共享 Mesh/材质/纹理引用。不修改导入 Mesh、pivot 或 glTF 节点矩阵。ID 在撤销、删除和事务回滚后不复用，save/load 保存已使用的计数范围。只有根实例有 `ent_*` ID，导入的内部节点仍属于同一实例。

## 实际验收

```powershell
& F:/gymenv/python.exe -B -m unittest discover -s tests -p 'test_*.py'
& F:/gymenv/python.exe -B tests/placement_smoke.py captures/placement-v1-validation
```

`placement_smoke.py` 启动实际可见 Editor 窗口，通过真实 SDL 鼠标/键盘事件、ImGui 控件、原 GLRenderer 和材质管线运行流程。没有下载新资产。仅初始 fixture 使用 Commands 放入 Side Table 并调整相机；之后关键操作经 UI 输入完成。

本地原始 Roman 高约 25.963，Side Table 高约 0.761，单位并不一致。验收把桌子实例放大 40 倍，让未缩放士兵能在桌面摆放；Mesh 原始数据不变，Editor 不会自动推测单位。

实际通过的流程：

1. Roman 从 Assets 拖入 Ground，断言世界包围盒最低点 Z=0。
2. 点击 Place on Surface，再点 Side Table 的真实三角形，士兵底部贴桌面。
3. 拖动旋转环，重新表面放置，验证保持 Z-up；每次拖动一条 Undo。
4. 切 Local，旋转后的轴与 World 明显不同；鼠标微调后 Inspector 数值同步。
5. Ctrl+D 复制，验证新 ID 及相同 Mesh/材质/纹理资源引用。
6. Outliner 选桌子并 Lock；左键不能选中它，surface raycast 仍命中它。
7. Ctrl+Z / Ctrl+Y 恢复锁定状态。
8. Box 拖入 Ground；Bottle 拖入锁定桌面，底部与实际鼠标像素命中的三角形高度一致（桌面有不同高度的边缘，不能用整个桌子的最高点代替 hit）。
9. Ctrl+S / Ctrl+O 保存和重新载入五个实例，逐项验证 ID、TRS、locked、类型与 anchor；GL 检查无错误。

产物：`captures/placement-v1-validation/placement-editor.png`、`placement-scene.json`、`placement-result.json`。这些是本地验收结果，沿用 captures 的 Git 忽略规则。

自动测试 **128 项通过**，覆盖合成几何及已有真实资产，额外覆盖斜面人物直立、pitch/roll 消除、非均匀缩放、隐藏实例锚点、批量失败回滚、非法场景载入原子性、ID 不复用、UI 输入捕获。

已有真实窗口回归：`editor_smoke.py`、`editor_integration_smoke.py`、`photo_smoke.py`、`file_dialog_smoke.py`、`stl_render_smoke.py`、`render_smoke.py`。拍照回归覆盖四种镜头/画幅、六张 PNG、PNG 与干净预览一致、九宫格排除、Editor/Shot Camera 独立；Photo 实现没有改动。三个旧示例均运行，旧 STL loader 的 ASCII 探测提示之后正常回退二进制，未导致验收失败。

## 当前限制

- Bounds Bottom 是完整世界 AABB 的底部中心对齐单个 hit；不是脚骨骼、多接触点、穿插或坡面碰撞求解。人物在斜面上保持直立，但不保证整个脚底同时贴面。
- Local 使用实例用户旋转，不使用 glTF 导入轴转换作为 Gizmo 朝向。World Scale 按世界轴在局部轴上的投影权重缩放，以保持 TRS；旋转且非均匀缩放时不能表达完整世界剪切。
- Ground 有限、边长 2000；隐藏或超出范围后按既定 fallback 处理。辅助网格线有微小显示偏移，几何 Ground 始终 Z=0。
- 历史只在内存，载入场景清空历史；未设容量上限，快照开销随实例数/历史数增长，但不复制大网格和纹理。事务尚不支持嵌套。
- 模型单位不自动统一。Roman 约 33.9 万顶点，精确 Bottom 计算约数十毫秒，只在 placement 命令执行；首次加载、射线缓存和大场景操作可能短暂停顿。
- 只为已知 `roman_legionnaire.glb` 提供 Character 默认值，其他人物需手动选择类型。仍按几何三角形拾取，不采样贴图透明度。
- Ground/网格显示、Camera 导航不进入 Placement Undo。锁定实例可改名称/显隐，变换与删除必须先解锁。
- 资产路径仍依赖外部模型文件，场景 JSON 不打包资产；本仓库继续仅跟踪 06 的小 STL，01–05 和 07 不随提交上传。Shot Camera 的既有保存限制保持原状。

## V2 建议（未实现）

优先考虑显式单位/尺寸预设、Prop Align Normal、表面多点接触规则、历史容量策略与更快的大场景 raycast。等单实例流程稳定后再分别设计 Multi Select、Group、Formation 和 AI API；本次未引入这些系统或物理、骨骼、动画、阴影、HDRI。
