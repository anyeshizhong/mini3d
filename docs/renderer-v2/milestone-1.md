# Renderer V2 — Milestone 1

本轮只实现轻量 RenderPlan、保守视锥裁剪和模型绘制统计。保留现有 Placement、Photography、AI API 和 Scene 存储格式；没有新增依赖，没有合并 main。

## 基线与工作区

远端 `git ls-remote` 和本地祖先检查确认：

- `406d697730d833fa9685f07342cf49e1e79427e2`：Gizmo 修复。
- `7aa2109076cbc90f5cf67f0f6dc5b429414b0929`：Shot 阴影视域基线，包含上述修复。
- `f92ea9ffd1d30263658778a990c235adca8fdb5c`、`6d725b4d537eeee7f11bc2c1d23333260f032a15`：后续测试证据，均沿该历史继续。

V2 分支 `feature/renderer-v2-core` 从 `6d725b4` 建立。根目录停在 `chore/local-consolidation-20261010`，有尚未提交的本地整理；没有覆盖、暂存或提交其中的内容。V2 工作树位于 `.worktrees/renderer-v2-core`。六个已忽略的模型子目录用 Windows junction 引用原本地模型，模型和贴图没有复制进提交，也没有删除原资源。

开发历史参考：[Issue #4](https://github.com/anyeshizhong/mini3d/issues/4)、[Issue #6](https://github.com/anyeshizhong/mini3d/issues/6)。本轮不声称解决阴影运动稳定性。

## 实现边界

`mini3d/render_plan.py` 每帧只展平一次场景，读取 Scene.update 后的世界矩阵，准备 DrawItem（原实体、共享网格、材质、float32 绘制矩阵、世界 AABB）。主颜色集合分为 legacy/imported 与 opaque/transparent；GPU 资源仍通过原渲染器缓存按需解析，不重复上传。MaterialRenderer 原有透明物体远到近排序保持原样。

视锥采用 OpenGL 列向量约定，从 P×V 的行提取六个平面。局部包围盒经完整世界矩阵转成保守世界 AABB，包含旋转、父子变换、镜像和非均匀缩放；批量测试每个盒在六个平面上的最大支撑值，仅在盒完全位于任一平面外时剔除。接触边界、大地面和包围整个视锥的盒保留。为 float32 绘制算术保留相对数值余量。

未知或无效包围盒、非仿射矩阵保留；不靠中心点决定可见性。legacy OUTLINE shader 会扩张几何，因此该模式下 legacy 网格保守保留；带实体坐标轴的网格也保留。选择描边仍使用编辑器原有独立路径。

阴影候选集合保留完整场景实体，包含画外和远裁剪面之外的投影物，也包含拟合需要的接收物。没有把颜色可见集合交给 Shadow Fit 或 Shadow Pass；原 BLEND 不投射阴影规则未改变。

没有跨帧新缓存：相机位置/旋转、镜头、aspect、near/far、实体/父节点变换、材质、可见性、替换网格和场景重载均在下帧重新准备。现有网格/纹理 GPU 缓存的资源生命周期仍由原实现管理。

`renderer.frustum_culling = False` 可关闭裁剪用于对照。`renderer.last_render_plan` 可查看准备结果；`renderer.render_stats` 提供：

- `entities_before/after/culled`：显式 visible 筛选后的绘制实体数与颜色裁剪结果，区别于场景根对象数。
- `bounds_tested`、`shadow_candidates`、`opaque_entities/transparent_entities`。
- `color_draw_calls/shadow_draw_calls`、`color_triangles/shadow_triangles`：在实际 glDrawElements 调用后计数，legacy outline 两遍分别计入。
- `draw_calls/submitted_triangles`：上述模型颜色和阴影提交之和，不包含网格线、坐标轴、选择描边和 ImGui。不是整帧所有 GL 调用数，也不是去重后的资产三角形数。
- `render_plan_cpu_ms`：准备步骤的 CPU 时间，不是 GPU 时间。

## 实测

Windows 10 19045，Intel Core i7-8550U，Intel UHD Graphics 620，OpenGL 4.6 驱动 Build 27.20.100.8682，Python 3.8.20，Pygame 2.6.1。基准从 Git 固定提交加载原 GLRenderer；材质和阴影 pass 共用原算法及本轮计数仪表。每个条件预热 3 次，交替 V1/V2 测量 21 次。完整同步渲染为 render/render_shot + glFinish，排除 Scene.update、PNG 编码和首次上传；Shot 包含 FBO 绑定与 resize。

以下为最终一次运行的中位数（ms）。GPU 项使用独立 GL_TIME_ELAPSED 查询，7 次；查询代表 GPU 命令时间线，可能包含提交间隙，不解释为纯着色器执行时间。所有原始样本、P95、CPU update/fit/plan 和 GPU 查询在 [results.json](results.json)。

| 场景 | 根/绘制实体 | 主颜色调用 V1→V2 | 阴影调用 | 同步中位数 V1→V2 | 降低 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 大地面 + 画外 caster | 2 / 2 | 2→1 | 2→2 | 17.158→17.094 | 0.4% |
| 层级/镜像/透明/Unlit + 40 画外方块 | 46 / 46 | 46→6 | 44→44 | 22.970→14.306 | 37.7% |
| DamagedHelmet + 40 画外方块 | 41 / 41 | 41→1 | 41→41 | 42.645→26.822 | 37.1% |

包含阴影的模型调用分别为 4→3、90→50、82→42；提交三角形分别为 48→36、1080→600、31864→31384。减少的只是被裁剪主颜色提交，阴影提交保持原样。RenderPlan CPU 中位数为 0.649、5.510、6.194 ms；因此全可见/极少实体场景不保证加速。首次运行两个 40 画外方块场景中位数降低约 37%/30%，两次运行绝对耗时和 P95 有波动，不设通用 FPS 承诺，也不宣称 GPU shader 明显加速。

这些 40 个方块是明确命名的裁剪测试负载，不代表 CesiumMan 或 Roman Legionnaire 的真实复杂度。House/CesiumMan 本机未找到；Rome 原 GLB 可用，但按本轮额度约束没有重跑 Rome＋40 大型压力报告。没有用替代模型冒充这些场景的验收成绩。显存没有可靠测量；本轮未改变纹理/FBO规格。

## 正确性证据

262 项单元测试全部通过，无跳过；其中新增 11 项覆盖六个裁剪平面、接触边界、巨大地面、独立八角点支撑 oracle、父子旋转和非均匀/负缩放、不同相机/lens/aspect、动态修改和保守 fallback。已有 Placement、分组、Undo/Redo、API 和存储契约单测保持通过。

三个实测场景均与固定 V1 输出逐像素一致，差异像素为 0；关闭 V2 裁剪也逐像素一致。额外测试 REALISTIC/Wireframe、REALISTIC/Unlit、TOON/Lit、OUTLINE/Lit，全部逐像素一致，并独立拦截实际 GL 提交核对统计。画外 caster 确认不进入颜色集合、仍进入阴影集合；阴影开关改变 1,280,000 个实际图片像素。

六个相关 GPU/UI 脚本通过：Photo（预览与导出 PNG）、Shot Camera 跨进程重载、Lighting、Shadow（含 MASK、BLEND、Unlit、状态恢复）、Camera clipping（focus 与 near/far）、Editor integration（拾取、Gizmo、Inspector 和输入仲裁）。没有重跑完整历史 81 项 UI 测试。[验证汇总](verification.json) 记录范围。Shadow 脚本第一次因隔离目录缺历史 baseline PNG 而退出；引用本机已有历史证据后通过，非引擎失败。

实际引擎输出：

| 测试 | V1 | V2 |
| --- | --- | --- |
| 混合材质/层级 | [PNG](mixed-v1.png) | [PNG](mixed-v2.png) |
| 真实 PBR 头盔 | [PNG](helmet-v1.png) | [PNG](helmet-v2.png) |
| 画外阴影 | [Shadow off](offscreen-shadow-off.png) | [Shadow on](offscreen-shadow-on.png) |

头盔为 Khronos glTF Sample Assets 的 DamagedHelmet，沿用已有固定来源 `edc7c9e67c639d230715049ee31f9a96a6babbbe`。ctxwing：重建与 glTF 转换，CC-BY-4.0；theblueturtle_：原始版本，CC-BY-NC-4.0。完整元数据见 [已有资产来源](../render-quality-v1/asset-sources.json)。本轮仅保存真实渲染证据，不提交原 GLB/纹理。方块及场景为项目原创测试几何，没有生成式图片。

## 复现

在 V2 工作树中，使用本机现有环境：

```powershell
F:/gymenv/python.exe -B -m unittest discover -s tests -p 'test_*.py'
F:/gymenv/python.exe -B tests/renderer_v2_smoke.py --assets-root F:/python_project/mini3d
F:/gymenv/python.exe -B tests/photo_smoke.py captures/renderer-v2/regressions/photo
F:/gymenv/python.exe -B tests/shot_camera_persistence_smoke.py captures/renderer-v2/regressions/shot_camera_persistence
F:/gymenv/python.exe -B tests/lighting_smoke.py captures/renderer-v2/regressions/lighting
F:/gymenv/python.exe -B tests/scene_clipping_smoke.py captures/renderer-v2/regressions/scene_clipping
F:/gymenv/python.exe -B tests/editor_integration_smoke.py
```

`tests/shadow_smoke.py` 需要先在输出目录放置历史 `baseline-off.png` 与 `baseline-studio.png`；本机来源为根目录 `captures/stabilization-regressions/shadow/`，本轮副本位于 V2 的 `captures/renderer-v2/regressions/shadow/`。然后运行 `F:/gymenv/python.exe -B tests/shadow_smoke.py captures/renderer-v2/regressions/shadow`。重新建立工作树时，可选模型需保留原目录或重建同样的本地 junction；没有可选资产时对应单测按原规则跳过。

## 已知限制与下一步

没有发现本轮新增的引擎错误；测试不能证明所有场景无 Bug。六平面 AABB 判定允许保守假阳性，没有精确多面体相交或遮挡剔除。未知 bounds 和 legacy outline 暂时不裁剪。主颜色集合每帧重新建立，没有静态世界 AABB/光源空间缓存；全可见场景仍付出规划开销。Issue #6 的阴影运动变化保持原状态。

Milestone 1 完成后停止。下一轮建议先用真实 House＋40 / Rome＋40 及静态 CPU profiling 评估规划开销，再考虑有明确失效规则的包围盒缓存；阴影稳定化需独立里程碑和授权。
