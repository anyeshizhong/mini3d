# World Surroundings · 独立实验

本目录复用仓库现有 SPQR C++20/OpenGL 查看器与同一 Renderer 核心，保留已完成的地形基础实验。当前优先为**World Surroundings世界外围环境系统**：约定摄影范围内，城市、郊外和远景连续可信。设计、源码接入与验收见 [SURROUNDINGS.md](SURROUNDINGS.md)，完整路线见 [PROJECT.md](../../PROJECT.md)。

**SUR-00固定场景、A/B/C回放和首轮实测已完成，下一步SUR-01先修地表分块/阴影参与再建设连续世界。** 摄影范围X/Y各±200m、地表上1.6～120m仍是完整世界待验收目标；没有手动自由摄影窗口或正式Editor集成。代码、复现与已发现风险见 [SUR-00](SUR-00.md)。近景材质和完整Spline继续后置。

当前方案为[SURROUNDINGS v0.3](SURROUNDINGS.md)：单个罗马郊外的地理布局、A天空基线/B最小二维对照/C三维外围已有独立原型；SUR-01连续世界、SUR-02可信郊外、SUR-03完整自由摄影与性能诊断。世界构建和性能分别验收，30 FPS/25ms目标留给后续SUR-PERF，不阻断前期建设；明显架构问题、深度/遮挡和阴影错误仍须当期解决。

GitHub审阅入口：[精简图像、动画与测量报告](review/README.md)。完整构建及原始捕获由下列命令在本地captures生成。

LAB-02B当前为**功能通过、视觉待验收**。[Q-1材质高度混合](QUALITY.md)已有原型，但整体Q画质/导航预算未通过，续作和完整道路让位于SUR。[源码调查与实际适配](QUALITY-SOURCES.md)保留上游版本、许可和公式变化。Q-1不含去重复、Triplanar、草丛/碎石散布或正式Editor集成；SUR仅允许为固定示例准备少量静态外围元素，不算这些编辑功能完成。

LAB-01 高度图/查询、LAB-02A 雕刻和 LAB-02B 材质绘制入口见本文后半部分，实测结果见 [HEIGHTMAP.md](HEIGHTMAP.md)、[SCULPT.md](SCULPT.md) 和 [PAINT.md](PAINT.md)。以下先保留 LAB-00 的复现方式。

## SUR-00：当前外围实验入口

```powershell
F:/gymenv/python.exe -B experiments/world-surroundings/run_surroundings.py --output captures/world-surroundings/sur00-reproduce --conditions day-clear day-haze day-haze-strong sunset-haze
```

A为共同罗马场景与天空，B为从同一C烘焙的固定二维背景，C为真实三维山脊；三者共享地表、出城道路、光照和相机帧。固定机位、连续路线、截图/录像、三轮完整帧测量和镜头扫参相互分离。`--visible`仅显示回放，不是SUR-03自由导航。具体依赖、输出、范围、测量限制和下一阶段风险见 [SUR-00.md](SUR-00.md)。旧LAB/Q命令与证据保持独立。

## 一条命令复现

在仓库根目录、Windows 桌面会话下运行：

```powershell
F:/gymenv/python.exe -B experiments/world-surroundings/run_baseline.py --output captures/world-surroundings/lab00-run01
```

`F:/gymenv/python.exe` 是本机已有环境；其他机器使用安装了根目录 `requirements.txt` 的 Python。需要桌面 OpenGL 3.3、CMake ≥3.20、支持 C++20 的 MinGW g++、Ninja 以及 MinGW 的 `GL/glcorearb.h`、`GL/glext.h`，构建工具需在 PATH。没有新增 pip 依赖，也不需要外部模型或纹理。

- `--output` 必须是新目录或空目录，脚本不会清空已有结果。
- 构建默认位于 `captures/world-surroundings/build-lab00`；可用 `--build-dir` 指定另一个独立构建目录，用 `--cmake` / `--compiler` 指定工具路径。
- 只构建 `spqr-native` target，不写入 `spqr-native/bin` 或替换编辑器 DLL。重复执行可以复用该实验构建缓存；从空构建目录开始会重新编译同一核心。
- 所有 GL 操作与测量串行执行；导出 context 关闭后才启动 native 查看器。失败退出为非零，已开始的运行在 `report.json` 中保留失败状态和日志。

## 输入与输出

`baseline_scene.py` 创建确定性的有限平地和非对称几何标记，设置现有场景光照、程序天空与阴影。通过 `mini3d/native_photo_bundle.export_live_bundle(..., shared_textures=False)` 调用已有导出逻辑，生成 **离线 v1** 网格/材质/着色器 Bundle；没有复制光照或 GL 渲染器实现。

`export_baseline(output, view='horizontal', *, renderer)` 由调用者提供当前 GL context 与 `GLRenderer(1081, 662)`。视图为 `horizontal`、`oblique`、`distant`。原 viewer 只接受 `walk|orbit`，因此每个视图使用独立 Bundle，内含 `orbit` 路线的固定相机帧，不修改查看器接口。

每次运行的主要产物：

| 路径 | 内容 |
| --- | --- |
| `report.json` | 成败、源码/可执行文件摘要、环境、复现命令、三机位原始测量与重复性检查 |
| `configure.log` / `build.log` | 同一 CMake 目标的配置与构建日志 |
| `export-1/<view>/`、`export-2/<view>/` | 两套独立导出的 `scene.bin`、`frames.bin`、`shaders/` 与元数据 |
| `native-1/<view>/preview.png`、`native-2/<view>/preview.png` | 真实原生查看器首个测量机位截图 |
| `native-*/<view>/benchmark-orbit.json` | 每帧样本、P50/P95/P99、实际 GL renderer、AA/阴影模式 |
| `native-*/<view>/captures/orbit-0.*`、`orbit-mid.*` | 首个测量帧与偏移 60 帧的颜色、阴影深度及捕获元数据 |

输出位于已忽略的 `captures/` 下，保留本地供检查，不自动提交或上传。PPM 已为顶向下 RGB；PNG 只做无损格式转换。`.rgba` 为底向上颜色原始数据；`.depth.f32` 是底向上的远阴影图 float32，**不是相机深度图**。稳定近阴影启用状态和矩阵由 capture JSON 单独记录。

## 冻结的测量条件

原查看器固定渲染尺寸 **1081×662**。基线使用 **1x AA、24 帧 warmup、120 帧测量、关闭 vsync、隐藏窗口**，使用当前原生深度修正与稳定近/远阴影路径；源场景远阴影分辨率、相机参数与材质以每份 `metadata.json` 和 capture JSON 为准。

每个机位重复导出并测量两次。脚本检查离线资源字节摘要、三视图共享场景摘要、非空几何/阴影、颜色与深度数值有效性、同机位捕获稳定性、跨运行颜色差异和阴影深度摘要。

程序天空复用仓库内置中性 IBL，资源来源与许可沿用 `mini3d/resources/ibl/NOTICE.md`；其内容摘要也记录在报告中。固定机位可复用已有阴影缓存，capture 的 `shadow_draws=0` 不视作失败，实际检查 active 标志及非空有效深度。

- `render_work_ms` 包含原生绘制提交及 `glFinish`，不含 swap；不是独立 GPU timestamp 计时。
- `swap_interval_ms` 是相邻交换完成之间的完整 viewer 帧间隔，含主循环开销和 swap；与编辑器完整 UI 帧时间分开报告。
- 截图在测量结束后进行；未启用会污染性能样本的 `--record-dir`。
- 两次性能样本允许正常波动，不能要求耗时逐帧相同；相同输入、固定机位的资源与画面则检查确定性。

本基线相机静止、场景很小，不代表连续导航、动态雕刻、主编辑器 30 FPS 或大地形性能。查看器实际 GPU 与导出用 Python GL GPU 可以不同，报告分别保存；`nvidia-smi` 仅作设备/驱动清单，实际 native GPU 以 benchmark 的 `renderer` 为准。

## 验证入口与下一步

```powershell
F:/gymenv/python.exe -B -m unittest discover -s tests -p test_world_surroundings_baseline.py
```

CPU 回归覆盖基线几何/相机/离线帧契约，不能代替原生 GL 图像检查。当前实测结论、三机位图片链接和 LAB-01 最小接入设计见 [BASELINE.md](BASELINE.md)。本阶段不修改正式 Editor、Scene v3、Placement、AI API、UI 或 live ABI。

## LAB-01：高度图与有限地形

使用同一 Python 环境，另需本实验的 Pillow 依赖（本机已装9.5.0）：

```powershell
F:/gymenv/python.exe -m pip install -r experiments/world-surroundings/requirements.txt
F:/gymenv/python.exe -B experiments/world-surroundings/run_heightmap.py --output captures/world-surroundings/lab01-run01
```

第二条命令生成原创测试数据：65×65/257×257的16位灰度高度图、33×49的8位矩形高度图；分别构建32×32单元网格块，验证查询与接缝，再经相同 SPQR 核心进行三机位、两轮原生测量。输出目录仍须为空；构建目录和工具选项与 LAB-00 相同。

导入自己的高度图：

```powershell
F:/gymenv/python.exe -B experiments/world-surroundings/run_heightmap.py --output captures/world-surroundings/my-heightmap --heightmap path/to/height.png --size 128 128 --origin -64 -64 --base-z 0 --height-range 20
```

- 只接受8/16位单通道灰度 PNG，尺寸至少2×2，默认最多1048576个样本；拒绝 RGB、调色板、alpha/tRNS透明度和损坏文件。读取前检查尺寸预算，解码保留16位精度。
- 列从原点向 +X、行从原点向 +Y；可加 `--flip-y` 显式反转行。高程为 `base_z + sample/(255或65535)*height_range`，不按每张图的最小/最大值重归一化，也不按 sRGB/gAMA 做颜色转换。
- `--chunk-cells` 调整静态分块单元数，默认32。共享边界的位置、UV、面积加权平滑法线来自同一完整网格；没有独立 LOD 或流送。
- 浮点高度源保留为只读 float64；实际 Mesh 的坐标规范为 float32。查询按同一组实际 float32 顶点求三角面高度与几何法线；渲染使用平滑法线。float32 会合并XY格点的配置明确拒绝。
- 查询越界返回 `hit=False`，非有限输入报错；格线归正方向单元，最外边归最后单元，单元对角线归首三角。任何三角面规则都没有偷偷替换成双线性高度。
- 默认三组样例保留 LAB-00 的36×26米占地与固定机位/画质，便于对照采样密度成本；自定义尺寸/原点/高度范围会相应调整机位和标记物尺度。图中标记物只作单点锚定探针，不代表大型建筑地基完整贴合。

程序调用入口在实验目录加入 `sys.path` 后使用：`Heightfield.flat(...)` 创建平地，`load_heightmap(...)` 导入高度图，`to_mesh(...)` / `iter_mesh_chunks(...)` 产生普通 Mini3D 网格，`query_surface(x,y)` 查询高度/几何法线。它们是实验模块接口，不是正式 AI API。

输出包含原始 `inputs/*.png`、原始数值/源代码摘要、查询与射线误差、分块覆盖及接缝检查、几何/资源字节数、三机位 Bundle、PNG 和原生帧时。复制的用户 Heightmap 字节与实际导入参数保存在结果目录及 `report.json` 中。生成时间包含 PNG 解码及静态高度网格/法线构建；独立射线验证耗时另记。

```powershell
F:/gymenv/python.exe -B -m unittest discover -s tests -p test_world_surroundings_*.py
```

这一步交付静态地形、导入与查询；动态雕刻/局部 GPU 上传属于 LAB-02A，材质绘制和道路随后独立验收。正式 Scene、存档格式与编辑器保持原边界。

## LAB-02A：雕刻与持续更新

```powershell
# 自动事件回放、GPU对照、帧时与录像
F:/gymenv/python.exe -B experiments/world-surroundings/run_sculpt.py --output captures/world-surroundings/sculpt-check

# 直接进入独立可操作窗口
F:/gymenv/python.exe -B experiments/world-surroundings/run_sculpt.py --output captures/world-surroundings/sculpt-live --interactive
```

`1/2/3/4`选择抬高/降低/平滑/平整，左键拖动预览、松开提交，滚轮调整下一笔半径，`Esc`取消，`Z/Y`撤销/重做，关闭窗口结束。相机固定；强度为实验模式预设。仅窗口启动烟测可加`--live-frames 30`，默认运行到关闭。

脚本将实验DLL构建到`captures/world-surroundings/build-lab02a/bin/terrain_lab.dll`，复用同一SPQR源码；共享header仅有宏隔离friend钩子，正式DLL不增加接口。运行时保留同一Renderer，更新变化块VBO并刷新bounds/阴影和当前CPU拾取。输出目录、构建目录必须分开；不覆盖用户正式二进制。

自动模式输出`report.json`、`input-replay.json`、`checkpoints/*/preview.png`、GPU/CPU及全量参考对照、`sculpt-replay.gif`。GIF是单独回放中的真实渲染采样，固定模拟时间播放，读回/编码不计入测量帧时。交互模式报告明确不包含自动验收。

实现、实际设备/性能、图像与限制见 [SCULPT.md](SCULPT.md)，共享核心扩展边界见 [DYNAMIC-DESIGN.md](DYNAMIC-DESIGN.md)。65×65实验已通过，尚未集成正式编辑器；三层材质入口见下节。

## LAB-02B：真实三层材质绘制

```powershell
# 同输入比较CPU脏区烘焙和分层shader，GPU校验、三机位与录像
F:/gymenv/python.exe -B experiments/world-surroundings/run_paint.py --output captures/world-surroundings/paint-check

# 直接进入分层方案操作窗口
F:/gymenv/python.exe -B experiments/world-surroundings/run_paint.py --output captures/world-surroundings/paint-live --interactive --scheme layered
```

`1/2/3`选择土壤/岩石/草地，`E`切换绘制/擦除，左键拖动、松开提交，滚轮调整下一笔半径，`Esc`取消，`Z/Y`撤销/重做。标题显示当前状态；关闭窗口结束。相机固定，强度为实验预设；`--live-frames 30`仅用于窗口启动检查。历史超预算会拒绝并回滚该笔，标题显示原因，窗口继续运行。

权重257×257，地形65×65。三层使用随实验提供的真实CC0 PBR小图及世界纹理尺度，运行时无需联网；原始来源和摘要见 [素材NOTICE](assets/materials/NOTICE.md)。`prepare_material_assets.py`用于重新下载和复现输入，常规运行不需要执行。

仍构建同一个实验`terrain_lab` target，但默认使用独立`build-lab02b`目录。分层方案只上传权重脏区，预滤材质atlas保持静态；CPU烘焙方案保留为对照。正式SPQR ABI、生产shader、Editor/Scene/API没有新增地形功能。自动报告包含两方案相同输入/权重检查、GPU纹理和几何读回、全量新建参考、近景/斜俯/远景、独立录像和帧时；`weights.npy`是实验证据，不是正式Scene存档。

实测选择、图像、复现和边界见 [PAINT.md](PAINT.md)、[纹理扩展设计](PAINT-DESIGN.md)。当前下一步为 [SUR-01连续世界](SURROUNDINGS.md)，首轮证据见[SUR-00](SUR-00.md)，完整Spline道路与挖填继续HOLD。
