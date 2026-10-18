# C++ 原生场景绘制与拍照集成

构建下文的本机 DLL 后，运行 `python -B -m mini3d --scene examples/pompeii/native-photo.json`，会打开 SPQR 主街的 Shot / Camera View。Arrange 与 Shot 可共用同一 C++ 场景渲染核心；后端选择和回退规则见下文。现有镜头、画幅、曝光、白平衡、景深、点击对焦和 Capture PNG 流程继续使用；照片保存到本目录的 `captures/`。关闭窗口即可退出，没有演示倒计时。`start-photo.cmd` 是本机便捷入口，换机器需修改其中的 Python 路径。

此源代码提交不包含新素材、导出资源包、DLL、EXE、截图或运行缓存。已有仓库资产保持原样；Pompeii 使用内置程序化建筑，无需另行下载模型。独立本地工作副本完成验证后，整理到本仓库。

## 移动与构图

Shot 工作区内，鼠标放在画面上滚动滚轮会沿镜头方向持续移动，每格 1 米；按住 Shift 每格 5 米，Ctrl 每格 0.1 米。可以越过原来的观察目标点，走到远处房屋前。移动时切入 Editor View，点击 Camera View 将当前构图写入拍摄相机，再 Capture PNG。Arrange 仍使用原来的围绕目标点缩放；其主视口也可按后端配置使用共享 C++ 核心。

## 已接入

- Arrange 主视口、Shot 工作区的 Editor View / Camera View 及 `api.capture()` 通过共享场景绘制入口选择 Python 或 C++ 后端。C++ 路径绘制可支持的场景，包含相机深度处理、近景阴影和 1x/4x 抗锯齿。
- C++ DLL 借用编辑器的现有图形上下文，不另开渲染窗口。每次预览通过一次绘制调用提交整个相机帧，颜色和真实深度一起返回现有离屏目标。
- 使用实际绘制投影处理景深和点击对焦，避免近裁面优化后错误反推距离。保存的 Shot Camera 参数保持原值。
- 相机移动、曝光/色彩更新、尺寸和 AA 切换复用已上传的场景。纯实体变换通过批量 transform API 更新 bundle 中所有变化的 leaf；C++ 先校验整个批次，再一次提交并失效阴影缓存。实体拓扑/可见性、mesh identity/bounds、材质或环境资源变化仍重建整份 bundle。冷加载仍需准备和上传资源；CPU Scene 与 Commands 仍是编辑状态的权威来源。
- UI、Shot clean 场景准备/照片色彩、景深后处理、PNG 编码及 Arrange 辅助叠层仍由 Python 管理。共享渲染保留当前 Scene 的 atmosphere/ground；Arrange 不会套用 Shot 专用 clean 场景或照片色彩。Unlit 可由原生核心绘制；Wireframe 在 auto 下回退 Python 并记录原因，在严格原生模式下报错。Legionnaire 编辑器 smoke 覆盖其测试的拖动与存档切换路径；这不等于完整原生编辑器，也不构成所有场景与冷加载的通用 30 FPS 保证。

## Live 纹理与变换协议

在线编辑器导出 live bundle v2：每条纹理记录只包含 GL target 和现有纹理 handle，不读回或保存像素，也不在 native 侧重新上传。v2 由 `spqr_photo_create_shared` 或分帧的 `spqr_photo_begin_shared` 加载；该入口要求创建时当前 WGL context 有效，后续调用使用同一 context/线程。native 只借用纹理，不改存储或采样参数，也不在 renderer close 时删除它们。MaterialRenderer / Environment 的纹理所有者必须活到 native handle 销毁之后。旧离线 `spqr_photo_create` 与 v1 像素 bundle 路径保持不变，且拒绝 v2。

DLL 的 ABI 版本仍为 v1；`spqr_photo_create_shared` 和 `spqr_photo_transforms` 是新增导出。共享 native renderer 要求 DLL 同时提供这两个入口，旧 DLL 缺少任一入口时需要重新构建，不会改走旧的逐帧像素导出路径。变换批次按当前 bundle 的实体索引提交 world、normal 和 mirrored winding；无效索引、非有限值或非 affine world 会在任何实体修改前拒绝整个批次。纯变换保留网格/材质资源，只使原生阴影相关缓存失效。

## 位置与构建

`mini3d/scene_renderer.py` 是 Arrange / Shot 共用绘制入口，负责后端选择与 Python 回退；`mini3d/native_renderer.py` 管理共享 native 渲染器及借用的 GL 上下文。`mini3d/native_photo.py` 仅保留旧导入的兼容 re-export，`mini3d/native_photo_bundle.py` 同步两工作区共用的场景资源和参数。DLL 文件名 `native/spqr_photo.dll`、`spqr_photo_*` 导出名及 ABI v1 保持不变；DLL 需本机 x64 构建，不依赖 Python C 扩展 ABI，镜头帧通过 ctypes 调用。C++ 源在仓库内的 `spqr-native/src/native_photo.*` 和渲染核心中。Windows 安装 CMake、MinGW-w64（含 OpenGL 头文件）及项目 Python 依赖后，在项目根执行：

```powershell
cmake -S spqr-native -B spqr-native/build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build spqr-native/build --target spqr_photo -j 2
Copy-Item spqr-native/build/bin/spqr_photo.dll native/spqr_photo.dll
python -B -m mini3d --scene examples/pompeii/native-photo.json
```

编译器及 Python 位数需一致。当前 C++ 源支持空场景 bundle、live v2 共享纹理和批量变换；修改后必须重新构建并复制 DLL，旧 DLL 不会随 Python 代码自动更新。

本机启动器使用 `F:/gymenv/python.exe` 和现有 Python 依赖；换机器需修改入口中的解释器路径并安装原项目依赖。`tools/run_editor.py` 只给专用运行程序临时设置高性能 GPU 偏好，退出恢复。第三方素材与着色器许可仍适用，附于原项目和 `native/notices/`。

后端通过以下环境变量选择，工作区专用变量优先于共同设置：

```powershell
$env:MINI3D_RENDER_BACKEND='auto'   # 共同默认：auto / native / python
$env:MINI3D_ARRANGE_BACKEND='native' # 可选，仅覆盖 Arrange
$env:MINI3D_PHOTO_BACKEND='native'   # 可选，仅覆盖 Shot
$env:MINI3D_REQUIRE_NATIVE_RENDER='1' # 可选，Arrange 与 Shot 都必须使用 native
$env:MINI3D_REQUIRE_NATIVE_PHOTO='1'  # 旧设置，仅对 Shot 严格
```

`auto` 在原生 DLL 可用时尝试 C++；缺 DLL 时使用 Python，原生绘制不兼容时回退 Python 并在 `render_stats` 记录原因（资源不兼容也会打印日志）。`native` 显式选择是严格模式，失败会报错；`MINI3D_REQUIRE_NATIVE_RENDER=1` 对两个工作区都严格，旧变量 `MINI3D_REQUIRE_NATIVE_PHOTO=1` 只对 Shot 严格。严格 native 与显式 `python` 冲突时会报错。Unlit 受原生核心支持；Wireframe 尚不支持，auto 下回退并记录原因，严格模式报错。

## 当前验收入口

真实 Legionnaire 导入卡顿的根因、阶段耗时、复现命令与证据见 [导入修复验收](docs/LEGIONNAIRE-NATIVE-IMPORT.md)。

- `tests/test_native_renderer.py`：共享后端策略、缓存失败、相机参数失效条件和关闭后重建等契约。
- `tests/native_arrange_gpu_smoke.py`：Arrange 原生后端的 GPU smoke 入口。
- `tests/native_legionnaire_editor_smoke.py`：实际编辑器中导入高面数 Legionnaire、选择/拖动、Undo/Redo、保存重载、切换 Shot 和关闭纹理借用者的 GPU 验收入口。

## 验证

- 5 项滚轮移动测试通过，覆盖越过目标点、快慢/反向操作、UI 输入屏蔽、Arrange 原操作和镜头姿态保留；另有 5 项 Shot Camera、24 项相机回归通过。

- C++ 实际绘制 SPQR；1920×1080预览/PNG完全一致；相机/曝光/AA复用、增量变换和几何资源编辑同步通过。
- 近远对焦、光圈响应、深度不被后处理改写、完整 PNG 和重载一致、关闭幂等通过。
- 所有画幅的深度对焦、CPU 色彩参考、色彩重置、HDR 场景保存/重载完全一致通过。
- 完整12帧编辑器运行，拍照→摆放→拍照、控件/API和实际照片导出通过，GL错误为0。

测试脚本随源码提供，历史报告和图片保留本地，不随源代码上传。测试入口、实机配置及性能结论边界见 [原生验证记录](docs/SPQR-NATIVE-VALIDATION.md)。

首次人物验证用了不对应固定点击位置的低机位，点击到了天空；第二次发现 HDR 重载少量色差，已通过显式设置共享上下文采样状态修正，第三次严格比较通过。保留原失败记录，不放宽像素容差。

## 交互分帧初始化

正常可见交互循环使用 `spqr_photo_begin_shared` 创建未就绪 handle，然后在原主线程/context 中逐帧调用 `spqr_photo_prepare_step(handle, &ready)`；返回值表示成功，ready 表示可渲染。单个 shader 或网格为一个阶段；无摄影地面时跳过其专用程序。未就绪 handle 可 destroy，但不可 render/resize/globals/transforms。原同步 create/create_shared 行为保留；旧 DLL 无此扩展时仍可同步运行。后台线程只准备 CPU 资产和图像，不调用 GL。实现与实测边界见 [editor-startup.md](docs/editor-startup.md)。

后续新增模型不再清空已有视口。相同 WGL context、模式及完整处理后 shader 源码的 native renderer 共享已编译 ProgramSet；弱缓存不延长 GL 生命周期，各 renderer 绘制前重设自有 globals，最后一个使用者负责删除程序。只读 `spqr_photo_program_compile_count` 可确认重建是否发生新编译。
