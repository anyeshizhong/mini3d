# Renderer V2.1 Q1：固定环境 Split-Sum IBL 实验

本轮在真实 Mini3D PNG 中补上了金属环境反射，并让粗糙度决定反射的清晰程度。
使用一套固定、独立核实为 CC0 的摄影棚 HDR，默认关闭，可经 Python/JSON API 开关。
保留原 GGX 方向光、阴影、材质采样、sRGB 转换和 Reinhard 色调映射。
这是一项最小画质原型；没有开始 Q2、天空编辑器、实时烘焙或新渲染后端。

基线为最新已推送 Renderer V2 `dfcca0de6465d70e4cdcc8881a7f4c4d8084ace3`
（包含 M1 `f36a0ff` 与 M2A）。检查本地工作树及远端分支后，未发现 M2B 工作。
独立分支 `feature/renderer-v21-quality-q1`，Worktree `.worktrees/renderer-v21-quality-q1`。
主工作区的未提交修改和原 CPU-cache Worktree 均保留。

## 实现与边界

新增 `mini3d/environment.py` 负责固定资源、原子设置验证、延迟纹理上传和释放。
每个 MaterialRenderer/context 首次启用时读取一次预烘焙数组，上传三个纹理；随后帧只采样。
关闭 IBL 保留缓存，反复开关不分配新纹理；`release()` / `close()` 删除纹理，支持再次上传。
没有在 Scene.update、RenderPlan 或 Shadow Fit 中增加卷积或缓存逻辑。

原版 Scene 光照中的环境项为 `(1-metallic) * baseColor * AO * ambient`，金属没有环境反射。
Q1 在该结果上叠加环境贡献，A/B 的原方向光、原 ambient、阴影、材质和相机完全相同：

```text
R = reflect(-V, N)
specular = prefilteredGGX(R, roughness * 8) * (F0 * LUT.x + F90 * LUT.y)
diffuse = lambertian(N) * (1 - F0) * (1 - metallic) * baseColor
result += (diffuse + specular) * AO * environmentIntensity
```

Lambertian 资源已包含 irradiance / π，Shader 不再除一次 π。
LUT 的 x 是 NdotV，y 是感知粗糙度；GGX 烘焙参数也是感知粗糙度。
沿用原粗糙度下限 0.045。F0 沿用现有金属度和 KHR_materials_specular 计算；
新增环境项的 F90 按 dielectric specularWeight 与 metallic 混合。
`(1-F0)` 是 Q1 的简单漫反射能量分配近似；暂未加入最新 Khronos Renderer 的多次散射补偿。
这会让高粗糙度金属与完整参考实现仍有亮度差异。

环境以世界方向采样，Mini3D Z-up 转为 glTF/环境 Y-up：`(x, z, -y)`。
没有摄影机绑定的环境旋转。颜色纹理仍先解码为线性，MR/AO/法线/LUT 不做 sRGB 解码；
HDR 使用 RGB16F 线性值，在原 Reinhard 与 sRGB 输出前相加。曝光固定为 **1.0**，
没有添加曝光控制，也没有对 A/B 使用不同曝光、白平衡、饱和度或后期处理。

方向光的 shadowVisibility 仍只作用于方向光；环境反射和漫反射不会错误乘整个阴影图。
AO 沿用材质提供的 AO，Q1 不计算新的环境遮挡。Unlit / Wireframe 的早返回保留，
BLEND alpha 和 MASK discard 不变。老式无 PBR material 的渲染路径继续使用原照明。
Studio 模式仍有原虚拟棚灯/反射面，IBL 同样叠加；摄影与严谨对照使用 **Scene** 模式。

纹理单元 0–6 仍为材质，7 仍为阴影，8/9 为环境 cube，10 为 LUT。
材质渲染保存/恢复新增单元的 2D/cube 绑定与 seamless 状态；上传保存/恢复 unpack 参数。
Shader 使用 GLSL 330，新增纹理/采样功能都属于 OpenGL 3.3。

## 开源研究、版本与许可

| 实现 | 固定版本 | 本轮采用或判断 |
| --- | --- | --- |
| [glTF Sample Viewer](https://github.com/KhronosGroup/glTF-Sample-Viewer/tree/b6f9275f7a95a8a12804e0ff33af3df3c7e9ccc5) | `b6f9275f7a95a8a12804e0ff33af3df3c7e9ccc5` | Viewer 将 IBL/PBR 交给 Sample Renderer；用于参考表现和环境/LUT 的组织方式，未移植 UI |
| [glTF Sample Renderer](https://github.com/KhronosGroup/glTF-Sample-Renderer/tree/0686eb22dc86ecfdd1e0fc93a141b50edac4a706) | `0686eb22dc86ecfdd1e0fc93a141b50edac4a706` | Apache-2.0；原样保留 panorama/filter Shader，用独立桌面 GL host 离线执行 |
| [glTF IBL Sampler](https://github.com/KhronosGroup/glTF-IBL-Sampler/tree/bd32f8a9ae502df5797ad18c705312eda247dbfd) | `bd32f8a9ae502df5797ad18c705312eda247dbfd` | 研究 Lambertian/GGX、LUT、mip 与浮点输出；原 CLI 需要 Vulkan/glslang/KTX，Q1 未编译 |
| [Filament](https://github.com/google/filament/tree/764fe6cac9bdb4ba24d3d852344dfa04a5f70f75) | `764fe6cac9bdb4ba24d3d852344dfa04a5f70f75` | 研究 [IBL 与 BRDF 文档](https://google.github.io/filament/main/filament.html)；过滤 Shader 的相关 Smith GGX LUT 积分已有 Filament 来源注释；未移植 backend |

选用 Sample Renderer 的成熟 Shader，是因为它可直接由本项目已有 NumPy/pygame/PyOpenGL
执行。仅补充文件解码与 OpenGL host，避免引入 Vulkan、KTX/Basis 解码或完整 Filament
发行包。没有自行发明卷积算法。原文件、SHA-256、作者/许可证与编译适配记录见
[tools/ibl/upstream/NOTICE.md](../../tools/ibl/upstream/NOTICE.md)，包含 Apache 完整许可。
原 Shader 内 Holger Dammertz 的 Hammersley 代码另有 CC BY 3.0 署名及许可链接，已保留。

固定 HDR 是 **Studio Small 02 / Greg Zaal**。独立核实其
[原资产 CC0 标记](https://polyhaven.com/a/studio_small_02)及
[Poly Haven 资产许可](https://polyhaven.com/license)，并保留 Filament 随资源附带的 CC0 文本。
工具的 Apache 许可不是判断 HDR 许可的依据。
来源为上述固定 Filament 提交的 `third_party/environments/studio_small_02_2k.hdr`；
源 SHA-256 为 `8dee8bd1f47b6e723284a58bd0a2db12e3cd3bc70283e17707d06b6b142065e0`。
原 HDR 不随运行时分发，资源改动仅包括投影、卷积、降分辨率和 FP16 存储；没有增亮。
细节见 [资源 NOTICE](../../mini3d/resources/ibl/NOTICE.md) 与
[烘焙元数据](../../mini3d/resources/ibl/neutral.json)。

注意模型自身的许可与环境许可不同。Helmet 的上游同时列出 ctxwing 的 CC BY 4.0
和早期模型 theblueturtle_ 的 CC BY-NC 4.0；本实验保留两项署名，Helmet PNG 用于非商业审查。
Lantern / Avocado 上游为 CC0。完整署名、固定模型审计版本和原链接见
[照片 NOTICE](q1/NOTICE.md)。不重新分发这些 GLB，不把所有照片标成 CC0。

## A/B 原始照片与 C 参考表现

以下链接都是未经后期处理的 Mini3D 1920×1080 PNG。A 是关闭 IBL，且与独立原版
`dfcca0d` Worktree 生成的 A **逐像素相同**；B 只启用 IBL。
同一模型的相机、几何、纹理、材质、方向光、阴影与分辨率相同，深度数组也逐项相同。

共同参数：Scene mode，direction `[-3,-4,6]`，diffuse `2.0`，ambient `0.12`；
阴影 1024、bias `0.0003`、PCF 开启。环境强度 **0.35**，曝光 **1.0**，Reinhard + sRGB。
真实模型统一缩放到 Z 高度 2，居中、底面贴地；摄影机 `[3.4,-5.2,2.9]`，目标 `[0,0,1]`，
50 mm、16:9、near 0.03、far 100。球阵列摄影机与全部矩阵在 results.json 中独立记录。

| 模型 | A 原 V2 | B IBL | C：Khronos 参考表现说明 |
| --- | --- | --- | --- |
| DamagedHelmet | [原 PNG](q1/DamagedHelmet-A.png) | [原 PNG](q1/DamagedHelmet-B.png) | 金属面主要反射环境；软棚灯应在弯曲、损伤及粗糙度变化处形成不同宽度的亮部，不能靠 diffuse ambient 照亮金属 |
| Lantern | [原 PNG](q1/Lantern-A.png) | [原 PNG](q1/Lantern-B.png) | 木材/石座有漫反射环境填充，金属挂链/箍环有反射；发光灯罩不因环境开关改变自身 emissive 输入 |
| Avocado | [原 PNG](q1/Avocado-A.png) | [原 PNG](q1/Avocado-B.png) | 非金属主要保留 baseColor 驱动的漫反射，反射较弱；绿皮、黄果肉与棕核仍应分开，而不是整体变白 |
| 可控球体 | [原 PNG](q1/spheres-A.png) | [原 PNG](q1/spheres-B.png) | 金属球体现环境颜色和形状，粗糙度从低到高使反射逐步变宽/模糊；非金属仍以有色漫反射为主 |

C 是基于固定 Sample Renderer 的
[IBL Shader](https://github.com/KhronosGroup/glTF-Sample-Renderer/blob/0686eb22dc86ecfdd1e0fc93a141b50edac4a706/source/Renderer/shaders/ibl.glsl)
及样本模型资料的参考表现解释，**没有声称已运行 Viewer 或获得匹配相机的 C 截图**。
可在 [官方 Sample Viewer](https://github.khronos.org/glTF-Sample-Viewer/) 打开对应模型并导入
同一 HDR 复核；默认 Viewer 环境、相机、色调映射与 Mini3D 不同，不能逐像素比较。
Q1 的单次散射与简单 diffuse 能量分配也区别于完整参考实现。

球阵列上排 metallic=1、下排 metallic=0；从左到右 roughness=`0.08,0.30,0.60,1.00`，
全部 baseColor 为线性 `[0.55,0.25,0.07]`，几何与法线相同。
每个球使用独立 glTF fixture，避免实例共享材质把粗糙度覆盖成相同值。

目视检查：Helmet 侧面、鼻部和金属边缘获得环境反射，低粗糙度金属球清楚反射棚灯；
高粗糙度反射平缓。Lantern 金属箍/链条更可辨，木材纹理仍在。Avocado 没有异常发白，
原纹理的绿、黄、棕保持分离。IBL 填充使地面和阴影内部也变亮，但阴影仍可辨。
未见新纹理方向/采样错误；球体与 Avocado 原有的局部自阴影/离散边缘仍存在，Q1 未修阴影或 AA。
Helmet B 有 632 个像素任一通道 ≥254（全图约 0.0305%）；球阵列有 23 个。
Lantern/Avocado 没有此类像素。强棚灯高光局部接近白，未出现大面积曝光截断。
这不是色差仪测量；不声明与 Viewer 的颜色数值完全一致。

## 实测性能与纹理代价

硬件：Intel Core i7-8550U，**Intel UHD Graphics 620**；Windows 10，Python 3.8.20、
NumPy、pygame 2.6.1、PyOpenGL；实际驱动 GL `4.6.0 - Build 27.20.100.8682`。
专门 GPU 回归请求了 OpenGL 3.3 core，实际渲染成功；Shader/API 均不依赖超过 3.3 的功能。
该机器每片段支持 32 个纹理单元，Q1 占用到单元 10；3.3 的最低 16 个也足够。

计时包含 RenderPlan、方向光阴影 pass 与颜色 pass。同步 CPU+GPU wall 时间用 glFinish
和 perf_counter，GPU 时间用 GL_TIME_ELAPSED。不包括 PNG 编码/读回、Scene.update 或首次上传。
同一进程交替 A/B，3 组热身后各 12 次；表中为中位数，P95 与样本数保存在
[results.json](q1/results.json) 的 `paired_timing`。单独捕获时的计时也保留但不用于表中结论。

| 实际资产，1920×1080 | GPU A → B (ms) | 同步 CPU+GPU A → B (ms) | 实际提交 Draw Calls A/B |
| --- | --- | --- | --- |
| DamagedHelmet 原 GLB | 8.12 → 9.31 | 13.05 → 13.94 | 4 / 4 |
| Lantern 原 GLB | 4.74 → 5.22 | 9.73 → 10.72 | 8 / 8 |
| Avocado 原 GLB | 5.36 → 5.91 | 10.00 → 10.47 | 4 / 4 |
| 8 个诊断球 + 地面 | 6.35 → 7.80 | 13.38 → 14.33 | 18 / 18 |

三个真实模型的 GPU 增量约 **0.48–1.19 ms**。不是 FPS 优化，不把球体成绩作为真实资产性能。
短测存在集显频率、调度和热状态波动，不能外推为复杂场景的固定 FPS。

纹理：diffuse cube `6×32×32×RGB16F`；specular cube 从 256² 到 1² 共 9 级 RGB16F；
LUT `256×256×RG16F`。总有效数据 **3,444,724 bytes = 3.29 MiB**，压缩 npz **2,842,294 bytes**。
GPU 查询确认 RGB/RG 的通道位数为 16；驱动实际分配可能有对齐/额外开销，UHD 620 使用共享内存，
这里报告的是名义纹理数据，未声称测得驱动私有显存总量。
第一次读取/解压/上传并同步约 **60.99 ms**，以后帧复用；关闭 IBL 后释放要调用 release/close。
离线 1024 samples 的烘焙在同 GPU 上约 **2.37 s**，只在开发工具运行，摄影不会执行。

## 验证与复现

针对本轮改动复用相关测试：环境 3 项新测试，以及 Shot persistence、lighting、lighting API、
shadows、API 共 **45 项单测通过**。没有重复运行整个无关资产测试矩阵。
真实 GPU 检查包括：

- `ibl_quality_q1.py`：四组原 PNG，原版 V2 逐像素比较、深度不变、公开 capture 与 Shot 相同；
  Scene 保存/加载后 PNG 相同；开关回原图；摄影机、方向光与原地位置修改生效；
  Unlit 不受 IBL，纹理复用、材质 GL 状态恢复、release 后重建。
- `ibl_gpu_regression.py`：IBL 开启时 BLEND / MASK / OPAQUE alpha 保持一致，MASK 丢弃仍生效；
  Unlit 图完全相同；首次上传恢复脏 unpack 设置；查询浮点纹理格式；重复 close 删除纹理；
  画外投影物仍在 Shot shadow_candidates 中，IBL 开启时中心阴影降低约 19.67/255。
- 原 `shadow_smoke.py`：旧 disabled/Studio 基线精确匹配，alpha shadow、发光/Unlit、PCF/bias、
  摄影 PNG、GL 状态及资源释放通过。其方块计时仅是功能回归证据。
- 原 `lighting_api_smoke.py`、`photo_smoke.py`、`shot_camera_persistence_smoke.py`：
  方向光、摄影按钮/镜头/比例、重启加载摄影机与 PNG 一致通过。所有检查 GL error=0。

原版结果、源 Shader SHA 与当前结果分别在
[original-v2-results.json](q1/original-v2-results.json)、[results.json](q1/results.json)；
GPU 专项及旧回归数据在 [ibl-gpu-results.json](q1/ibl-gpu-results.json)、
[shadow-results.json](q1/shadow-results.json)、[lighting-api-results.json](q1/lighting-api-results.json)。
PNG 的 SHA 与模型 GLB SHA 也在结果文件中。

Python API（调用方像原来一样持有 OpenGL context 和 GLRenderer）：

```python
api.set_environment(enabled=True, intensity=0.35)
api.get_environment()  # {'enabled': True, 'intensity': 0.35}
api.capture('ibl.png')
api.set_environment(enabled=False)
```

JSON 新命令是 `set_environment` / `get_environment`；设置不可混入 placement transaction。
Scene v3 增加可选 `environment` 对象，Shot 继承同一 Scene 设置；旧 v1/v2/v3 无该字段时
默认关闭。非法布尔、非有限/负强度、空值和未知字段在加载提交前失败，保留原场景。
强度范围 0–100；与原方向光 diffuse/ambient 独立。Q1 没有新增 GUI 环境编辑器。

在本机 Worktree 中使用 `F:/gymenv/python.exe -B`：

```powershell
# 原版摄影，--engine-root 指向未改动的 dfcca0d checkout
F:/gymenv/python.exe -B tests/ibl_quality_q1.py --baseline --engine-root ../renderer-v2-core --assets-root F:/python_project/mini3d/model/11_benchmark_round01 --output captures/q1-original
# Q1 A/B；原版逐像素比较，缺任何真实模型会直接报错
F:/gymenv/python.exe -B tests/ibl_quality_q1.py --assets-root F:/python_project/mini3d/model/11_benchmark_round01 --original captures/q1-original --output docs/renderer-v2/q1
F:/gymenv/python.exe -B tests/ibl_gpu_regression.py
F:/gymenv/python.exe -B -m unittest discover -s tests -p test_environment.py
```

离线资源可重复生成：从固定 Filament 原始文件链接下载 HDR 到 captures 中，
`F:/gymenv/python.exe -B tools/ibl/bake.py captures/q1-research/studio_small_02_2k.hdr`。
脚本检查源 SHA，使用本地 vendored Shader，没有网络依赖；不同驱动的积分/浮点舍入和
压缩包字节不保证完全相同，烘焙参数与输出 SHA 会记录在 neutral.json 中。
运行 Mini3D 无需原 HDR 或该工具。

剩余限制：固定单环境/方向，没有天空背景、曝光 UI、多次散射、复杂材质的完整 IBL 扩展，
没有局部反射探针或动态物体反射。原 ambient 与 Studio 虚拟反射仍可与 IBL 叠加，
自行把环境强度调得很高会冲淡阴影。原自阴影与锯齿尚在。Q1 完成后提交推送，等待审查。
