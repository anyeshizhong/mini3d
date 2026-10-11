# Renderer V2 — Milestone 2A：Shadow Fit 批量分类

日期：2026-10-11。基线 `f36a0ffae693841e03d8fad21fca058062bf9545`；交付分支 `feature/renderer-v2-cpu-cache`。沿用 `.worktrees/renderer-v2-core` 工作树，根目录本地整理及原始资产保留，没有合并 main。

本轮只修改一个生产文件 `mini3d/shadow_fit.py`：批量执行原有相交算法的包含/排除判断，精确边面求交保留原实现。RenderPlan、Scene.update、ShadowMap、GPU 提交和公共接口均未重构，没有新增依赖或跨帧缓存。

## 分析与选择

使用本机原始 Rome River Side、40 个共享 Roman Legionnaire 实例和一块显式 PBR 地面。42 个根对象、643 个层级节点、258 个绘制实体、24 个共享网格；主颜色资产几何合计 23,948,897 个三角形，不是方块替代成绩。Rome 保持原 Unlit 材质；地面是新增的明确接收物。

固定 `f36a0ff` 的 cProfile，5 次 Shadow Fit：`receiver_matrix` 累积 431.21 ms，`_intersection` 366.53 ms（约 85%）；其中 `_corners` 74.41 ms。矩阵求逆不是本场景最大的开销，主要浪费在大量只需包含/排除判断的逐盒调用、NumPy 小数组和重复几何准备。[原始 profile 与数据](cpu-cache/results.json)。cProfile 有仪表开销，不用其数值充当真实计时。

数据依赖与重复工作：

| 数据 | 依赖 | 基线每帧行为 |
| --- | --- | --- |
| 局部盒角点、数值容差 | 当前模型 bounds | receiver、全场景光空间范围、caster 分别重复准备 |
| 世界角点 | bounds、当前 world_matrix，含父节点变换 | 全场景范围和完全包含的相交分支重复变换 |
| 摄影机平面与角点 | pose、lens、aspect、near/far | 每次 fit 更新，必须保留 |
| 光空间坐标、接收棱柱 | 当前灯光与接收区域 | 每次 fit 更新，必须保留 |
| 精确凸体交点 | 以上几何与当前裁剪体 | 只有部分相交的盒需要边面交点和矩阵求逆 |

## 实现与正确性

一次 fit 中批量准备所有局部角点、世界角点和原数值容差，供 receiver 与 caster 两步复用。对两套平面分别批量计算原归一化距离和包含/排除掩码。完全包含时直接复用世界角点，完全排除时省略输出；部分相交仍调用原 `_intersection`，保留双向棱边/平面求交、容差及退化 fallback。

5 次 fit 的标量 `_intersection` 调用由 2,580 降至 195，`_corners` 调用由 3,875 降至 200；相交实体的精确几何算法没有改变。

没有依据 Python 对象 ID 或 dirty flag 保存跨帧状态：每次 fit 从当前 bounds/world_matrix 的值重建数组。因此位置、旋转、非均匀缩放、父节点与导入矩阵的原地修改、重挂父节点、换模型、修改 bounds、相机和灯光变化、场景加载都不会命中旧结果。已用固定基线检查这 11 种状态，拟合矩阵逐项相等。新单测还用原标量精确相交作 oracle，覆盖 150 个随机旋转、缩放及镜像盒、接触边界、没有内含角点的交叠与退化平面。

caster 继续来自完整场景，不由 receiver 或主颜色集合代替；画外物体仍能进入光空间接收棱柱。一个实际 Roman Legionnaire 的六个网格均被颜色视锥剔除，但七个阴影调用（六个网格＋地面）保留。阴影开关改变 243,998 个照片像素；优化前后差异像素为 0。

## 性能对照

本机：Intel Core i7-8550U、Intel UHD Graphics 620，Windows 10 19045，OpenGL 4.6 / 驱动 Build 27.20.100.8682，Python 3.8.20。CPU perf_counter 计时，预热 3 次、交替基线/优化测量各 21 次。模型加载、GPU 上传和图片编码不计入 CPU 表。RenderPlan 与 Scene.update 调用同一未修改实现，以对照顺序标记 before/after，其波动不归因于本轮优化。

| CPU 步骤 | 基线中位数 ms | 优化后中位数 ms | 基线 P95 ms | 优化后 P95 ms |
| --- | ---: | ---: | ---: | ---: |
| Shadow Fit | 64.667 | 18.456 | 94.956 | 27.569 |
| RenderPlan | 23.594 | 21.450 | 35.677 | 36.304 |
| Scene.update | 29.037 | 26.781 | 40.541 | 49.901 |

**Shadow Fit 中位耗时减少 71.46%，每次约省 46.21 ms。** 这是该真实资产、该机位的 CPU 几何拟合收益；不解释为 GPU 绘制或完整 Shot/FPS 提升。机器存在计时波动，原始样本和 P95 一并保留。第一次试跑同一实际资产的 Shadow Fit 为 73.43→20.47 ms，收益约 72%，最终表采用完成验证脚本的一次运行。

实际 GL 提交在基线/优化中均为主颜色 258 次、Shadow 257 次、合计 515 次；主颜色 23,948,897、阴影 23,942,537、合计 47,891,434 个提交三角形。BLEND 仍不投影；本轮没有通过减少绘制量获取 CPU 收益。

## 验证与证据

- **266 项单元测试通过，无跳过**：既有 262 项＋4 项批量相交专项。
- 实际 Rome＋40，固定 `f36a0ff` 与本轮矩阵、主颜色 RGB PNG 完全一致。
- 修改实际模型变换、相机和灯光后，对照 PNG 完全一致。
- 同一真实场景经 Mini3DAPI 保存/加载，前后 PNG 完全一致。
- 实际 Roman Legionnaire 画外投影测试通过；新旧投影 PNG 完全一致。
- 相关 GPU 回归：Shadow（MASK/BLEND/Unlit、尺寸、状态恢复等）、Lighting API、Shot Camera 跨进程保存加载全部通过。没有重新执行全部历史 UI/大场景压力套件。

[测试汇总和日志](cpu-cache/verification.json)、[unit](cpu-cache/unit.log)、[shadow](cpu-cache/shadow.log)、[lighting API](cpu-cache/lighting_api.log)、[摄影相机重载](cpu-cache/shot_camera_persistence.log)。全部图片由实际 Mini3D OpenGL 输出。

| 实际模型对照 | 基线 `f36a0ff` | 优化后 |
| --- | --- | --- |
| Rome＋40 | [PNG](cpu-cache/original-before.png) | [PNG](cpu-cache/original-after.png) |
| 改模型/相机/灯光 | [PNG](cpu-cache/changed-model-camera-light-before.png) | [PNG](cpu-cache/changed-model-camera-light-after.png) |
| 真实士兵画外阴影 | [PNG](cpu-cache/offscreen-before.png) | [PNG](cpu-cache/offscreen-after.png) |

PNG 保存在仓库用于非商业验证，并按所含 Roman Legionnaire 衍生内容的 CC-BY-NC-SA-4.0 许可分享。Roman Legionnaire：Geoffrey Marchal，[原始来源](https://sketchfab.com/3d-models/roman-legionnaire-40b87797180148e4bace023b6da0c45a)，[CC-BY-NC-SA-4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)；Rome River Side：Shahriar Shahrabi，[原始来源](https://sketchfab.com/3d-models/rome-river-side-8521d86dcd9043eba0b518ccab430d0f)，[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)。[asset-metadata.json](cpu-cache/asset-metadata.json) 记录 GLB 内置署名、来源和 SHA256；原 GLB 与贴图未提交或改写。

## 复现

在 `.worktrees/renderer-v2-core`（当前分支 `feature/renderer-v2-cpu-cache`）执行：

```powershell
F:/gymenv/python.exe -B tests/renderer_v2_cpu_cache_benchmark.py --assets-root F:/python_project/mini3d --profile-only
F:/gymenv/python.exe -B tests/renderer_v2_cpu_cache_benchmark.py --assets-root F:/python_project/mini3d --gpu
F:/gymenv/python.exe -B tests/renderer_v2_cpu_cache_benchmark.py --assets-root F:/python_project/mini3d --offscreen-only
F:/gymenv/python.exe -B -m unittest discover -s tests -p 'test_*.py'
```

默认生成文件位于忽略的 `captures/renderer-v2-cpu-cache/`；缺少两份原始 GLB 时明确失败，不自动下载或替换。另一个 `--offscreen-only` 步骤需要前一步 results.json，用于追加画外投影验证。回归复现命令见 verification.json；Shadow 回归输出目录先放置本机历史 baseline-off/studio PNG，沿用 Milestone 1 的来源。

## 限制与停止

本轮未发现新增引擎错误。批量暂存为 O(N) 内存；若多数盒都部分相交，仍需原精确算法，收益取决于场景。这里没有跨帧静态缓存，RenderPlan 和 Scene.update 的重复 CPU 工作仍在。阴影动态闪烁、1024 ShadowMap 精度、抗锯齿和环境照明未解决；没有引入 C++、LOD 或 Instancing。

Rome 测试布局沿用既有性能脚本的尺度约定（XY 跨度 40、士兵高 1.7、5×8）；未用地形 raycast 做实际贴地摆放，部分士兵被原建筑遮挡。因此这是实际资产的固定性能/一致性基准，不宣称完成 Issue #4 的实景布景验收，也不将 Rome 的 Unlit 材质当 PBR 受影面。

Milestone 2A 完成后停止。下一轮可针对 Scene.update、RenderPlan 做独立 profiling，再评估基于实际数组值变化的静态缓存；本轮不继续开发。
