# V2 测试覆盖与冗余审计

基线：正式 `main` / `v2.0.0`，`2de85ed7e30c63ea86be4f8ec8a201a8b356621a`。
整理前采用刚完成的根目录完整发布实测：277项单测、37组执行器入口、26张Q1/Q2字节一致、三场景Blender像素一致。原始实测输出保持在本机，公开发布记录见 [V2验证](V2-VALIDATION.md)。
另固化77个脚本的SHA-256、全部277个单测ID、逐条断言表达式、CLI/资产输入和源代码/文档调用者：[机器清单](testing/v2-engineering/coverage-before.json)。该清单是基线，不会改成整理后版本。
调用者扫描同时包含历史文档，不能据此认定仍有自动执行；`validate_v2`中的动态smoke列表也已核对。AST中相同函数体只是候选，不证明外层state、相机、尺寸或资源相同。没有发现可直接删除的重复单测文件。

## 重复关系及边界

| 测试组 | 核实结果 | 处理 |
| --- | --- | --- |
| Placement V1/V2 | 同四资产，但V1 table×40、native扫描尺度；V2 table×3及米尺度、多选/编组/阵型/事务。SDL center/asset_drag/events/drop_asset部分函数体相同，依赖各自闭包state | 两套输入、全部断言保持；不合并成一个流程 |
| Picking / Placement triangle | 一个返回Mesh，另一个返回Entity(Mesh)；命中与摆放目标不同 | 保持，不按名称合并 |
| Editor / Gizmo / UI | 单测模拟输入/历史；integration真实ImGui拖入和Inspector；file_dialog真实异步Tk生命周期；81条摄影UI检查覆盖跨面板释放#5 | 保持互补回归；简单构造器相同不能替代不同事件序列 |
| Lighting / Shadow | CPU方向/API原子验证、GPU像素、UI输入、独立ray/depth oracle各不相同；sample/probe函数体相同但捕获各自SIZE/camera | 保持各层断言；复用现有lighting_fixture，不统一GL flags或readback状态 |
| Photography | photo_smoke真实控件/FBO；persistence新进程PNG；MSAA resolve/depth/stencil/独立READ-DRAW FBO；同窗口API共享Undo | 保持，不能互相替代 |
| AI API | Python实体合同、JSON白名单/事务、40人真实PNG、无GL摄影状态流程、同Editor绑定 | 保持各自输入与错误路径 |
| rome_visibility_smoke | 只调用ground_separation的run+run_editor，无断言；当前run_editor已由ground脚本CLI调用 | 删除转发；旧偏移实验在Git bd41b2b及原图中追溯 |
| stabilization_regressions | 13组均为当前core的子集；旧baseline还依赖已解除的固定Worktree | 删除重复执行器；统一core生成1033e5e快照，保留同参数/全部断言 |
| Photographer fixture | Q1/Q2、运动与性能基准import整个photographer_session，只需要asset几何导出 | 将原asset函数原样抽为photography_fixture；手动程序移入research，字节级资产/PNG验证 |
| 两个摄影Scene启动器 | 相同load_scene/set_camera_view/Editor.run，无自动断言，只默认输入文件夹不同 | 合并为research/open_scene.py，显式Scene输入；两套Scene分别实测 |
| CPU/GPU性能 | cache基准、Shadow Fit paired timing、Placement 1/40/100观察回答不同问题 | 迁benchmarks，不删算法oracle、计时或GPU断言 |

## 逐文件审计（77份基线源文件）

下表提供目标、执行入口与拟处理；输入、每条独有断言、测试方法及全部主要调用者详见机器清单。`断言处`为源代码assert/assert*或check调用处计数，不是运行时检查次数；参数循环与报告checks会扩展检查数量。

| 基线文件 | 实际目标 | 执行入口 | 方法/断言处 | 处理 |
| --- | --- | --- | --- | --- |
| `tests/ai_api_smoke.py` | API-only Roman 5x8 -> transform -> save/reload -> 50mm 16:9 PNG -> state. | validate_v2 direct/delegated | 0 / 14 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/api_photography_workflow_20261010.py` | Photographer's arrangement/API round trip; no external assets or GL required. | validate_v2 direct/delegated | 0 / 12 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/audit_placement_20261010.py` | Repeatable composition workflow audit using only the tracked STL cube. | direct CLI / helper import | 4 / 34 | 额外4项组合工作流回归；保留直接入口 |
| `tests/audit_shadow_precision_20261010.py` | Controlled render: only ground span and shadow resolution vary. | direct CLI / helper import | 0 / 0 | 研究/摄影采集；迁至 research/ |
| `tests/consolidation_gpu_regression.py` | Real GPU regressions for export isolation, clean shots and failed startup. | validate_v2 direct/delegated | 0 / 2 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/demo_equivalence.py` | Compare legacy entry frames against a Git revision with fixed frame timing. | validate_v2 direct/delegated | 0 / 1 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/editor_integration_smoke.py` | Drive actual ImGui drag/drop, picking, gizmo and Inspector through editor_app. | validate_v2 direct/delegated | 0 / 20 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/editor_smoke.py` | Exercise the actual editor/ImGui/OpenGL loop in a hidden desktop window. | validate_v2 direct/delegated | 0 / 21 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/file_dialog_smoke.py` | Real Tk picker + hidden OpenGL editor: pending, cancel, reopen, quit. | validate_v2 direct/delegated | 0 / 13 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/ground_separation_smoke.py` | Real GL image/depth comparisons, placement and actual Editor validation. | validate_v2 direct/delegated | 0 / 24 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/ibl_gpu_regression.py` | IBL enabled: alpha/Unlit, first-upload GL state, offscreen shadows and lifetime. | validate_v2 direct/delegated | 0 / 12 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/ibl_quality_q1.py` | Real Mini3D A/B PNGs and GL regressions. Uses local licensed glTF assets. | validate_v2 direct/delegated | 0 / 16 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/lighting_api_smoke.py` | Lighting V1 end-to-end acceptance on desktop OpenGL, using public AI APIs. | validate_v2 direct/delegated | 0 / 18 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/lighting_fixture.py` | Original, self-contained glTF PBR cube for directional-light acceptance. | direct CLI / helper import | 0 / 0 | 共享 PBR Fixture；保持 |
| `tests/lighting_smoke.py` | Real GPU acceptance. --baseline captures the unchanged renderer before edits. | validate_v2 direct/delegated | 0 / 11 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/lighting_ui_smoke.py` | Exercise real ImGui lighting inputs through SDL mouse/keyboard events. | validate_v2 direct/delegated | 0 / 12 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/open_assets_shadow_audit_20261010.py` | Downloaded CC0 House + CC-BY CesiumMan: CPU, Shot, motion and persistence. | direct CLI / helper import | 0 / 14 | 研究/摄影采集；迁至 research/ |
| `tests/open_photographer_session.py` | Open one of the saved photographic setups in the existing Mini3D Editor. | direct CLI / helper import | 0 / 0 | 手动 Scene 启动；合并为 research/open_scene.py |
| `tests/open_second_session.py` | Open the still-life photographs as editable Mini3D scenes. | direct CLI / helper import | 0 / 0 | 手动 Scene 启动；合并为 research/open_scene.py |
| `tests/photo_smoke.py` | Exercise the real photo buttons and compare PNGs with the preview FBO. | validate_v2 direct/delegated | 0 / 19 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/photographer_session.py` | An original Mini3D photography session. Run from any directory; no downloaded models. | direct CLI / helper import | 0 / 2 | 研究/摄影采集；迁至 research/ |
| `tests/photographer_session_two.py` | A second practical shoot: still life, occlusion, light, and scale changes. | direct CLI / helper import | 0 / 6 | 研究/摄影采集；迁至 research/ |
| `tests/placement_smoke.py` | Visible SDL/ImGui acceptance run using the locally supplied four real assets. | validate_v2 direct/delegated | 0 / 52 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/placement_v2_performance.py` | Measure real Editor/OpenGL Roman 1/40/100 cases; no optimization or downloads. | direct CLI / helper import | 0 / 15 | 性能/配对基准；迁至 benchmarks/；统一执行器调用保持 |
| `tests/placement_v2_smoke.py` | Visible V2 acceptance with real assets, SDL input and actual ImGui widgets. | validate_v2 direct/delegated | 0 / 63 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/render_quality_v1.py` | Repeatable original-geometry and local PBR photography, with real GPU timing. | direct CLI / helper import | 0 / 10 | 研究/摄影采集；迁至 research/ |
| `tests/render_smoke.py` | Run all real demo loops in hidden OpenGL windows, with navigation events. | direct CLI / helper import | 0 / 4 | 兼容示例循环/导航 Fixture；demo_equivalence 调用；保持 |
| `tests/renderer_v2_cpu_cache_benchmark.py` | Paired f36a0ff/current CPU timings and real-asset GL correctness evidence. | validate_v2 direct/delegated | 0 / 24 | 性能/配对基准；迁至 benchmarks/；统一执行器调用保持 |
| `tests/renderer_v2_smoke.py` | Real desktop OpenGL, paired V1/V2 PNG and timing evidence. No downloads. | validate_v2 direct/delegated | 0 / 12 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/rome_added_models_smoke.py` | Issue #4 supplementary local assets and existing 2048 setting; no conversions. | validate_v2 direct/delegated | 0 / 2 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/rome_integration_smoke.py` | Issue #4: real Rome placement/rendering/photography/JSON API acceptance. | validate_v2 direct/delegated | 0 / 23 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/rome_integration_ui_smoke.py` | Actual Editor/Camera View screenshots for Issue #4's saved Roman scene. | validate_v2 direct/delegated | 0 / 2 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/rome_visibility_smoke.py` | Compatibility entry for the Ground separation regression. | direct CLI / helper import | 0 / 0 | 无独有断言的转发；删除，ground_separation_smoke.py 继承 |
| `tests/scene_clipping_smoke.py` | Issue #3 GPU evidence, written before the fix. --baseline expects clipping. | validate_v2 direct/delegated | 0 / 7 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/shadow_assets_smoke.py` | Real library assets: GPU shadows, independent triangle rays and depth checks. | validate_v2 direct/delegated | 0 / 10 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/shadow_fit_performance_20261010.py` | Separate CPU fit scaling from synchronized real Rome+40 Shot rendering. | validate_v2 direct/delegated | 0 / 2 | 性能/配对基准；迁至 benchmarks/；统一执行器调用保持 |
| `tests/shadow_motion_audit_20261010.py` | Temporal Shot shadow audit: fixed world probes, actual depth maps, locked-fit control. | validate_v2 direct/delegated | 0 / 5 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/shadow_smoke.py` | Real GPU directional shadows. --baseline uses isolated 1033e5e checkout. | validate_v2 direct/delegated | 0 / 34 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/shadow_ui_smoke.py` | Real Editor checkbox -> live scene shadow preview (SDL/ImGui, GPU). | validate_v2 direct/delegated | 0 / 4 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/shot_camera_persistence_smoke.py` | Compare real PNG output across process restart without recreating the shot. | validate_v2 direct/delegated | 0 / 9 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/shot_msaa_smoke.py` | Real GPU FBO resolve, depth/stencil, resize, lifetime and Shot PNG parity. | validate_v2 direct/delegated | 0 / 24 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/stabilization_regressions.py` | Sequential real GPU regressions; generated PNGs stay in ignored captures. | direct CLI / helper import | 0 / 0 | 旧执行器；删除，validate_v2 core 继承全部13项 |
| `tests/stl_render_smoke.py` | Render a real STL through the editor in all three material modes. | validate_v2 direct/delegated | 0 / 2 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/test_api.py` | API works without an Editor UI or OpenGL context; results are detached data. | unittest discover; validate_v2 core/all | 8 / 51 | 长期单测；原文件保持 |
| `tests/test_api_binding.py` | API binding must share the editor's existing state and history. | unittest discover; validate_v2 core/all | 1 / 8 | 长期单测；原文件保持 |
| `tests/test_api_dispatch.py` | JSON whitelist, structured errors and atomic command batches. | unittest discover; validate_v2 core/all | 6 / 18 | 长期单测；原文件保持 |
| `tests/test_camera.py` | Camera navigation regressions; run without an OpenGL window. | unittest discover; validate_v2 core/all | 24 / 75 | 长期单测；原文件保持 |
| `tests/test_commands.py` | Placement API history is atomic and never copies shared rendering resources. | unittest discover; validate_v2 core/all | 13 / 79 | 长期单测；原文件保持 |
| `tests/test_editor.py` | Headless editor behavior: instance lifecycle, persistence and viewport tools. | unittest discover; validate_v2 core/all | 24 / 96 | 长期单测；原文件保持 |
| `tests/test_environment.py` | Fixed IBL resource conventions and API/persistence regression (no GL required). | unittest discover; validate_v2 core/all | 3 / 18 | 长期单测；原文件保持 |
| `tests/test_examples.py` | Legacy demo semantics must survive moving and sharing their scene types. | unittest discover; validate_v2 core/all | 5 / 10 | 长期单测；原文件保持 |
| `tests/test_formation.py` | Rectangular formation identity, resource sharing, atomicity and yaw rules. | unittest discover; validate_v2 core/all | 9 / 54 | 长期单测；原文件保持 |
| `tests/test_gltf_loader.py` | Importer regression tests: layout, coordinates, sharing and real assets. | unittest discover; validate_v2 core/all | 11 / 34 | 长期单测；原文件保持 |
| `tests/test_ground_separation.py` | Scene geometry, display guides and placement queries have separate lifetimes. | unittest discover; validate_v2 core/all | 6 / 32 | 长期单测；原文件保持 |
| `tests/test_lighting.py` | Lighting contract tests without a GL context; GPU pixels: lighting_smoke.py. | unittest discover; validate_v2 core/all | 8 / 32 | 长期单测；原文件保持 |
| `tests/test_lighting_api.py` | Lighting V1: public API, dispatcher, atomic validation and v3 persistence. | unittest discover; validate_v2 core/all | 11 / 42 | 长期单测；原文件保持 |
| `tests/test_model_dialog.py` | File-picker lifecycle and asynchronous import behavior. | unittest discover; validate_v2 core/all | 8 / 30 | 长期单测；原文件保持 |
| `tests/test_multi_gizmo.py` | Multi Gizmo drives shared command deltas about the selection centre. | unittest discover; validate_v2 core/all | 9 / 38 | 长期单测；原文件保持 |
| `tests/test_picking.py` | Exact selection stays correct across viewport offsets and scene transforms. | unittest discover; validate_v2 core/all | 12 / 28 | 长期单测；原文件保持 |
| `tests/test_placement.py` | Placement rules use actual geometry, independent of OpenGL and Editor UI. | unittest discover; validate_v2 core/all | 10 / 46 | 长期单测；原文件保持 |
| `tests/test_placement_assets.py` | Acceptance geometry using local assets; missing optional assets skip cleanly. | unittest discover; validate_v2 core/all | 2 / 15 | 长期单测；原文件保持 |
| `tests/test_placement_editor.py` | Placement editor integration and atomic persistence, without an OpenGL window. | unittest discover; validate_v2 core/all | 12 / 78 | 长期单测；原文件保持 |
| `tests/test_placement_gizmo.py` | Gizmo command transactions and world/local behavior, without a GL window. | unittest discover; validate_v2 core/all | 7 / 24 | 长期单测；原文件保持 |
| `tests/test_placement_v2_commands.py` | Selection, group and multi-transform contracts without an Editor or GL context. | unittest discover; validate_v2 core/all | 13 / 74 | 长期单测；原文件保持 |
| `tests/test_placement_v2_editor.py` | Placement V2 editor input and scene-format integration, without a GL window. | unittest discover; validate_v2 core/all | 10 / 68 | 长期单测；原文件保持 |
| `tests/test_render_plan.py` | CPU visibility checks, independent eight-corner support oracle and mutations. | unittest discover; validate_v2 core/all | 11 / 30 | 长期单测；原文件保持 |
| `tests/test_scene_clipping.py` | Issue #3: framing a small object must not clip the rest of the scene. | unittest discover; validate_v2 core/all | 8 / 30 | 长期单测；原文件保持 |
| `tests/test_shadow_camera_fit.py` | Independent convex-intersection reference and directional-caster coverage. | unittest discover; validate_v2 core/all | 8 / 17 | 长期单测；原文件保持 |
| `tests/test_shadow_fit_batch.py` | Batched early-outs against the original scalar exact-intersection oracle. | unittest discover; validate_v2 core/all | 4 / 4 | 长期单测；原文件保持 |
| `tests/test_shadows.py` | Directional shadow projection and public controls, without a GL context. | unittest discover; validate_v2 core/all | 5 / 17 | 长期单测；原文件保持 |
| `tests/test_shot_antialiasing.py` | Shot AA API validation and backward-compatible Scene v3 persistence. | unittest discover; validate_v2 core/all | 2 / 10 | 长期单测；原文件保持 |
| `tests/test_shot_camera.py` | test_copy_pose_and_lens_are_independent; test_focal_presets_and_aspects_preserve_pose_and_focal_length; test_fit_rect_centers_and_never_exceeds_available_viewport; test_editor_navigation_and_photo_preview_do_not_move_shot; test_capture_and_camera_view_require_explicit_camera_creation | unittest discover; validate_v2 core/all | 5 / 20 | 长期单测；原文件保持 |
| `tests/test_shot_camera_persistence.py` | Scene v3 photography persistence, strict input validation and atomic load. | unittest discover; validate_v2 core/all | 10 / 44 | 长期单测；原文件保持 |
| `tests/test_stl_loader.py` | STL import, hard edges and editor persistence without an OpenGL window. | unittest discover; validate_v2 core/all | 4 / 15 | 长期单测；原文件保持 |
| `tests/test_surface_drag.py` | Real ray/triangle surface gestures, without a rendering context. | unittest discover; validate_v2 core/all | 8 / 29 | 长期单测；原文件保持 |
| `tests/ui_photography_journey_20261010.py` | Actual ImGui/GL event-loop journeys: drag ownership, photo isolation, scene changes. | validate_v2 direct/delegated | 0 / 33 | 长期 GPU/UI/API 回归；独有断言保持 |
| `tests/unified_api_ui_smoke.py` | Actual single Editor window: JSON API edits, UI history, Shot and PNG. | validate_v2 direct/delegated | 0 / 5 | 长期 GPU/UI/API 回归；独有断言保持 |

## 小批次实施与回退

1. 固化覆盖/输入/断言、277测试身份及本机资料精确哈希，不改测试或原资料。
2. 抽摄影Fixture、去掉两个确认冗余入口。全部277单测及37组统一执行器验收；导出Fixture原函数AST和字节相同，原Q1/Q2/影子运动保持。单独提交，revert该提交即可回退。
3. 将研究采集/性能基准移入各自目录，合并两个手动启动器；仅改必要ROOT/导入/CLI输出入口和validate内部路径。重新完整37组、直接CLI、额外4项composition回归及原始证据哈希；补文档索引和本机输出分类。单独提交，可独立revert。

不引入运行时依赖，不改mini3d/、场景格式、生产接口、验收阈值。阶段2/3各自先测试再提交。

## 文档与本机资料原则

当前权威入口集中在docs/README.md；V1/Q1/Q2及缺陷前后资料是带版本的实验事实，不作为重复指南合并。Q1/Q2原图/.blend/HDR、Rome证据、失败前后图片及所有许可证保持原位。
本机ignored captures/archives全文件清单及361组初始精确内容重复仅存在本机忽略目录；绝对路径、资产私人清单不提交。像素相似不算重复。相同字节可能分别代表对照/新图/多次独立运行，保留其上下文。未确认用户独有原始数据的删除，本轮保持不变。
