# FILE_REGISTRY.md — Mini3D 文件职责登记簿

**本文件只回答：当前有哪些文件、每个文件现在负责什么、哪些代码关系需要核对。**

这是随源代码同步维护的**现状表**，不是开发日志。不得写日期、某次新增了什么功能、哪次合并了什么或如何实现。修改时间和修改过程由 Git 提交及 PR 承载。

每个现存脚本应有：**准确路径、现在的职责与边界、必要的对外接口 / 上下游 / 测试关联**。当前部分条目仅做过模块头部抽查或根据旧文档定位，故保留“已抽查 / 待核验”状态以免把推测当事实。动手修改前必须查源码；不要让此登记代替实现。

## 强制同步规则

- **新增**：在所属分类登记新文件的现行职责，不写“新增了一个……功能”。
- **删除**：移除对应条目，不留“已删除”或历史条目；同步检查导入和文档链接。
- **合并**：保留真正存在的合并后文件，描述它现在承担的全部职责；删除被合并的旧文件条目。
- **重命名、拆分**：依据当前路径与职责更新，去除旧路径。
- **修改已有代码**：只有职责、接口、上下游或测试归属改变时才修订原条目；单纯内部优化不增加记录。
- **同时交付**：上述变动与登记簿须在同一任务/PR 内完成，必要时更新 `FIRST.md` 的分类索引和 `OPERATIONS.md` 操作规程。
- **检查一致性**：不得保留不存在的脚本路径，不能遗漏新增脚本。对尚未完成逐项核验的测试/工具分类，应明确注明，不可假装已逐个登记。
- **只查所需**：主 Agent 根据 FIRST 分类读取对应小节、源文件及测试，不必全读。
  
## A. 入口、编辑器和 UI（工作区）

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/__init__.py` | Python 包初始化；不是编辑器主入口 | 待核验 |
| `mini3d/__main__.py` | `python -m mini3d` 的入口，转交 `editor_app.main` | 已抽查 |
| `editor_app.py` | 解析 CLI 参数（场景、资产、无窗口、截图、IPC）后运行编辑器 | 已抽查 |
| `editor.py` | 顶层兼容启动入口，避免与 `mini3d/editor.py` 混淆 | 待核验 |
| `mini3d/editor.py` | 编辑器应用状态、用户输入分配、场景/命令/Viewer/Shot 的联结点；不负责 ImGui 面板绘制 | 已抽查 |
| `mini3d/editor_runtime.py` | Pygame/ImGui/OpenGL 生命周期、首帧界面、后台资产结果交付与分帧 native 资源准备，后续新增/重建保留已有视口至就绪；Arrange 经共享场景入口绘制并叠加辅助图形；隐藏及固定帧数运行同步输出场景 | 已抽查 |
| `mini3d/editor_ui.py` | Dear ImGui 全局工作区栏、可调面板、资产列表/属性表、实际图像输入捕获和临时 UI 状态；通过应用命令触发操作，不拥有 Scene | 已抽查 |
| `mini3d/editor_loading.py` | 交互资产请求、取消与主线程提交；后台模板经 AssetCache.adopt 接入现有 Add/Drop/Import 命令和 Undo，拖放保存请求时的表面命中；同步 API 独立保留 | 已抽查 |
| `mini3d/editor_tools.py` | 变换 Gizmo 和视口内编辑工具的交互 | 待核验 |
| `mini3d/model_dialog.py` | 模型文件选择对话框及其生命周期 | 待核验 |
| `mini3d/viewer.py` | 浏览相机及场景取景视图，不等于独立 Shot Camera | 待核验 |
| `mini3d/orbit_controller.py` | 环绕、平移、缩放等浏览相机导航状态 | 待核验 |
| `mini3d/camera.py` | 通用相机位姿、投影和几何计算基础 | 待核验 |
| `mini3d/viewport_cache.py` | 视口重复绘制所需的缓存键 / 失效条件 | 待核验 |

## B. Scene、摆放、资源与导入

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/scene.py` | Entity / Mesh / SceneGroup 及共享资源实例的场景模型 | 已抽查 |
| `mini3d/commands.py` | PlacementCommands、Undo/Redo、编辑事务；不能绕开它随意修改可撤销编辑 | 已抽查 |
| `mini3d/placement.py` | 几何表面射线命中与摆放定位 | 待核验 |
| `mini3d/placement_plane.py` | 数学摆放平面，不等于实际渲染地面 | 待核验 |
| `mini3d/surface_drag.py` | 连续贴面拖动的一次交互与提交/取消语义 | 待核验 |
| `mini3d/formation.py` | 阵型生成和阵型位置计算 | 待核验 |
| `mini3d/picking.py` | 鼠标到场景物体的几何拾取 | 待核验 |
| `mini3d/assets.py` | 无 GL 的 Asset 模板/共享实例与格式中立 AssetCache；load 同步加载，adopt 接收后台准备完成的模板 | 已抽查 |
| `mini3d/asset_loader.py` | 单 daemon worker 私有缓存、CPU 模型解析与图像解码；队列 poll 交付结果，取消/关闭屏蔽迟到结果，不接触活动 Scene/History/GL | 已抽查 |
| `mini3d/gltf_loader.py` | glTF/GLB 解码、模型资源缓存（Editor 通过其 AssetCache 使用） | 待核验 |
| `mini3d/stl_loader.py` | ASCII/二进制 STL 到模型网格的导入 | 待核验 |
| `mini3d/urdf_loader.py` | URDF 机器人实体/链接树数据导入 | 待核验 |
| `mini3d/geometry.py` | 基础几何体生成和网格工具 | 待核验 |
| `mini3d/geometry_cache.py` | 网格相关的可复用计算 / 缓存辅助，具体键需核查 | 待核验 |
| `mini3d/roman_assets.py` | 内建罗马街道可编辑模块及其材质和几何生成；不声称是考古复原 | 已抽查 |
| `mini3d/roman_soldier.py` | 内建罗马士兵程序化资产 | 待核验 |
| `mini3d/street.py` | 用可编辑 Roman Assets 构造有限街道与分组布局 | 已抽查 |
| `mini3d/scene_io.py` | 场景文件序列化、读取和版本兼容 | 待核验 |
| `mini3d/scene_snapshot.py` | 场景派生快照、变化检测等中间表示；具体边界待核查 | 待核验 |
| `mini3d/spatial_index.py` | 空间索引原型；当前默认是否启用由代码及配置确认 | 待核验 |

## C. Python 渲染（编辑视口及摄影的 Python 绘制路径）

**按任务进入，不必顺序通读**。当前实际入口和主要边界：

- **Arrange / Editor 可见视口**：`mini3d/editor_runtime.py` 维护渲染循环，经 `mini3d/scene_renderer.py` 选择 Python 或共享 C++ 场景核心；`GLRenderer` 负责 Python 路径及原生帧后的编辑辅助叠层。
- **Python 画面生成**：`GLRenderer` → `render_plan` 组织绘制 → `material_renderer` 与 `shadow_map` 等实际绘制；`scene_snapshot.py` 提供共享的逐帧数据快照。
- **Shot 预览 / PNG**：先查 D 节的 `shot_camera.py`；该路径可能使用 Python `GLRenderer`，也可能通过 `native_renderer.py`（兼容名 `native_photo.py`）转至 F 节共享 C++ 后端，不能仅看最终画面判断后端。
- **跨区域入口**：用户要修改灯光或阴影时，先读 C.3；材质或遮挡看 C.2；天空/IBL 看 C.4；帧缓冲/GL 状态看 C.5；涉及共享 native 核心时追 D.2/F。

### C.1 绘制入口与可见性规划

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/scene_renderer.py` | Arrange / Shot 共用场景绘制入口；选择后端、配置目标尺寸/采样并记录回退，在 auto 回退时运行 Python 绘制 | 已抽查 |
| `mini3d/gl_renderer.py` | Python 绘制顶层入口，协调材质、ShadowMap、RenderPlan、EditorGrid 和兼容几何；也提供 Arrange native 场景帧后的 Python 辅助叠层 | 已抽查 |
| `mini3d/editor_grid.py` | `EditorGrid.draw/close` 绘制覆盖视野的 placement-plane 辅助网格，保持世界坐标轴、格距、场景深度只读和调用方 GL 状态；不参与拾取、放置或 Shot 照片。Arrange native 帧后仍由 GLRenderer 的辅助绘制路径调用；回归见 `tests/editor_grid_gpu_smoke.py`、`tests/test_ground_separation.py` | 已抽查 |
| `mini3d/render_plan.py` | 根据本帧 Scene/Camera 构建颜色可见性、分类和绘制计划 | 已抽查 |

### C.2 材质、着色器与绘制顺序

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/material_renderer.py` | glTF 材质绘制、主线程 GPU 上传和资源复用；可消费带原图 identity 校验的后台 RGBA 解码结果 | 已抽查 |
| `mini3d/material_shaders.py` | Python 绘制路径的 GLSL 着色器源 | 已抽查 |
| `mini3d/draw_order.py` | 绘制顺序辅助；透明与不透明排序行为应查源码 | 已抽查 |

### C.3 阴影与光照

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/shadow_fit.py` | 根据接收体、投影者与相机计算阴影视域 | 已抽查 |
| `mini3d/shadow_map.py` | ShadowMap 生成、资源、缓存和阴影采样配合 | 已抽查 |
| `mini3d/lighting.py` | 方向光与光照设置校验/状态 | 已抽查 |

### C.4 天空、大气、环境和 IBL

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/sky_renderer.py` | 天空绘制 | 已抽查 |
| `mini3d/atmosphere.py` | 摄影大气/天空/地面状态及照片场景准备 | 已抽查 |
| `mini3d/environment.py` | IBL / 环境贴图等环境渲染资源 | 已抽查 |
| `mini3d/hdr.py` | HDR 图像处理辅助 | 已抽查 |
| `mini3d/ibl_filter.py` | IBL 过滤 / 预计算辅助 | 已抽查 |

### C.5 目标缓冲、GL 状态与辅助后端

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/render_target.py` | 离屏帧缓冲、尺寸、抗锯齿及颜色/深度附件生命周期 | 已抽查 |
| `mini3d/gl_state.py` | OpenGL 上下文状态的保存、恢复与读取辅助 | 已抽查 |
| `mini3d/headless_gl.py` | 无可见窗口的 OpenGL 环境辅助 | 已抽查 |
| `mini3d/cpu_renderer.py` | CPU 绘制及参考用途；不要与正式 GPU 后端混淆 | 已抽查 |
| `mini3d/math3d.py` | 通用三维数学辅助，不等于 Scene 的所有坐标契约 | 已抽查 |

**共享但登记在其他分类**：`mini3d/scene.py`（场景所有权）、`mini3d/scene_snapshot.py`（派生帧数据）、`mini3d/geometry_cache.py`（网格派生缓存）、`mini3d/viewport_cache.py`（视口重新绘制决策）、`mini3d/camera.py`（相机投影）；不要为渲染而重复登记这些文件。

## D. 摄影流程与原生桥接

摄影是**使用渲染能力的上层任务流程**，不等于另一份独立的完整渲染器。需要先从 `shot_camera.py` 看预览/照片如何选择实际后端。

### D.1 Shot 相机、对焦和后处理

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/shot_camera.py` | 独立 Shot Camera 参数、摄影场景准备、照片色彩/景深和 PNG 流程；场景帧交给共享入口选择 GL/native 后端，Shot 不直接调用场景 renderer | 已抽查 |
| `mini3d/depth_of_field.py` | 摄影景深计算/后处理 | 已抽查 |
| `mini3d/photo_focus.py` | Camera View 点击深度对焦与焦点定位辅助 | 已抽查 |
| `mini3d/photo_color.py` | 色温白平衡、照片色彩预设校验/应用 | 已抽查 |
| `mini3d/photo_environment.py` | 摄影环境数据与辅助处理 | 已抽查 |

### D.2 Python 与 native 绘制边界

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/native_renderer.py` | Arrange / Shot 共用 native renderer 生命周期、后端选择、bundle/globals 同步、live 纹理借用、实体批量变换和 GL 状态保护；prepare_step 在原线程/context 逐帧准备资源，资源变化/关闭取消部分初始化，交互按时间预算推进廉价阶段 | 已抽查 |
| `mini3d/native_photo.py` | 兼容 re-export：将既有 Shot 导入名映射到 `native_renderer.py` | 已抽查 |
| `mini3d/native_photo_bundle.py` | 将 Arrange / Shot 活动场景及参数同步至 native bundle；在线 v2 记录借用纹理 handle 和实体索引映射，离线 v1 仍导出像素；自身不绘帧 | 已抽查 |
| `native/export_scene.py` | Python 向共享 native 核心导出场景、材质与共享资源的底层转换逻辑 | 待核验 |

**live 与离线导出边界不能混淆**：`mini3d/native_photo_bundle.py` 面向已打开编辑器的 Arrange / Shot live bundle；`native/export_scene.py` 同时提供其复用的底层转换辅助与离线场景/参考采集入口。逐帧绘制通过 `scene_renderer` / `native_renderer` 调用 DLL，不由导出器绘帧。

## E. AI API 与本地通信

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `mini3d/api.py` | 无 UI 的场景/编辑/拍照 API，借用同一 Editor / Commands；拍照需调用者 GL context | 已抽查 |
| `mini3d/api_dispatch.py` | JSON 命令白名单和参数校验分发 | 待核验 |
| `mini3d/editor_ipc.py` | 活动 Editor 的本地 IPC 接收与主线程交付 | 待核验 |
| `mini3d/ipc_client.py` | 外部发现/调用本地 Editor IPC 的客户端入口 | 待核验 |

## F. C++20 原生核心（`spqr-native/src/`）

**仅在需要 Arrange / Shot 原生绘制、构建、原生阴影或跨语言契约时深入**。以下条目省略的共同前缀均为 `spqr-native/src/`；原生 DLL 的调用者位于 D.2 节。

### F.1 原生输入数据与编辑器接口

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `bundle.cpp` / `bundle.hpp` | 解析离线 v1 像素纹理和仅允许 shared-context API 读取的 live v2 借用 handle；组织原生网格/材质/纹理/实体 | 待核验 |
| `native_photo.cpp` / `native_photo.h` | 编辑器调用的共享 Arrange / Shot DLL C 接口；ABI v1 保留同步 create/create_shared 与 transforms；可选 begin_shared/prepare_step 在创建线程/context 逐步初始化，未就绪拒绝绘制/更新，可销毁部分资源；可选 program_compile_count 提供当前 handle 的实际程序编译数 | 待核验 |

### F.2 原生 OpenGL 绘制与阴影视域

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `renderer.cpp` / `renderer.hpp` | C++ 绘制核心、颜色/阴影、实例化及 GL 资源；同步或分阶段初始化，按 context/完整源码弱缓存共享 shader program，逐程序编译/逐网格上传并隔离共享 uniform 状态；仅存在摄影地面实体时编译地面程序；借用纹理不转移所有权，批量变换提交后失效阴影缓存 | 待核验 |
| `shadow_fit.cpp` / `shadow_fit.hpp` | 原生视锥、接收体/投影者与阴影视域拟合 | 已抽查 |

### F.3 OpenGL 函数加载、平台及独立查看器

| 文件 | 具体职责与界限 | 状态 |
| --- | --- | --- |
| `gl_api.cpp` / `gl_api.hpp` | 原生 OpenGL API 加载及相关约束 | 已抽查 |
| `platform_win32.cpp` / `platform_win32.hpp` | Windows/WGL 平台窗口与上下文 | 已抽查 |
| `main.cpp` | 独立查看器/基准命令行入口，不等于 Python 编辑器 | 已抽查 |

**注意**：`native_photo.cpp` 是 Python 编辑器借用现有 GL 上下文的 Arrange / Shot 共享原生接口；`main.cpp` 是独立可执行程序的入口。它们不等价。修改 native 结构/字段时须同时核查 `mini3d/native_photo_bundle.py`、`spqr-native/FORMAT.md` 和相关测试。

## G. 测试、工具与辅助材料（待逐项核对）

- `tests/test_*.py`：unittest 单元回归。选择和改动模块相关的具体测试；跨共享契约修改后扩大验证。
- `tests/*smoke.py` 及专用验收脚本：桌面 OpenGL、Shot、UI、保存载入和 GPU 实测，不等同于单测。
- `tests/*benchmark*.py` / `tests/*performance*.py`：基准脚本；确认设备、后端、采样参数与全帧口径。
- `spqr-native/tests/`：C++ / native 库功能、数值及 GPU 验收。
- `tools/` 与 `spqr-native/tools/`：运行、构建、导出、生成素材与验证辅助；不能无检查地当生产入口。
- `docs/`：规范、历史报告、实验数据、照片混合存放。是否删减先调查链接、复现依赖、许可证及使用情况。

## H. 发生跨模块修改时必须核实的契约

| 共享契约 | 主要关注者 |
| --- | --- |
| 实体 ID、变换、历史、Scene v3 | Scene / Commands / scene_io / UI / API / native_renderer / native transform API |
| Camera pose、焦距、near/far 与点击对焦 | camera / shot_camera / scene_renderer / native_renderer / photo_focus / native bundle |
| Python → C++ bundle 字段、live 纹理借用和共享网格 | native_photo_bundle / native_renderer / native/export_scene / bundle / native_photo |
| ShadowMap 投影和缓存 | shadow_fit / shadow_map / native shadow_fit / native renderer；实体批量变换会使原生阴影缓存失效 |
| GL FBO、状态、资源释放 | scene_renderer / gl_renderer / render_target / gl_state / native_renderer；借用纹理必须存活到 native handle 销毁 |
| Arrange 与 Shot 的后端策略 / 回退诊断 | scene_renderer / native_renderer / editor_runtime / shot_camera |
| 同场景 API/UI 修改和照片一致性 | editor / editor_ui / api / editor_ipc / shot_camera / scene_renderer |

阅读后仍须打开拟修改的真实脚本，核查接口与调用者。`已抽查` 不代表完整审计，`待核验` 不等于不存在或不可使用。
