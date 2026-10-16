# 拍照集成版

构建下文的本机 DLL 后，运行 `python -B -m mini3d --scene examples/pompeii/native-photo.json`，会打开 SPQR 主街的 Shot / Camera View。现有的镜头、画幅、曝光、白平衡、景深、点击对焦和 Capture PNG 继续使用；照片保存到本目录的 `captures/`。关闭窗口即可退出，没有演示倒计时。`start-photo.cmd` 是本机便捷入口，换机器需修改其中的 Python 路径。

此源代码提交不包含新素材、导出资源包、DLL、EXE、截图或运行缓存。已有仓库资产保持原样；Pompeii 使用内置程序化建筑，无需另行下载模型。独立本地工作副本完成验证后，整理到本仓库。

## 移动与构图

Shot 工作区内，鼠标放在画面上滚动滚轮会沿镜头方向持续移动，每格 1 米；按住 Shift 每格 5 米，Ctrl 每格 0.1 米。可以越过原来的观察目标点，走到远处房屋前。移动时切入 Editor View，点击 Camera View 将当前构图写入拍摄相机，再 Capture PNG。Arrange 工作区仍使用原来的围绕目标点缩放。

## 已接入

- Shot 工作区的 Editor View、Camera View，以及 `api.capture()` 使用 C++ 绘制可支持的场景，包含此前的相机深度修复、稳定近景阴影和 1x/4x 抗锯齿。
- C++ DLL 借用编辑器的现有图形上下文，不另开渲染窗口。每次预览通过一次绘制调用提交整个相机帧，颜色和真实深度一起返回现有离屏目标。
- 使用实际绘制投影处理景深和点击对焦，避免近裁面优化后错误反推距离。保存的 Shot Camera 参数保持原值。
- 相机移动、曝光/色彩更新、尺寸和 AA 切换复用已上传的场景；几何/材质、天空资源等变化会重新同步资源包。资源初次准备和几何编辑可能有停顿，目前尚未改成细粒度原生场景命令。
- 原有 UI、景深后处理、PNG 编码和 Arrange 绘制仍在 Python。此交付不等于完整原生编辑器，也没有新的完整拍照交互 30 FPS 验收结论。

## 位置与构建

`mini3d/native_photo.py` 是共享上下文适配层；`native_photo_bundle.py` 低频同步当前场景和参数。离线查看器与实时 Shot 共享唯一的原生资源导出器 `spqr-native/tools/export_scene.py` 和阴影源码 `spqr-native/shaders/shadow_cascade.glsl`；本机运行必须保留这两份源码文件所在的项目目录。`native/` 仍是 DLL 安装目录，`native/spqr_photo.dll` 需本机 x64 构建，不依赖 Python C 扩展 ABI，镜头帧通过 ctypes 调用。C++ 源在仓库内的 `spqr-native/src/native_photo.*` 和渲染核心中。Windows 安装 CMake、MinGW-w64（含 OpenGL 头文件）及项目 Python 依赖后，在项目根执行：

```powershell
cmake -S spqr-native -B spqr-native/build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build spqr-native/build --target spqr_photo -j 2
Copy-Item spqr-native/build/bin/spqr_photo.dll native/spqr_photo.dll
python -B -m mini3d --scene examples/pompeii/native-photo.json
```

编译器及 Python 位数需一致。没有 DLL 时默认 auto 会使用 Python 绘制；需要严格检查原生路径时，启动前设置 `$env:MINI3D_REQUIRE_NATIVE_PHOTO='1'`，缺 DLL 或任何回退均报错。

本机启动器使用 `F:/gymenv/python.exe` 和现有 Python 依赖；换机器需修改入口中的解释器路径并安装原项目依赖。`tools/run_editor.py` 只给专用运行程序临时设置高性能 GPU 偏好，退出恢复。第三方素材与着色器许可仍适用，附于原项目和 `native/notices/`。

`MINI3D_PHOTO_BACKEND=python` 可恢复原拍照绘制。默认 auto 在 DLL 存在时接入；遇到原生格式暂不支持的旧模型，使用已有兼容绘制并在日志及 render_stats 记录原因，不丢弃这些模型。验证脚本设置 `MINI3D_REQUIRE_NATIVE_PHOTO=1`，任何回退都会使测试失败。

## 验证

- 5 项滚轮移动测试通过，覆盖越过目标点、快慢/反向操作、UI 输入屏蔽、Arrange 原操作和镜头姿态保留；另有 5 项 Shot Camera、24 项相机回归通过。

- C++ 实际绘制 SPQR；1920×1080预览/PNG完全一致；相机/曝光/AA复用和几何编辑同步通过。
- 近远对焦、光圈响应、深度不被后处理改写、完整 PNG 和重载一致、关闭幂等通过。
- 所有画幅的深度对焦、CPU 色彩参考、色彩重置、HDR 场景保存/重载完全一致通过。
- 完整12帧编辑器运行，拍照→摆放→拍照、控件/API和实际照片导出通过，GL错误为0。

测试脚本随源码提供，历史报告和图片保留本地，不随源代码上传。测试入口、实机配置及性能结论边界见 [原生验证记录](docs/SPQR-NATIVE-VALIDATION.md)。

首次人物验证用了不对应固定点击位置的低机位，点击到了天空；第二次发现 HDR 重载少量色差，已通过显式设置共享上下文采样状态修正，第三次严格比较通过。保留原失败记录，不放宽像素容差。
