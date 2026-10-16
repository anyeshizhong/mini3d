# SPQR Native 核心原型

这是 C++20 场景/渲染核心和独立查看器原型。独立查看器的逐帧渲染不依赖 Python；同一核心现也通过 `spqr_photo` DLL 接入现有 Python 编辑器的 Shot 预览和 PNG。完整原生编辑器与 AI API 的迁移仍属于后续里程碑。拍照集成构建见 [NATIVE-PHOTO.md](../NATIVE-PHOTO.md)。

源码仓库不包含本机编译产物或导出资源包。按下文构建查看器并导出 Pompeii 至 `assets/` 后，将生成的 `build/bin/spqr-native.exe` 复制至本目录 `bin/`，双击 `run-demo.cmd` 可运行一小时主街演示，开启平滑相机、垂直同步和4x MSAA。它沿测试路线播放相机，尚未提供完整编辑器交互。

也可直接运行：

```powershell
bin/spqr-native.exe --bundle assets --output demo-output --route orbit --seconds 120
```

`--capture` 在基准结束后重新渲染首个测量机位和中间机位，输出颜色与阴影深度，截图不计入帧时。`--validate-only` 只检查资源包，不创建 GL 上下文。`--seconds` 默认循环离散相机样本；同时使用 `--smooth-camera` 可按经过时间平滑往返播放（单程8秒）。`--vsync` 用于可见预览；正式无上限性能测试不加此选项。

默认启用保守相机深度范围修复，根据原始视锥与真实物体包围盒的交集收紧 near，减少远处墙裙、门窗与瓦线的深度冲突，不使用固定的最低近裁距离。近面相交和无效数据保留原 near。`--legacy-depth` 仅用于复现旧路径和旧参考图比较；四张旧参考图不能代表整条移动路线的画质已通过。

`--record-dir DIR --record-every N --record-count N` 可保存离屏目标与窗口前缓冲的诊断图像对；这会读回 GPU 并拖慢后续帧，报告会标记 recording，不能用作性能验收。

`--samples 1|4` 指定颜色抗锯齿采样数，命令行默认1以保留旧基准配置；演示入口使用4。4x 在独立颜色目标绘制后解析，阴影保持单采样。显卡能力不足时明确报错，不自动降低配置。基准和截图 JSON 均记录采样数。

默认阴影现为两层：原有全景阴影图保留远处覆盖，4096近景阴影图覆盖相机前方0.02–18米，以固定半径、格点对齐减少近处波浪和移动爬动；12–16米平滑过渡。`--legacy-shadows` 恢复原单图路径；要复现旧参考图，需同时使用 `--samples 1 --legacy-depth --legacy-shadows`。资源包metadata中的2048是旧参考条件，当前运行模式以benchmark JSON为准。

## 结构

- `src/bundle.*`：版本化资源包、共享网格/材质/纹理与独立实体。
- `src/shadow_fit.*`：double 精度接收区域、摄影地面投影、双侧盒/视锥交点与画外 caster 深度拟合。
- 同文件提供保守可见近裁距离计算；颜色使用修复后的深度范围，阴影拟合与天空保留原相机输入。
- `shaders/shadow_cascade.glsl` 是原生近远阴影扩展；基础material.frag仍保存原样，运行时仅在新模式替换阴影采样函数。导出工具会复制此扩展到资源包。
- `src/renderer.*`：原有 GLSL、颜色/阴影实例化、原生裁剪和 OpenGL 状态管理。
- 颜色目标固定为与旧版一致的 RGBA8 / depth24-stencil8，随后复制到窗口；不依赖窗口默认深度缓冲格式。
- `src/platform_win32.*`：Windows/WGL OpenGL 3.3 上下文。原型先针对当前实机，尚未提供跨平台窗口后端。
- `tools/export_scene.py`：一次性导出 Python 程序化资产、现有着色器、测试相机路线及参考图。原生运行不调用资产工厂。
- `tools/run_gpu.py`：只为指定测试可执行文件设置临时高性能显卡偏好，退出恢复原值；报告实际 GPU 仍以 GL_RENDERER 为准。
- `tools/compare_captures.py`：RGB 与阴影深度比较，默认要求完全相等，任何容差必须显式传入并报告。
- `FORMAT.md`：场景/相机包协议。

## 构建

需要支持 C++20 的 MinGW-w64 和 CMake。无需下载渲染引擎、GLM 或其他运行库。

```powershell
cmake -S . -B build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 2
```

开发时把构建目录放在当前会话 `work/native-build`，不要将其写入正式项目。

## 离线导出

从本目录运行以下命令，`--project ..` 使用仓库根的 Python 编辑器：

```powershell
python -B tools/export_scene.py --project .. --output assets
```

导出时需要 OpenGL 上下文，且不能与 GPU 性能测试并行。`--benchmark` 可额外测同相机路径的 Python 渲染参考；该数据不包含编辑器 UI，须与完整编辑器数据分开解释。资源包保留共享关系及摄影地面，未把整个城市烘焙成一个物体。

## 性能与画质口径

目标配置为 MX130、三维视口 1081×662、1x AA、2048 PCF 阴影以及原有程序天空、地面和材质。1440×900 是旧编辑器窗口尺寸，不能当作三维渲染分辨率。

原型读取相机路径，实时计算可见性与阴影拟合；路径文件不包含预计算可见集或拟合阴影矩阵。帧计时排除截图读回和编码。无 UI 的原生查看器结果不能直接宣称完整编辑器稳定 30 FPS。

`tests/test_shadow_fit.py` 验证小型与无效输入；`tests/test_pompeii_shadow.py` 验证完整 435 模块 / 897 渲染对象的多机位与低太阳阴影矩阵。实际 GPU 图像/深度和性能结果由此次会话的交付报告列出。

`tests/test_camera_depth.py --library bin/spqr_shadow.dll --project OLD_PROJECT --output-json RESULT.json` 不创建 GL，独立比较 120 个主街样本的原视锥/OBB 交集，并检查可能受新近面影响的实际三角形裁剪结果及无效输入回退。测试通过不等于所有自由相机位置已验收。

`tests/test_stable_shadow.py` 检查固定范围、格点对齐、近景视锥覆盖、画外投影者及可选288个实景相机样本。新阴影的同机位图像、连续移动性能与限制见本轮 `SPQR-shadow-fix.md`。

## 当前范围

支持的是由导出器生成的同场景原型包，不是完整 glTF 导入器或通用场景编辑器。场景 JSON v3、Python IPC、撤销/重做与完整摄影后处理尚未整体迁移。当前原型通过独立接口验证场景与渲染边界，再决定后续集成。

原有素材与着色器的许可继续适用。源代码来源和哈希由导出包 metadata 记录；不应将第三方纹理或资产重新声明为本原型原创。
