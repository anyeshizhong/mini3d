# Rome River Side 几何消失诊断

2026-10-08，Intel UHD Graphics 620，真实桌面 OpenGL / Editor。使用本地 `model/08_rome_river/rome_river_side.glb`，未改 GLB、材质或实例几何。

## 结论

已复现**原始比例模型在部分俯视角度下河面消失**。根因是巨大内置 Ground 的深度精度误差，使它错误遮挡略高于 Z=0 的河面；不是 glTF doubleSided 丢失、winding 错误或 camera near/far 裁掉模型。

另外，从 Z<0 的地面下方向上看时，双面的不透明 Ground 会正常遮挡地上的模型。这种遮挡保留；需要查看底部时可使用现有 Ground 开关。

## 按顺序进行的 A/B 实验

脚本：`tests/rome_visibility_smoke.py`。每个比例使用 8 个固定姿态，6 个位于地上、2 个位于地下；相机位置、裁剪范围、每次 draw 的 culling/depth/blend 状态及像素差记录在 `result.json`。

1. **原行为 / 临时禁用 GL_CULL_FACE**：所有视角差异均为 **0 像素**。测试拦截绘制期间的 `glEnable`，确保不会在 primitive 绘制时重新开启 culling，而不只是帧开始时关闭一次。原始文件 4 个材质全部 `doubleSided=true`，每个材质 draw 实测 culling 都关闭。测试结束恢复，不增加生产开关。
2. **Alpha**：临时将所有材质改成 OPAQUE。只有原来 BLEND 的 Fire 改变，问题视角差异 22 像素，河面仍消失。河面所属材质本来就是 OPAQUE，没有 alpha discard；实测普通材质写深度、Fire 不写深度。
3. **Depth / Ground**：隐藏 Ground 后河面恢复。单独渲染模型和 Ground，读回深度缓冲并反投影到世界空间：本应位于 Z=0 的 Ground 在问题区域算成 **Z=0.001212～0.001226**，错误遮挡 **1,949 个模型像素**。此模型宽约 0.97、高约 0.31，而 Ground 是边长 2000 的两个三角形；尺度悬殊造成地面光栅深度不稳定。临时缩小 Ground 的控制组也恢复河面。
4. **near/far**：问题姿态 near=0.019436、far=5.477353，所有模型顶点视空间深度位于 **1.532709～2.508829**，完整落在裁剪范围内。又分别扩大裁剪范围、收紧 near 做对照；这些操作会改变深度误差，不能据此误判为几何被裁剪。因此保留原 Camera 算法和参数。

问题姿态：yaw=0.8、pitch=0.7，camera position=`[1.03109915, 1.05889054, 1.40740974]`，实例 scale=1、Bounds Bottom 放在 Ground。离屏截图 960×640。以上像素统计不把隐藏 Ground 造成的背景变化误算为“恢复的模型”。

## 最小修复

只修改 `mini3d/material_renderer.py`：

- 当且仅当当前实例是 `scene.ground` 时，启用 `GL_POLYGON_OFFSET_FILL` 并设置 `glPolygonOffset(1, 1)`，把地面的光栅深度略向后偏移。
- 普通模型绘制关闭此偏移；保存并恢复调用方的 enable、factor、units，异常路径同样恢复。
- Ground 几何仍严格位于 Z=0，raycast、Bounds Bottom、持久化及原始 glTF 不变。继续按材质 doubleSided 和变换 determinant 选择 culling / winding。
- 没有永久全局关闭 culling，没有关闭深度测试，没有扩大 camera clipping，也没有重构 Renderer。

这种偏移是光栅层面的接触容差，不是严格几何位移；非常贴近 Ground 的表面会获得显示优先权。并不解决任意模型间的共面冲突，也不承诺所有 GPU、极端尺度或接近地平线的姿态完全无深度误差。

参考：[Khronos glTF 双面材质定义](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#double-sided)、[Khronos Polygon Offset 参数说明](https://wikis.khronos.org/opengl/Parameters_of_Polygon_Offset)。前者的规则已在原渲染器中实现；后者用于本次仅作用于内置 Ground 的修复。

## 验证与截图

- 原始比例 8 视角实际 GL 测试通过；6 个地上视角修复后 Ground 错误遮挡模型的像素全部为 **0**，问题视角为 **1949 → 0**。
- 另以实例 scale=100 重跑同组姿态，验证先前环境测试使用的比例。
- 真实 Editor 启动，固定同一相机，在同一进程内生成前后截图：修复前河面被灰色 Ground 覆盖，修复后河水可见。
- 实际 GL 回归检查：单面材质继续 cull，负 determinant 使用 CW，双面材质不 cull，偏移仅作用于 Ground，调用方偏移状态在成功和异常后均恢复。
- **191 项自动测试通过**。
- `tests/photo_smoke.py` 通过：真实按钮、4 个镜头/画幅、6 张 PNG、Camera View 与 Capture 一致、构图线不进入成片、Editor/Shot Camera 独立。

产物目录 `captures/rome-visibility/`（本地生成，不提交图片或 GLB）：

| 文件 | 内容 |
| --- | --- |
| `view-04-A-original.png` | 原行为，河面缺失 |
| `view-04-B-no-cull.png` | 临时禁用 culling，与 A 完全相同 |
| `view-04-C-opaque.png` | Alpha 排查 |
| `view-04-D-no-ground.png` | 移除 Ground 的深度控制组 |
| `view-04-E-wide-clip.png` / `view-04-F-tight-near.png` | 裁剪范围控制组 |
| `view-04-G-small-ground.png` | Ground 大小控制组 |
| `view-04-H-fixed.png` | 保留 Ground，仅启用局部深度偏移 |
| `editor-before.png` / `editor-after.png` | 真实 Editor 同视角前后截图 |
| `result.json` | 全部视角状态与数值 |

```powershell
& F:/gymenv/python.exe -B tests/rome_visibility_smoke.py
& F:/gymenv/python.exe -B tests/rome_visibility_smoke.py captures/rome-visibility-scale100 100
& F:/gymenv/python.exe -B -m unittest discover -s tests -p 'test_*.py'
& F:/gymenv/python.exe -B tests/photo_smoke.py captures/rome-visibility/photo-regression
```

诊断脚本中的 GL monkeypatch、alpha/ground/clip 控制组仅供复现实验，不进入运行时配置。
