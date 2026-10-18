# 编辑器启动黑屏

## 原因与实测

窗口已经创建，但首次 `pygame.display.flip()` 在初始资产载入、Python 侧材质资源准备、live bundle 导出、C++ renderer 创建与第一帧绘制之后。C++ 路径增加的准备工作因此全部发生在黑色窗口仍未被编辑器帧替换时。

在本机、同一默认 Roman Legionnaire（589879 三角形）下的单次实测，从 `editor_runtime.run()` 开始计时：

| 阶段 | native 修改前 | Python 对照 | native 修改后 |
| --- | ---: | ---: | ---: |
| 窗口创建完成 | 0.336 s | 0.316 s | 0.347 s |
| 首次呈现编辑器 | 5.594 s | 2.444 s | 0.992 s |
| 首次场景呈现 | 5.594 s | 2.444 s | 4.860 s |

native 修改前的 bundle 准备为约 2.081 s，原生创建约 1.998 s。这里的 bundle 准备包含 Python 侧资源及 uniform/shader 准备，并非单纯磁盘写入。原始日志：`.runtime/startup-native-before/timings.jsonl`、`startup-python-before/timings.jsonl`、`startup-native-after/timings.jsonl`。

这些是同设备的短流程采样，受 OS/驱动缓存影响；**不能据此宣称 shader 编译或完整启动耗时已消除**。窗口出现之前的 Python import 时间也没有计入。

## 首帧调整后的行为（线程优化前）

可见、多帧的编辑器启动首先合成一帧真实界面，视口显示 `Preparing scene resources...`。此帧不初始化 native renderer，不把占位纹理当成有效场景缓存。下一帧继续在原有 GL context 和线程中准备真实场景；完成前屏蔽排队的场景拾取/操作事件，完成后正常显示并解除捕获。

`--frames 1` 及 `--hidden` 路径仍在首帧同步绘制实际场景，避免自动截图只得到准备界面。没有把 GL 调用搬到不拥有 context 的后台线程，也没有切回 Python 冒充 native。

## 验证

`tests/editor_ui_layout_smoke.py OUTPUT` 使用实际 SDL/GL 窗口，断言第一次呈现前 native.render 尚未调用，保存 `startup.png`，随后验证正常 native 场景及交互。`tests/editor_screenshot_smoke.py OUTPUT` 覆盖最小化、恢复、缩放、UI 截图和照片隔离。`tests/native_legionnaire_editor_smoke.py OUTPUT` 使用真实默认模型检查导入、选择、移动、存档与 Shot 资源生命周期。

另对 `frames=1` 的可见/隐藏两个路径分别实测：均得到 `native-arrange` 与 589879 个颜色三角形，准备提示为空；结果在 `.runtime/single-frame-verified/`。因此自动单帧截图仍输出真实场景。

## 当前线程与分帧路径

正常可见编辑器（不指定固定帧数）在创建 UI 后提交初始模型，使用单个 daemon worker 的私有 AssetCache 读取/解析模型并解码 RGBA 图片。主线程每帧 poll；成功后先 adopt 模板，再执行原有 Add/Drop/Import 命令，只产生一次可撤销编辑。UI 的模型列表添加、拖放及文件选择/路径导入也使用此路径。公开同步 API、隐藏运行及指定固定帧数的自动截图保持同步语义。场景 JSON 的读取和已有场景恢复目前仍为同步路径。

Assets 面板提供 Cancel model loading；新模型请求替换待处理请求，Undo/Redo 和加载场景会取消它。取消/退出不 join worker，也不交付迟到结果；已经开始的 CPU 解析会自行结束，不能中断单次第三方解码调用。拖放使用请求时的 SurfaceHit，等待期间移动相机不会改变最终落点。

OpenGL 和活动 Scene/History 保留在主线程。native.prepare_step 在交互循环中按约 6 ms 的 CPU 时间预算推进资源任务，多个廉价阶段可在同一帧完成；单个不可中断的 GL 调用仍可能超预算。任务包括：Python 材质/天空程序、单张纹理、环境准备、bundle、C++ 开始、逐程序编译、逐网格上传和最终目标初始化。无摄影地面实体时跳过 C++ 地面程序编译。帧间正常呈现 UI、处理事件和 IPC。首次启动没有可显示场景时才清空占位视口；之后新增模型或重建资源保留上一张完整场景图像，进度放在状态栏，暂停旧图上的 Gizmo/拾取/拖放，准备完成后替换画面。待准备场景不写入已完成视口缓存；资源契约改变会取消部分 native handle 并重建；变换通过原有批量更新传递。

新增 C API `spqr_photo_begin_shared` / `spqr_photo_prepare_step` 可与原同步 create_shared 并存；旧 DLL 缺少新增导出时仍走同步创建，新版 DLL 已在本机重建。所有调用要求创建线程及原 GL context，销毁部分初始化不能删除借用纹理。未就绪的 render/resize/globals/transforms 会返回错误。

这改善加载期间的响应性，不代表每次 GPU 调用都有固定帧预算：单个 shader 编译、环境准备或大纹理上传仍可能暂停主线程。尚未启用后台共享 GL context 或驱动程序二进制缓存。

## 线程与 native 生命周期验收

- `tests/test_asset_loader.py`：真实 STL/带纹理 glTF、非主线程解析和解码、source 更新、错误/取消/非阻塞退出。
- `tests/test_editor_loading.py`：主线程提交、单步 Undo/Redo、错误不污染场景/资源列表、请求时落点、加载场景和历史操作取消。
- `tests/test_native_preparation.py`：逐任务推进、资源变化重启、关闭部分初始化和失败策略。
- `tests/editor_loading_smoke.py OUTPUT`：实际 SDL/GL 默认 589879 三角形 Legionnaire，注入 0.5 秒 CPU 延迟，检查加载时持续事件/缩放、真实 native 场景、Undo/Redo 与 Shot；`--real-timing` 不注入延迟。
- `tests/native_preparation_gpu_smoke.py OUTPUT`：新 C API、未就绪操作拒绝、含/不含摄影地面、部分网格上传后销毁与借用纹理寿命。

每次计时应保留完整 report.json；CPU 延迟注入用来证明响应，与正常启动耗时分开报告。

### 本机正常加载采样

`tests/editor_loading_smoke.py .runtime/threaded-loading-final --real-timing` 未注入 CPU 延迟：首个编辑器帧 1.162 s，真实场景出现 4.613 s；CPU 加载期间持续处理 22 帧。该流程还在准备期间缩放窗口并修改物体变换，首帧 native transform 更新已验证。最长单任务为 C++ 主材质程序编译 1.298 s，最长两次呈现间隔 1.301 s；因此不能宣称加载始终 60 FPS 或完全无停顿。这些数据来自一次本机运行，受驱动/OS 缓存和窗口操作影响，不与旧采样作严格性能对照。

`tests/editor_loading_exit_smoke.py .runtime/threaded-loading-exit` 用实际 SDL 点击 Cancel model loading，重新提交并在 worker 仍被测试阻塞时关闭窗口：退出耗时 0.123 s，之后释放 worker 没有迟到场景提交。该测试用于取消/退出语义，不是正常加载速度采样。

### 完整回归

`.runtime/threaded-regressions/summary.json` 记录：完整 452 项 unittest 通过；真实 Legionnaire 编辑器、UI 布局、native 摄影 GPU、statues 摄影 UI、可见/隐藏单帧场景均通过。其后补充的可选 ABI 成对符号兼容检查也通过（native preparation 5 项、既有 adapter 12 项定向回归）。新 C++ 分步生命周期测试的报告位于 `.runtime/native-preparation-gpu-smoke-20261018/report.json`。DLL 使用 `.runtime/native-deferred-build` Release 构建并复制到 `native/spqr_photo.dll`。

## 连续新增模型的回归修复

仅验证启动不够：原分帧循环把每次资源重建也当成 startup_frame 清空 target，导致用户每次向 Scene 添加模型时都出现空白；C++ 每个新 handle 又重复编译相同程序。当前保留已完成视口，后续准备只在状态栏显示，不允许在旧图上操作 Gizmo 或读取错误深度。廉价准备阶段按时间预算合并推进。

原生程序以当前 WGL context、stableShadows 模式和完整处理后 shader 源码作为共享键；旧/新 handle 在同 context 重建场景时共享已编译 ProgramSet，摄影地面程序按需补编译。缓存只保存 weak_ptr，最后一个 renderer 释放时由复制的 GL 删除函数指针回收 program，不依赖已销毁 renderer 的 GLApi。共享 program 的 uniform 状态也共享，因此每个 renderer 绘制前必须重新应用自己的 bundle globals。新增只读 `spqr_photo_program_compile_count` 供回归确认后续资源重建没有重复编译。

`tests/editor_repeated_assets_smoke.py OUTPUT` 使用正常交互循环连续加入真实 GLB，检查准备期间旧场景像素保持、更新后模型数/三角形正确、无需重新打开 Scene，并保存连续添加前中后的截图。`tests/native_preparation_gpu_smoke.py` 还验证 program 复用、跨 renderer uniform 隔离、源码变化导致新编译及借用纹理寿命。

### 连续添加的实际复现与验收

`.runtime/repeated-assets-regressions/old-runtime.log` 用修复前的 runtime 运行同一回归，在第二个模型准备时明确失败于 `Viewport texture changed while preparing roman_legionnaire.glb`；未改写生产源码来运行此基线。

修复后的 `.runtime/repeated-assets-regressions/repeated-assets/report.json`：连续添加两个真实 Legionnaire 实例和 WaterBottle，Scene 从 1 个增加到 4 个 root；每次后续 handle 编译计数均为 0，准备期间与上一张完整视口逐字节一致。三轮总等待分别约 0.510 / 0.370 / 0.966 s（含 CPU 加载、测试图像读回和下一帧检查），最长准备任务约 0.144 s。各轮 before/during/after PNG 保存在同目录；这些是该设备与固定测试流程采样，不能推广为所有模型的加载时间。

`.runtime/native-program-cache-gpu-smoke-final/report.json` 验证共享句柄删除旧 owner 后仍可绘制、地面仅补编译 1 个程序、shader 源码改变会另编译，以及不同曝光两个共享句柄交替渲染后各自像素完全恢复；借用纹理未被删除。`.runtime/publish-final-units.log` 记录最新完整 454 项单元回归通过。
