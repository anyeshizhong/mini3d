# V2 Consolidation：第一阶段代码与架构审计

日期：2026-10-11。基线：`efd5ddc158b7a9709c420564a383b99f0e6b934b`。
范围：全部 31 个生产 Python 模块、根入口/旧示例、tests/tools、质量证据、Git 分支关系，
另对本地工作区建立私有文件清单和整理建议。本次提交只包含本文和 [ARCHITECTURE](ARCHITECTURE.md)。
不删除代码或数据，不重命名公共接口，不变更场景格式，不修改历史分支，不合并 main。

## 结论与优先级

当前主路径可以继续作为 V2 稳定化基线。最明确的冗余是 GLRenderer 的历史注释、
数字示例重复类型，以及 RenderPlan/MaterialRenderer 的重复分类；最大结构风险是
Editor 同时承担运行循环和持久化、ShadowMap 借用 MaterialRenderer 的私有状态/缓存协议。
保持模块数量不是目标，减少模块数量也不是目标。按行为与所有权收敛，先做容易证明等价的批次。

- P0：守住 Q2 原图、Blender 场景/HDR/参数/许可、原始模型、历史渲染结果、未提交内容；
  确认分支和测试证据来源，先审查文档。
- P1：历史注释与职责无关的缓存跟踪、文档/测试入口索引；只在后续获准批次执行。
- P2：Editor serializer/runtime、GPU 状态工具、资产协议、重复规划；每项单独提交。
- P3：legacy 示例共享适配层、未使用公共 helper 的弃用评估；先补足行为证据，不以删文件交付。

下表行数包含空行、注释和内嵌 shader，不能作为复杂度或重构必要性的单独依据。
测试列为可定位的主要覆盖，不把名称相似误当作完整行为覆盖。

## 逐模块职责、调用者、测试与拟修改范围

所有文件在 `mini3d/` 下。D=可删除候选，M=适合收敛共享实现，S=适合拆分，K=保持。
“可删除”仅描述后续候选，本轮未执行。

| 模块 / 行数 | 职责与主要调用者 | 对应测试 / 证据 | 判断、风险与拟范围 |
| --- | --- | --- | --- |
| `api.py` / 253 | Mini3DAPI 薄接口；外部脚本、JSON、Q2 mini 工具；依赖 Editor 状态 | `test_api`、`test_api_dispatch`、`test_lighting_api`、`test_environment`、`test_shot_antialiasing`、`ai_api_smoke` | K/P2；保持公共方法和事务规则，随 Editor 内部拆分解耦，不建立第二套 Scene/历史/serializer |
| `api_dispatch.py` / 69 | JSON 白名单、签名检查、逐命令执行 | `test_api_dispatch`、environment/shadows/Shot AA 单测 | K；不能用反射开放任意方法；保持批次错误/事务语义 |
| `camera.py` / 116 | Camera 参数和 view/projection；Viewer/Orbit/Shot/API | `test_camera`、picking/Shot/render_plan 单测 | K；世界 Z-up、局部 -Z/+Y、clip depth 不变 |
| `orbit_controller.py` / 166 | orbit/pan/zoom、bounds framing/clipping、snapshot；Viewer/API | `test_camera`、`test_scene_clipping`、`scene_clipping_smoke` | K；bounds 与可见深度不是同一用途，不能只为统一 helper 而改裁剪 |
| `viewer.py` / 185 | bounds、导航适配、焦点、取景；Editor/API/旧示例 | camera/clipping、multi_gizmo、placement_v2_editor、`render_smoke` | K/M/P2；与 render_plan bounds 有重叠但场景层级/可见性/容错不同，先界定输入再共享基础数学 |
| `scene.py` / 230 | Mesh、实例层级、ID、组、选择和默认状态；loaders/commands/editor | commands/editor/placement/group/gizmo/render_plan/shadow 单测（广泛间接覆盖） | K；不应把 GL 上传、JSON I/O 或 UI 导入 Scene；`ground` 旧槽位保留兼容，不因无现代使用删除 |
| `gltf_loader.py` / 363 | GLB/glTF decode、材料/静态皮肤、Asset/AssetCache；Editor/Commands/STL | `test_gltf_loader`、`test_placement_assets`、`test_stl_loader`、真实 Q1/Q2 | S/P2；Asset/Cache 可独立为格式无关模块，保留现有导入路径转发；注意 STL ↔ glTF 与 builtin ground 的延迟依赖 |
| `stl_loader.py` / 44 | ASCII/binary STL → 现代 Mesh/Asset；AssetCache | `test_stl_loader`、`stl_render_smoke` | K；引入独立 Asset 协议后可移依赖，保留异常/轴/法线语义 |
| `geometry.py` / 175 | box/sphere/cylinder；旧示例、Q2 球/地面 | shadows/clipping、renderer_v2_smoke、Q2 sphere 原始几何 | K；球体极点零法线和退化三角是已知证据，不能在整理中顺带修几何 |
| `math3d.py` / 45 | normalize、旧 Euler/URDF 变换；数字示例 | 旧示例 `render_smoke`；无专门完整单测 | K/P3；含未用 pygame import 等历史内容，先证明约定；不能以现代 XYZ helper 直接替换旧旋转顺序 |
| `urdf_loader.py` / 330 | XML、link/joint、URI解析、工厂回调建树；旧示例 | `render_smoke` 的真实 URDF 路径；缺独立边界单测 | K/P3；仍是功能；与 glTF loader 不宜合并，格式/变换/实例协议不同 |
| `cpu_renderer.py` / 235 | CPU 投影、面/线/grid 绘制；非 Editor 主路径 | `test_camera` 中的 CPU helper；端到端 raster 覆盖不足 | K/P3；没有生产调用不等于安全删除公共模块，记录兼容用途和欠缺覆盖 |
| `commands.py` / 398 | 快照、事务、撤销重做、根操作、组/编队/拖放；Editor/API经Editor | `test_commands`、`test_placement_v2_commands`、formation/surface/multi_gizmo | K；作为共享修改路径；避免为 UI/API 各自建立历史实现 |
| `placement.py` / 130 | SurfaceHit、surface ray、ground factory、anchor/placement；Commands/Editor/API/SurfaceDrag | placement/placement_assets/ground_separation/commands/surface_drag | K/M/P2；bounds 可研究共用，锚点算法与 Viewer/剔除不等价 |
| `placement_plane.py` / 34 | 有限查询平面；Scene/Editor/placement | `test_placement`、`test_ground_separation`、surface_drag | K；小而清晰，不能合并为真正 Ground 以少一个文件 |
| `surface_drag.py` / 55 | 拖动生命周期、命中与事务token；Commands/Editor | `test_surface_drag`、placement_v2_smoke | K；stale gesture 不能取消后续事务；不可当作普通 transform wrapper 删除 |
| `formation.py` / 65 | 矩形编队参数验证与复制；Commands | `test_formation`、placement_v2_commands、placement_v2_performance | K；纯功能边界已合理，不引入 Instancing |
| `picking.py` / 199 | 屏幕ray/project、AABB/chunk/triangle精确拾取、弱缓存；Editor/Gizmo/placement | `test_picking`、placement_assets、STL、`renderer_v2_cpu_cache_benchmark` | K；mesh不可变假设要明确；拾取缓存与阴影拟合不是重复实现 |
| `editor_tools.py` / 220 | Gizmo 几何与事务更新；Editor | `test_multi_gizmo`、`test_placement_gizmo`、`test_placement_v2_editor`、editor_integration_smoke | M/P2；本地 euler_xyz 与 scene 重复但奇异阈值 1e-7/1e-8 不同，先比较 near-gimbal 输入再共享；保留原符号 |
| `editor_ui.py` / 711 | ImGui panels、Inspector、输入状态；editor.run | lighting_api 中 UI helper、editor_smoke、editor_integration_smoke、lighting_ui_smoke | K/S/P3；panel 可私有拆分，只有需要隔离输入仲裁时做，禁止复制 Commands 操作 |
| `model_dialog.py` / 104 | 异步子进程原生文件选择和结果收集；Editor | `test_model_dialog`、`file_dialog_smoke` | K；子进程隔离有价值，不移回阻塞主循环 |
| `editor.py` / 809 | Editor 状态/命令桥、输入、v3 serializer、SDL/ImGui运行组装；entry/API | editor/API/commands/placement/Shot/lighting单测，editor和photo GPU smokes | S/P2；先拆 serializer，再拆 runtime，两批；保持 Editor 方法转发、load验证后提交状态、API无窗口构造 |
| `lighting.py` / 90 | world light、参数验证、lighting/shadow state；Editor/API/renderers | `test_lighting`、`test_lighting_api`、`test_shadows`、lighting_smoke | K；pure validation 与 GPU执行分开已合理 |
| `environment.py` / 102 | 固定IBL资源检查、状态验证、GPU cube/LUT所有权；API/Editor/MR | `test_environment`、`ibl_gpu_regression`、Q1 bake来源 | K/S/P3；目前尺寸小，不强拆；仅在 GPU状态共用时隔离资源上传，neutral.npz是运行资源非缓存 |
| `render_plan.py` / 115 | 每帧 DrawItem、AABB剔除和队列/统计；GLRenderer | `test_render_plan`、`renderer_v2_smoke` | K/M/P2；收敛与MR的分类/矩阵读取；不引入持久缓存，不让color queue成为shadow queue |
| `gl_renderer.py` / 2369 | 顶层pass、legacy shaders/upload、grid/axes、MR委托、shadow/统计；runtime/示例 | `render_smoke`、STL、renderer_v2_smoke、photo、lighting、shadow、IBL/MSAA GPU | D+S/P1→P2；1–1346历史注释可删除；活动1023行先保留，后抽legacy/guide私有实现；保留公共GLRenderer/helpers |
| `material_renderer.py` / 581 | PBR/alpha/纹理/mesh、排序、选中shell、GL状态；GLRenderer/ShadowMap | lighting/renderer_v2/ibl_gpu_regression/shot_msaa/editor GPU；部分shader静态单测 | M+S/P2；共享GL state独立出来；selection pass可私有隔离；不合并为Scene或RenderTarget，不改shader公式 |
| `shadow_map.py` / 261 | 全场景light matrix、depth target/pass、GLSL可见性、深度导出；GL/MR | `test_shadows`、`test_shadow_camera_fit`、shadow_smoke、renderer_v2/IBL GPU | M/P2；改为借用明确的mesh/texture访问协议，移出通用GL state；不得改变BLEND/MASK、bias/PCF和fallback |
| `shadow_fit.py` / 152 | Shot receiver/frustum/caster交集、批量box classification；ShadowMap | `test_shadow_camera_fit`、`test_shadow_fit_batch`、CPU cache benchmark、offscreen GPU | K；与RenderPlan都是bounds但目标不同；保持纯CPU、每fit复用而非跨帧缓存 |
| `render_target.py` / 129 | RGBA8+D24S8、resize/bind/resolve/close；runtime/Shot/tools | `shot_msaa_smoke`、photo/editor/IBL GPU；Shot AA 单测验证公共samples契约 | K；不承担camera/shading/persistence；`resolve`有意留下公共FBO，不是必须恢复caller的函数 |
| `shot_camera.py` / 152 | ShotCamera数据/序列化、摄影pass、PNG；Editor/API/GL类型判断 | Shot/Shot persistence/Shot AA单测，photo_smoke、shot_msaa、跨进程persistence | K/S/P3；数据与GPU流程可后续私有拆分；保持原导入、默认1×、预览PNG一致、caller FBO恢复 |

### 六个重点文件的边界判断

`editor.py` 是最适合按原因拆分的模块：项目文件格式和窗口循环有不同生命周期。
将 serializer 提为内部服务，同时由 Editor 保持 `save_scene/load_scene` 门面，比把保存逻辑
搬到 Scene 或另写 API serializer 安全。窗口初始化和 backend/event/render loop 再单独迁移。

`material_renderer.py` 应只负责材质绘制及其资源。Selection shell 属于 Editor pass，但用到了
相同 mesh 上传，可抽私有 pass 而不复制资源。通用状态恢复现在被 ShadowMap 借用，适合共享工具。

`scene.py` 是共同数据底座，已经无 OpenGL/UI 依赖，不宜继续塞入 renderer、格式 I/O 或历史栈。
选择/组是已有 Scene 数据契约，第一轮不能为了“纯场景图”迁移公共字段。

`shadow_map.py` 应拥有阴影资源和 depth pass；`shadow_fit.py` 保持数学算法。
它访问 `renderer._get_gpu`、`material_renderer._mesh/_texture`，并非孤立模块。
先提取共享 GL state，再界定资源访问协议，避免同时改所有权、布局和 shadow 算法。

`render_plan.py` 是当前帧的 CPU 快照/分类；没有上传、FBO或持久缓存职责。
`opaque/transparent` 目前仅分类/计数，消费路径仍用 imported 并再次排序。
这不是死代码的充分证据：DrawItem/RenderPlan 是已存在的符号，应保留并收敛消费方。

`render_target.py` 职责清晰，应保持。整数 samples 校验虽被 ShotCamera 数据路径调用，
不需要为129行模块再引入配置框架；不得改变其 public handles和resolve状态约定。

### 需要后续验证的具体风险

以下区分源码可确认的事实与尚未复现的故障，不能把潜在风险写成已经失败的测试：

| 优先级 | 源码事实 / 风险 | 后续验证与限制 |
| --- | --- | --- |
| P1 | `capture_png` 保存READ/DRAW FBO和viewport，但没有像`ShadowMap.save_depth_png`那样隔离PACK_ALIGNMENT/ROW_LENGTH/SKIP状态 | 非默认caller pack状态可能影响PNG读回；新增异常状态回归后再考虑局部修复，现有正常状态GPU通过不证明此情况 |
| P2 | `editor.run` 的target/renderer/app/UI创建位于主try之前 | 构造中途失败可能跳过统一finally；用可控失败验证生命周期，不能只看正常退出close通过 |
| P2 | picking弱缓存、GPU mesh缓存及Mesh.bounds基于已上传/已计算的共享几何 | 直接修改vertices/indices可能产生陈旧拾取/剔除/上传；应明确不可变资源契约，第一阶段不新增编辑几何或缓存失效框架 |
| P2 | `_render_scene` 的实体axes循环不受`clean.show_axes=False`直接控制，只受实体`isaxes`控制 | 历史示例axes实体与干净Shot组合需专项检查；当前真实资产摄影证据不能推导所有legacy helper组合都被排除 |
| P2 | GLRenderer legacy主pass/axes采用部分固定状态恢复，MR/depth pass采用更完整快照 | 每个pass的caller state契约不同；共享状态工具前确认哪些状态由runtime显式拥有，避免“统一恢复”改写调用顺序 |
| P2 | Scene载入先临时验证，但AssetCache可能在验证失败前已加载新模板 | 实时场景原子性与缓存副作用不是同一保证；提取serializer时保留边界，不承诺失败load完全无分配 |
| P3 | `MaterialRenderer`按透明mesh中心排序，不按相交三角形；GLRenderer和MR处理两种模式/颜色路径 | 已有视觉限制，应保留alpha/legacy回归；整理不增加排序算法或统一颜色管线 |

上述验证可以作为相关重构批次的针对性验收，若确认缺陷需另立小修复提交，
不能隐藏在搬文件或删除注释的diff中。

## GLRenderer 历史注释专项核查

基线总长 **2369 行**。第 **1–1346 行**全部为 Python 注释或空行，
运行代码从第 **1347 行**的 `import numpy as np` 开始；活动部分 **1023 行**。
注释中的 GLSL `#version` 也被外层Python注释屏蔽，没有任何编译/注册执行路径。

| 注释区内容 | 核查结果 | 维护价值 |
| --- | --- | --- |
| 第一套screen/world line与普通mesh shader，GLGrid/GLMeshGPU/GLRenderer，旧投影和CPU grid | 第184/226/277行声明旧类，使用旧camera字段/坐标转换；无活动定义 | 可作为Git历史查阅；不应与当前实现并行维护 |
| 第二套重复shader/grid/upload/renderer/axes，旧Z_FLIP/Y_FLIP投影 | 第869/919/971行再次声明旧类，重复projection/axis helper | 原理被活动实现覆盖；不能直接恢复替换现代camera |
| 旧投影与CPU grid试验说明 | focal-pixel、正Z、Y-down等历史约定，与标准GL相机不同 | 将必要说明写入架构/历史索引，无需保留整套注释代码 |

核验方法：AST parse完整文件，与只去掉前1346行的内存文本比较
`ast.dump(..., include_attributes=False)`，结果完全相同；原文件未写回。
Git `log --follow` 可追溯到 `bc7835a` 以及camera、lighting、shadow、RenderPlan各阶段。
未发现源码读取前缀并执行的脚本；全项目搜索调用定位到活动类。
因此此前缀可列为 **低运行风险删除候选**，但后续提交仍需验证shader字符串、行号变化和GPU回归。

不能与此前缀一起删除的内容：活动 GLGrid/GLMeshGPU、legacy REALISTIC/TOON/OUTLINE、
axes/line helpers。数字示例和STL/兼容路径仍依赖它们。
活动 `perspective_matrix`、`perspective_from_focal`、`draw_grid_cpu_like` 未发现项目内活动调用，
但属于可导入/可调用符号；本轮只标记P3弃用评估，不声明可安全删除。

## 冗余、合并、拆分与保持清单

| 分类 | 候选 | 前提 / 禁止事项 |
| --- | --- | --- |
| 可安全删除候选 | GLRenderer历史注释；被Git跟踪的5个CPython 3.8 `.pyc`仅停止跟踪 | 后续批准批次；保留历史；停止跟踪不等于删除用户磁盘文件 |
| 适合合并共享实现 | 两份euler_xyz；三个数字示例的Entity/Scene/Mesh/STLModel；MR重复队列分类；通用GL状态工具 | 奇异阈值/旧TRS顺序不同，先对比；保持公共导入转发，禁止把legacy Scene换成现代Scene |
| 适合拆分 | Editor serializer/runtime；GLRenderer legacy/guide；MR selection/state；loader Asset/Cache | 独立提交，不重命名公共接口；不同时迁移GPU ownership与shader语义 |
| 保持不变 | Camera/Orbit、Commands事务、Scene ID/组、PlacementPlane、surface_drag、shadow_fit、RenderTarget、固定IBL资源、真实资产和基准 | 已有清晰边界；不引入新算法或以文件数量为指标 |

`viewer.world_bounds`、`placement.geometry_bounds`、`render_plan.world_bounds`、shadow fit都使用bounds，
但分别服务聚焦/层级、假设变换的anchor、单mesh保守剔除、receiver/caster交集；不能直接合并成同一结果。
Mesh构造和glTF loader都有法线生成步骤；格式、权重和默认行为需比较，不能顺手“统一”Q2球体法线。

三个旧示例的标量scale及 `extra_local @ T @ R @ S` 与现代实体不同。
主工作区已经存在未提交的examples共享适配尝试；它不是Q2基线，不在本次提交中导入。

## 代码、回归、研究工具和历史证据分类

| 类别 | 内容 | 保留/整理原则 |
| --- | --- | --- |
| 生产实现 | `mini3d/*.py`、editor entry、`mini3d/resources/ibl/*`、requirements | 按运行依赖保留；resources与许可不视为可再生缓存 |
| 长期CPU回归 | 全部 `tests/test_*.py` | 保留；缺真实可选资产时skip必须明确；几何/commands/API/格式边界不可仅靠截图 |
| 长期GPU回归 | renderer_v2_smoke、shot_msaa_smoke、ibl_gpu_regression、photo/Shot persistence、lighting/shadow/ground/placement/editor/STL/file_dialog/scene_clipping/render smoke | 保留；指定新输出目录，避免覆盖验收证据；固定1033e5e仅由shadow baseline显式使用 |
| 性能回归/研究兼用 | renderer_v2_cpu_cache_benchmark、placement_v2_performance、shadow_fit_performance_20261010 | 保留脚本与raw samples/环境；重测不能覆盖历史分布，绝不把耗时断言跨硬件硬编码 |
| 可复现质量工具 | `tools/ibl/bake.py`与上游shader；`tools/quality_q2/{fetch_assets,mini,blender,compare}.py` | 离线工具非运行时；长期基准应保留固定版本、源哈希与许可，不因一次开发任务已结束删除 |
| 专项研究/交互研究 | diagnose_spheres；ibl_quality_q1；render_quality_v1；带日期audit、photographer_session/open_session、ui_photography_journey、open_assets/shadow_motion | 可归档到专项目录并提供索引，脚本并非全是自动回归；先检查路径、入口、runner调用再迁移 |
| 历史实验资料 | docs/testing、render-quality-v1、stabilization-v1、renderer-v2证据，captures历史logs/photos/raw performance，旧worktree ZIP/bundle | 保留唯一原件；截图、npz mask、mp4、scene、日志和机器参数共同归档，不能只留一张拼图 |
| 原资产 | 原GLB、外部glTF+bin+纹理、STL/URDF、HDR、preview和manifest/license | 不清理；转换文件不能替代原文件，GitHub图片不能替代原模型 |
| 可再生物 | 非修改过的pycache/pytest cache、确定来源的临时下载残片、额外软件分发包 | 仅候选，确认哈希/来源/使用情况及回退副本后批准处理；Python用户环境不在清理范围 |

Q2必须保留整个 `docs/renderer-v2/q2/`：三组 `.blend`、1920×1080真实PNG、
coverage/SSAA/诊断图、scene/cases、world AABB/投影核对、results/regressions/manifest、
HDR与原球/地面glTF、NOTICE。Q1 NOTICE、IBL输入/输出metadata与上游许可也保留。
已核验Q2 manifest全部 **48项**大小与SHA-256一致。
Blender 3.6.23便携程序与下载校验信息需作为可复现工具保留至少一份；
重建图片不会复原原运行的计时、驱动状态或人工观察结果。

## Git 祖先关系与 main 安全合入建议

已读取全部本地heads/remote-tracking refs，用 `merge-base --is-ancestor` 与左右提交数核查；
另读取在线 `git ls-remote --heads origin`，远端heads与现有对应跟踪ref一致。
本轮没有依赖fetch成功来声称远端已更新；没有修改历史分支。

```text
main bc7835a → camera refactor 7d55f04 → editor/Placement/API/lighting
 → clipping 1033e5e → shadow 52ee1ee
   ├─ Rome integration 476a799                         （独立支线）
   └─ Shot persistence 7cb7719 → photography 54d19e7 → Gizmo 406d697
      → render quality 7b51eae → Shot Fit e055a98 → fit assessment 7aa2109
      → motion performance f92ea9f → open assets 6d725b4
      → V2 Core f36a0ff → CPU Cache dfcca0d → Q1 1481814 → Q2 efd5ddc
```

| 分支组 | 相对Q2的结果 |
| --- | --- |
| main、refactor/camera-orbit、editor-viewport、placement-system、placement-v2、ai-api-v1、world-directional-light、lighting-v1-controls、fix/editor-scene-clipping、shadow-mapping-v1 | 全部是祖先，无独有提交；无需逐个重复合入 |
| shot-camera-persistence、fix/gizmo-panel-drag-v1、test/photography-audit-20261010、test/render-quality-v1、shadow-camera-fit-v1、test/shadow-motion-performance-20261010、test/open-assets-shadow-20261010 | 全部是祖先，历史证据已经包含在Q2链中 |
| renderer-v2-core / renderer-v2-cpu-cache / renderer-v21-quality-q1 | Q2祖先，分别落后3/2/1提交 |
| test/rome-integration-v1 `476a799` | 分叉点52ee1ee；Rome独有1提交，Q2独有12提交；双方都不是对方祖先 |

本地私有分支、未提交状态和绝对路径只记录在忽略的本机审计目录中，不放入公开提交。
祖先包含只证明已提交历史包含，不证明忽略资产或未提交修改已备份，也不能据此解除Worktree。

建议顺序（**待后续批准执行，本轮没有merge/cherry-pick/main push**）：

1. 审查此文档分支；从Q2建立稳定化集成分支，保留Q2原ref/commit和完整证据。
2. 分批实施下面P1/P2工作，逐批测/提交/回退。不要先合并主工作区的未提交整理。
3. 单独审查Rome支线的57文件变更：其独有提交增加测试/文档/图像，未改生产mini3d代码，
   但会与主链development-progress/shadow报告发生文档冲突。把完整证据带入独立集成提交，
   选择merge以保存分叉历史，或经审查选择明确范围cherry-pick；不把它作为renderer升级父链。
4. 单独review本地整理中的入口/examples/.gitignore/文档与模型manifest差异，
   只带入明确需要的变更；私有路径/资产清单不推送，未提交文件不可整树覆盖。
5. 最终候选跑全量CPU单测、长期GPU矩阵、真实资产/Blender对照和load v1/v2/v3，
   标明每个skip和实际机器环境；基准原图只读，复测另开目录。
6. 创建到main的review PR。main当前是Q2祖先，主链可快进；如采用PR merge commit/保护规则，
   依仓库策略保留完整历史。合入前重新核对在线main与merge-base，先保存release候选ref/tag。
   若main有新提交，重新整合并重测，禁止force-push覆盖。
7. 合入确认后才考虑把主工作区切到稳定main；必须先保存/核验原工作区未提交内容。
   不逐个合入已被Q2包含的feature分支，不删除历史refs以“清理”提交图。

## 分批重构计划

每批独立branch/commit/测试；默认通过新revert提交回退，保留历史，不用reset重写已推送ref。
某批失败仅回退该批；不得把后续批次作为修复前提。公共方法/导入路径保持转发兼容。

| 批次 / 优先级 | 拟修改范围 | 独立验收门槛 | 提交与回退边界 |
| --- | --- | --- | --- |
| A0 / P0（本轮） | 两份公开审计文档；私有清单/整理方案 | 基线/分支/依赖核验，文档链接与隐私检查；Q2 manifest、当前CPU/GPU结果 | 文档一提交；不含任何历史用户修改；revert文档即可 |
| A1 / P1 | 仅gl_renderer.py前1346行历史注释；保存历史引用 | 去前缀AST完全相同；render_smoke/STL三模式、renderer_v2、photo、shadow、MSAA/IBL真实GPU；禁止顺带改活动helper | 单文件注释清理提交，revert完整还原 |
| A2 / P1 | 5个已跟踪pyc停止跟踪（磁盘保留）；ignore/测试与工具索引 | 冷启动/单测、git ls-files无新缓存；确认不忽略质量证据；检查runner引用；本地未提交入口尚未导入 | 仓库卫生提交；不移动/删除本地数据，revert规则/跟踪变更 |
| A3 / P2 | 仅Editor serializer提取到内部服务，原方法转发 | editor/API、Shot persistence、environment/lighting/shadow/AA单测；旧v1/v2/v3、非法load不修改状态、跨进程PNG一致 | serializer提交；依赖门面稳定，revert可回原方法 |
| A4 / P2 | 仅editor.run与backend/window生命周期提取 | editor_smoke、editor_integration、file_dialog、resize/focus/input、退出资源、API构造无窗口 | runtime提交；不同时改变UI面板/输入规则 |
| A5 / P2 | 通用GL state工具从MR提取，MR与ShadowMap引用；原私有方法转发 | IBL 1×/4×、shadow/MSAA、首次upload/unpack、独立READ/DRAW FBO、scissor/stencil/cull/depth/texture恢复和释放 | GL状态提交；不改mesh格式/bias/shader公式；revert所有consumer import |
| A6 / P2 | Asset/Cache中立协议；消除STL与glTF反向依赖 | glTF/STL/builtin ground导入、clone共享/ID隔离、placement_assets、保存重载、缺资产异常 | loader边界提交；保留gltf_loader旧符号转发，完整revert |
| A7 / P2 | MR消费统一规划的分类/矩阵；保持透明排序与无plan兼容入口 | render_plan单测、无效/接触bounds、alpha modes/negative scale、offscreen caster、stats、V2前后像素与CPU cache benchmark | 规划提交；不加跨帧cache/LOD/Instancing；revert后回现有双分类 |
| A8 / P2 | GLRenderer内部legacy与guide拆分；资源访问协议显式化 | legacy/STL三模式、Editor selection、grid无depth写、Shot无grid、shadow上传复用、close幂等和无资源泄漏 | 每个私有pass各提交；公共GLRenderer/GLMeshGPU/helper保持；不与A7混合 |
| A9 / P3 | 示例共享legacy适配、euler重复实现收敛；分别提交 | 固定输入导航/URDF变换/resize截图；near-gimbal、multi-gizmo/undo；两份Euler误差明确后才统一 | 示例和Euler两个独立提交；不从未经审查的本地整树复制 |
| A10 / P0 | 最终稳定候选及main PR | 全部长期矩阵、真实模型、固定Blender三组、默认1×证据、CPU/GPU/内存变动报告 | release集成单独review；main只在下一次获准后合入 |

这些批次不承诺全部都需要实施：小模块职责清楚时保持即可。
拆分不得改变默认渲染模式、颜色空间、几何、阴影算法、样本数或场景JSON字段。

## 本地整理方案（公开原则）

详细文件路径/哈希、空间排行、未提交内容、worktree登记与归档信息保存于本机忽略目录，
不随此提交推送。目录整理与代码重构独立审批，禁止用 `git clean -fdx` 一次性执行。

- 日常工作区最终应使用经过审查并合入的稳定main。当前main仍是初始版，暂以Q2后继独立
  审计/稳定化工作区工作；主工作区存在未提交内容时禁止切换覆盖。
- 原资产和许可/manifest与可再生缓存分开；GLTF必须与bin/贴图一起保留。
  质量输入、摄影原图、性能raw样本、运行日志、场景和环境信息组成一个归档单元。
- 测试输出按revision/日期/场景/renderer/sample模式归档，保留1×、4×、SSAA、Eevee各自原件。
  公开证据进docs；机器路径、下载程序和详细清单进忽略目录。
- 建议补充Q2基线ignore：根`.worktrees/`、`archives/`、`.vscode/`、`.venv/`、`scenes/`和确认
  属于可选本地资产的model目录；保留小STL fixture、tools、resources、Q2 docs跟踪。
  主工作区已有未提交ignore修改，后续需逐条review，不能整文件覆盖或全局忽略PNG/JSON/GLB。
- 已被Q2包含的历史worktree仍可能保存忽略的原件。解除前列出tracked/untracked/ignored、
  检查进程使用和目录联接、归档完整内容、SHA-256/ZIP CRC和恢复演练，再逐个审批。
  固定阴影基线有测试依赖，先迁移调用再评估，不直接移除。
- Blender固定版本至少保留可复现的一份分发/程序和校验信息；迁出worktree是用户数据移动，
  必须审批并验证Q2重渲染。最大空间收益来自重复软件包或经核验的历史工作区副本，
  不是删模型/原图。精确估算只在私有本机清单中列出。

## 本轮验证及限制

新增文档前从Q2建立独立审计分支；保持主工作区和三个原开发worktree未提交状态不变。

| 检查 | 本轮结果 |
| --- | --- |
| 全模块AST/import/调用者、函数内import、测试入口核查 | 31生产模块，逐模块职责表；动态对象协议结合源码人工核查 |
| GLRenderer纯注释前缀内存删除模拟 | 前1346行全为注释/空行，AST结构完全相同；源文件未改 |
| Git全部refs/worktree/在线远端heads/祖先关系 | 主链线性；Rome分叉；历史分支未修改 |
| Q2清单大小+SHA-256 | 48/48一致，包含三组blend和原始渲染证据 |
| `python -B -m unittest discover -s tests -p 'test_*.py' -v` | 271项发现运行，OK，8项/子项skip：独立worktree未安装可选模型；不解释为全资产验证 |
| 可选资产补测 | 仅在测试进程内把两测试模块的PROJECT指向既有模型目录，未复制或修改资产；glTF五模型、外部glTF/GLB等价与真实Placement共4项测试通过，无skip |
| `shot_msaa_smoke.py` | UHD 620真实GPU，4×FBO/color/depth/stencil、resize、preview/PNG、save/reload、caller state/close通过 |
| `ibl_gpu_regression.py … 4` | 真实3.3 core上下文请求；alpha/Unlit、upload状态、离屏caster与资源释放通过 |
| `renderer_v2_smoke.py --assets-root …` | 真实GPU，offscreen shadow/mixed transparency/DamagedHelmet路径与剔除前后检查通过 |

本轮使用既有Python 3.8.20环境，NumPy1.24.3、pygame2.6.1、PyOpenGL3.1.10、imgui2.0.0；
真实GPU为Intel UHD Graphics 620，驱动报告GL4.6.0 Build27.20.100.8682。
测试新产物只写新审计输出目录，不覆盖历史图片/日志；详细日志留本机。
没有重跑完整Blender三场景渲染、全部历史UI/资产性能矩阵，也没有证明跨平台/驱动一致。
既有Q2结论来自保留的原始报告，本轮不会将历史验证冒充新运行结果。

完成文档提交与推送后停止，等待下一次审查；任何代码删除、目录解除、归档移动或空间清理
都属于下一轮明确审批后的分批操作。
