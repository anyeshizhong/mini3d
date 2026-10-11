# Mini3D V2 统一功能清单

正式候选分支：`refactor/v2-consolidation`，开发起点Q2 `efd5ddc`，包含审计`c198546`。
3+1指 **Placement、Rendering、Photography、AI API**。四者共用同一个程序和Scene。
状态：代码与历史已核实；整合后的最终验证结果在本轮回归完成后补齐。

| 既有能力 | 来源/实现 | 回归入口 |
| --- | --- | --- |
| GLB/glTF、ASCII/binary STL、大小写扩展名、原生异步文件选择、路径导入 | AssetCache/loaders/ModelFileDialog，早期editor→Q2 | test_gltf_loader/test_stl_loader/test_model_dialog、file_dialog/stl/editor smoke |
| 共享mesh实例、导入层级、Z-up转换、静态默认skin、材质/贴图 | gltf_loader/Scene | gltf_loader、placement_assets、Q1/Q2原模型 |
| 点击拾取、锁定、隐藏、Inspector、世界/局部Move/Rotate/Scale Gizmo、多选 | Editor/Gizmo/picking | editor、placement_editor、multi_gizmo、editor_integration |
| Surface placement、pivot/bounds_bottom、keep_upright、真实surface与有限查询plane | Placement V1/V2 | placement/assets/editor/surface_drag、placement smoke |
| spawn/duplicate/delete、分组/解组/命名、矩形阵型、批量变换 | Commands/formation/SceneGroup | commands/formation/placement_v2_commands、placement_v2 smoke |
| Undo/Redo、连续手势一次历史、Esc回滚、跨面板/失焦/模态输入 | Commands与Gizmo修复406d697 | placement_gizmo、surface_drag、UI photography journey |
| JSON v1/v2/v3载入、v3保存、稳定ID/组/选择/plane/metadata | Editor持久化 | editor/commands/ground/placement/API roundtrip |
| Focus、Frame all、orbit/pan/zoom、标准视图、resize、全场景clip | Camera/Viewer/Orbit，1033e5e | camera/scene_clipping、render/editor smoke |
| Grid辅助线、真实Ground、查询PlacementPlane分离 | faa0a52及前置修复 | ground_separation、photo smoke |
| 普通几何与STL REALISTIC/TOON/OUTLINE，旧URDF/基础示例 | GLRenderer legacy、urdf_loader | render_smoke、stl_render_smoke |
| PBR、Lit/Unlit/Wireframe、KHR_materials_unlit、贴图、vertex color | MaterialRenderer | lighting、renderer_v2、ibl_gpu、Q1/Q2 |
| OPAQUE/MASK/BLEND、alpha cutoff、doubleSided、负scale绕序 | MaterialRenderer/ShadowMap | ibl_gpu_regression、renderer_v2_smoke |
| Studio/Scene、世界方向灯、ambient/diffuse、原子校验和持久化 | 48e8912/efb3852 | lighting/API/UI及摄影回归 |
| 单方向ShadowMap、bias/PCF、MASK投影、Unlit可投不受、深度PNG | 52ee1ee | shadows/shadow_smoke/shadow_ui |
| 每帧RenderPlan、保守视锥剔除、draw/triangle/CPU统计、画外caster保留 | f36a0ff | test_render_plan、renderer_v2_smoke |
| Shot receiver/caster fit、全场景fallback、批量分类与每fit复用 | e055a98/dfcca0d | shadow_camera_fit/shadow_fit_batch、CPU cache benchmark |
| 固定offline split-sum IBL、开关/强度、cube/LUT生命周期 | 1481814 | environment、ibl_gpu、Q1质量对照 |
| 独立ShotCamera、Editor构图复制/API机位、焦距/画幅、letterbox与composition grid | Photography/shot_camera | shot_camera/photo_smoke |
| Shot v3持久化、旧文件清空相机、非法load保持状态 | 7cb7719 | Shot persistence单测与新进程GPU |
| Camera Preview与PNG相同pass、无UI/grid、同步导出 | render_shot/capture_png | photo_smoke、API workflow |
| 可选1×/4× MSAA、color/depth/stencil resolve、resize/释放、旧samples=1 | efd5ddc | shot_antialiasing/shot_msaa_smoke |
| Python实体/组/阵型/事务、场景查询与管理 | Mini3DAPI，Placement共用Commands | test_api/test_api_dispatch、ai_api_smoke |
| Python/JSON摄影机、灯、阴影、IBL、AA、PNG和save/load | Mini3DAPI/白名单dispatcher | lighting/environment/shadow/AA、API端到端 |
| JSON事务限制与异常结构、有限参数、错误不部分修改 | api_dispatch/shared validation | test_api_dispatch及各子系统非法输入 |
| 原Rome＋40、其他真实模型、PBR stage、布局/Unlit/性能边界证据 | Rome支线476a799，本轮合入历史 | rome_integration/shadow_assets/real performance |
| Q1/Q2 Blender离线质量对照、固定assets/HDR/原图/参数/许可 | tools/quality_q2、docs/renderer-v2 | 原图逐字节/逐像素与固定Blender复测 |
| CPU projection/line fallback和旧公共数学/URDF接口 | cpu_renderer/math3d/urdf_loader | camera及历史示例；保留，未以低使用频率删功能 |

Git核查：Q2包含所有feature/fix主链；Rome476a799为独立支线，本轮保留merge历史。
旧backup分支的早期editor/STL/dialog能力在后续链已替代；不恢复旧实现覆盖Commands或Q2。
主目录未提交的统一入口/示例整理将逐文件review接入，原文件保持原状。
不新增实时skin animation、透射阴影、避障、CSM/GI/LOD/Instancing等功能。
