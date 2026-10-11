# Mini3D V2 整合验证

日期2026-10-11。最终生产代码固定在 `99144e7`，回归工具在 `20f9e8b`；最终文档提交不改变生产代码。
使用既有Python3.8.20，未安装/升级依赖：NumPy1.24.3、pygame2.6.1、numpy-stl3.1.2、PyOpenGL3.1.10、imgui2.0.0；质量工具已有Pillow10.4.0。
实际GPU：Intel UHD Graphics620，GL4.6.0 Build27.20.100.8682。固定Blender3.6.23只作外部验证工具。

| 范围 | 结果 / 证据 |
| --- | --- |
| 全部单元测试 | 277项OK，无skip；原失败回归保留，[unit.log](v2-consolidation/unit.log) |
| 全项目验收 | 37入口（Core26、Quality4、Rome7）全部成功，源码/资源运行期间不变，[完整记录](v2-consolidation/release-runs.json) |
| Core | 26入口，[core-runs](v2-consolidation/core-runs.json)；SDL/ImGui/GL真实窗口和事件注入，不是人工点击验收 |
| Editor/Placement | 选择、复制/删除、文本捕获、orbit/resize、GLB拖入/拾取/Gizmo/Inspector、surface/pivot/bottom/upright、groups/formation、事务、取消/Undo/Redo、存档通过 |
| 摄影/Gizmo隔离 | 81条实际UI检查，0失败，[记录](v2-consolidation/ui_photography_81.log) |
| 同窗口3+1 | JSON实体→UI显示→UI Undo/Redo→API查询→Shot/4x/IBL/shadow/PNG→保存重载→Camera View，[结果](v2-consolidation/unified-api-results.json)、[实际UI](v2-consolidation/editor-unified-api.png) |
| AI API | 原40人API流程、JSON白名单/事务/非法输入、35项摄影和Scene操作，[流程](v2-consolidation/api-workflow-results.json) |
| Shot/MSAA | 4 samples color/depth/stencil resolve、resize/释放、独立READ/DRAW FBO、Preview/PNG、跨新进程重载PNG exact |
| IBL/材质 | 1x/4x首次upload/unpack、opaque/MASK/BLEND/Unlit、cube/LUT16bit、画外caster和close通过 |
| 阴影/裁剪 | Git1033e5e与current disabled/studio exact；Scene深度、bias/PCF、五类原模型+Rome、画外caster/culling通过 |
| legacy/URDF/STL | 五项兼容单测，六张Q2数字入口确定性PNG byte exact，STL Lit/Unlit/Wireframe通过 |
| Q1/Q2 | 4入口成功；26原图byte exact，[quality-runs](v2-consolidation/quality-runs.json) |
| Blender三场景 | Lantern/Avocado/spheres重新打开原.blend，RGBA changed pixels=0、max delta=0，[结果](v2-consolidation/blender-results.json) |
| Rome＋40 | 41 roots、642节点、257绘制实体、23共享mesh、23,948,895 triangles；实际UI/摄影/存档通过，[结果](v2-consolidation/rome-results.json)、[UI](v2-consolidation/editor-rome.png)、[runner](v2-consolidation/rome-runs.json) |
| Rome性能/Shadow Fit | 两机位×1024/4096，CPU21样本、同步帧5样本，GL error0，[raw](v2-consolidation/rome-performance.json) |
| 阴影运动 | 固定世界点确认质量限制，locked fit深度恒定，[raw](v2-consolidation/shadow-motion.json)、[Bug清单](V2-BUGS.md) |

26图是Q1八张A/B、Q2九张1x/4x/SSAA2和九张coverage，全部字节相同。Blender重新编码PNG元数据不同，文件字节不相同，但RGBA像素完全相同。
原Q2 manifest的48项文件大小/SHA-256匹配，原.blend/HDR/图片/参数/license未覆盖。
[源码资源指纹](v2-consolidation/source-hashes.json) 与 [模块依赖](v2-consolidation/dependencies.json) 可追溯；完整runner记录执行HEAD，分类报告从同一完整记录提取。

## 缺陷前后证据

[修复前](v2-consolidation/bugs-before.json) 保留真实失败与 [带实体轴Shot](v2-consolidation/axes-before.png)；[修复后](v2-consolidation/bugs-after.json) 六项全通过与 [clean Shot](v2-consolidation/axes-after.png)。
PACK/PBO原GL error1282变为与正常PNG byte exact并恢复状态；Shot隐藏实体轴且Editor保留；构造失败close由0变1次并关闭SDL。
Rome登记遗漏原KeyError变为真实资产成功。共享示例flatten的 [失败记录](v2-consolidation/legacy-flatten-before.log) 保留，新测试与六原入口PNG已通过。
测试参数/目录错误已纠正重跑，不归入程序Bug，失败日志未删除。
历史Rome harness的baseline=52ee1ee是旧标签，shot_camera_not_in_scene_v3当前为false，正表示Shot已保存；另有严格跨进程回归，不依赖手动重建摄影机。

## 复现和边界

在项目根、已有环境运行，输出选择新目录：

```powershell
python -B tools/validate_v2.py --suite all --output captures/v2-review-02
python -B tools/validate_blender_q2.py --blender <Blender-3.6.23可执行文件> --output captures/v2-blender-review-02
```

Quality需要原 `model/11_benchmark_round01`，Rome需要原Rome/士兵/补充士兵/Pantheon；大型资产和便携Blender不进Git。按既有说明/license/manifest保留或安装，工具不下载替代模型。
旧shadow基线从Git生成新测试快照，不注册/删除worktree；程序只读本版本自身资源。原始日志/性能样本/场景及本地清单在忽略目录，公开仅复制去除机器路径的结果和实际截图。
UHD620上的Rome重网格仍昂贵，未加入LOD/Instancing，不承诺流畅帧率；raw区分GPU timer与同步CPU+GPU时间，不以不同场景/样本数宣称加速。
阴影运动/contact/self-shadow、透明中心排序和球极点缺陷仍遗留；真实事件注入不覆盖全部人工操作、模型/驱动组合。
主目录未提交状态相同，43个原始/独立复制资产哈希一致；未删除/移动Worktree、历史分支、模型、照片或Python环境。详细清单只在本机忽略目录。
候选等待审查及正式main合并许可，本轮不合并main。
