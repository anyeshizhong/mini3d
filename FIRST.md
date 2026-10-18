# FIRST.md — Mini3D AI 工作总入口

> 适用：在本仓库工作的主 Agent 与其协调的子 Agent。
> 本文件是**任务分流入口**，不是全部技术文档，也不能替代用户要求、实际源代码或测试。
> 核心原则：**具体、分类、操作**。

## 0. 唯一对外接口：主 Agent

用户只需要用自然语言描述目标、问题或现象，**不必**指定模块、脚本、负责人、测试项目或修改步骤。
主 Agent 负责将需求转为可验证的目标，查找模块归属、判断影响范围、分配工作、集成结果并向用户交付。
可以内部按模块分工，但不得将内部协调义务转嫁给用户。只有确实缺少决定性条件且无法合理调查时，才提出简短澄清问题。

## 1. 三条规则

1. **具体（登记）**：每个生产脚本应登记准确路径、职责、对外接口、上游输入、下游影响及对应测试。首先查 `docs/ai/FILE_REGISTRY.md` 中相关分类，再读对应源文件。登记未核实时，不得根据文件名猜测代码行为；先核查源码，随后修订登记。
2. **分类（最小阅读）**：只加载当前任务所需的规范、脚本及测试。不要每次通读所有 `docs/`、`tests/` 或旧版审计资料。分类不是职责壁垒，跨模块问题由主 Agent 协调。
3. **操作（可执行）**：找到适用的操作规程，先明确验收结果，再实施最小合理变更、验证并回写登记。详见 `docs/ai/OPERATIONS.md`。

## 2. 收到用户任务后的执行流程

1. **识别目标**：把用户的自然语言转为要达到的可观察结果（例如“镜头平移时建筑阴影不跳”）。不要要求用户先懂渲染、Python 或 C++。
2. **检查现场**：确认当前分支、最近提交、工作区是否存在未提交改动、运行入口、是否使用 Python/native 后端。保护用户原有改动；未检查前禁止清理、覆盖或重置。
3. **任务分类**：按下表选主要领域，可有次要领域。先打开该领域的登记段落与操作规程。
4. **确定责任和边界**：列出拟修改脚本、其上游输入、下游调用者与必须一起验收的接口。单一局部 Bug 尽量局部处理；多文件修改可以合理，但必须说明为何跨越边界。
5. **定位证据**：读真正涉及的源代码、相应测试、实际复现场景；历史文档只是线索。禁止把旧报告当成当前版本已通过的新测试。
6. **执行与验收**：使用 `docs/ai/OPERATIONS.md` 对应规程；不降低画质、不偷偷回退 backend、不削弱断言。
7. **交付与回写**：报告改了什么、在哪个分支/提交、运行了哪些测试、哪些没验证、剩余风险；当脚本职责或公共接口改变时同步更新登记。

## 3. 分类索引（按任务读取，不必全部读取）

| 用户描述的任务 | 首先调查的代码区域 | 优先参考规范/说明 |
| --- | --- | --- |
| 按钮、面板、快捷键、视口操作 | `mini3d/editor_ui.py`、`editor.py`、`editor_runtime.py`、`editor_tools.py` | `docs/editor-ui-workspaces.md`、`docs/ARCHITECTURE.md` |
| 摆放、变换、撤销、编组、阵型 | `mini3d/commands.py`、`placement.py`、`scene.py`、`formation.py` | `docs/placement-v2.md` |
| 摄影、对焦、曝光、景深、PNG | `mini3d/shot_camera.py`、`photo_focus.py`、`depth_of_field.py`、`photo_color.py` | `docs/photo-workflow.md`、`NATIVE-PHOTO.md` |
| 照片后端、Python/C++ 衔接 | `mini3d/native_photo.py`、`native_photo_bundle.py`、`spqr-native/src/native_photo.cpp` | `NATIVE-PHOTO.md`、`docs/SPQR-NATIVE-VALIDATION.md` |
| 模型、材质、GLB/STL/URDF 导入 | `mini3d/gltf_loader.py`、`stl_loader.py`、`urdf_loader.py`、`material_renderer.py` | `model/README.md`、`docs/ARCHITECTURE.md` |
| 阴影、光照、天空、地平线 | `mini3d/shadow_fit.py`、`shadow_map.py`、`atmosphere.py`、`sky_renderer.py`、`spqr-native/src/shadow_fit.cpp` | `docs/SPQR-SHADOW-STABILITY.md`、`docs/SPQR-GROUND-CONTINUITY.md` |
| 渲染性能、裁剪、资源复用 | `mini3d/gl_renderer.py`、`render_plan.py`、`material_renderer.py`、`spqr-native/src/renderer.cpp` | `docs/SPQR-PERFORMANCE.md`、`docs/SPQR-ENGINE-OPTIMIZATION.md` |
| 罗马建筑、街道、Pompeii | `mini3d/roman_assets.py`、`street.py`、`tools/build_pompeii.py` | `docs/SPQR-POMPEII.md`、`docs/SPQR-MASONRY-INTEGRITY.md` |
| AI 控制、IPC、外部自动化 | `mini3d/api.py`、`api_dispatch.py`、`editor_ipc.py`、`ipc_client.py` | `docs/ai-api-v1.md`、`docs/ai-view-api.md`、`docs/live-editor-ipc.md` |
| 测试、性能验收、历史材料整理 | `tests/`、`tools/`、`docs/` | `docs/V2-VALIDATION.md`、`docs/SPQR-NATIVE-VALIDATION.md` |

具体脚本级索引：`docs/ai/FILE_REGISTRY.md`。
修改步骤与验收：`docs/ai/OPERATIONS.md`。
整体背景：`readme.md` 与 `docs/ARCHITECTURE.md`。其中 V2 架构文档含历史内容，当前实现以本分支源代码为准。

## 4. 跨部门协作条件

只要改动影响以下任何**共享契约**，主 Agent 应调查上游和下游并安排相应测试：

- `Scene` / `Entity`、实体 ID、事务 / Undo 或 Scene v3 存档；
- Editor UI ↔ Editor 状态 ↔ AI API / IPC 的同一份场景状态；
- Shot Camera、预览、真实深度、景深与 PNG 输出的一致性；
- Python ↔ native bundle / DLL 的字段、资源、投影与阴影约定；
- 绘制缓存、GL 状态、Shader 接口及 GPU 资源所有权。

不要求“一个 AI 永远只改一个文件”。责任划分用来降低误改和阅读成本，不妨碍必要的跨文件修复。主 Agent 对集成结果负责。

## 5. 当前项目不能忽略的事实

- 统一入口：`python -B -m mini3d`；另见 `editor_app.py` 和 `mini3d/__main__.py`。
- Python 继续承载 Editor / Arrange、AI API 和摄影交互；C++20 已接入 Shot 原生绘制，并非完整原生编辑器。
- 原生后端可回退到 Python；当用户要求验证原生修复时应强制 native 并核验实际后端，不能静默回退。
- 完整编辑器稳定 30 FPS 仍须在指定硬件/分辨率/场景/画质下单独验证；历史 P95 成绩不足以保证每帧都低于 33.33 ms。
- 不擅自改变已成立的照片画质、渲染表现、撤销语义、导入兼容性及用户资产。不要把开发中的历史分支当作唯一事实来源。

## 6. 文件现状登记与同步维护

- `FIRST.md` 负责任务入口和分类指路，不记录软件改动历史。
- `docs/ai/FILE_REGISTRY.md` 负责登记**目前实际存在**的每一个脚本及其**当前职责**。不写新增功能、修改时间、合并经过或版本流水账。
- 新建脚本就登记现行职责；删除则删条目；合并则留下合并后的文件并删掉原有文件条目；拆分、重命名亦按现状改写。
- 修改现有脚本时，如果职责/公共接口未变，则登记无需变化；如果影响登记内容，与代码在**同一次任务/PR** 同步更新。
- 主 Agent 检查路径、调用者、测试和分类索引是否仍有效。开发前先读相关登记，开发后校正登记。
- `docs/ai/OPERATIONS.md` 负责操作规程。历史改动由 Git/PR 保存，实验结果与性能数据由独立报告保存。
- 登记若和源代码不符，核验源码后直接修正现状，不追记经过。

**交付标准：用户自然语言需求 → 主 Agent 分类 → 定位必要源文件 → 修改 → 验收 → 同步现状表。**
