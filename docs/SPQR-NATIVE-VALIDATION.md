# SPQR Native / 摄影集成验证

2026-10-16。本次提交包含 C++20 渲染核心、现有 Python 编辑器的 Shot 适配，以及拍照滚轮持续移动。素材、导出包、二进制、截图、性能采样与临时运行状态保留本地。

## 已验证

- 旧 Python 工作版：393 项单元测试通过，18 项颜色/阴影深度回归完全相等。
- C++ 同场景原型：435 个独立模块、897 个渲染对象，保留共享网格和实例化；四个旧参考机位在旧兼容模式下 RGB/深度完全一致。
- 相机深度冲突修复：根据原视锥与物体包围盒交集保守收紧颜色 near；120 个主街机位数值和实际三角形检查通过，修复远处墙裙、门窗及屋顶的重叠闪烁。
- 阴影修复：4096 近图与 2048 远图、世界格点对齐、12–16m 混合；288 个实景相机样本的稳定范围、覆盖和 caster 深度检查通过。用户确认原有地面阴影大波浪消失，其余渲染问题暂未全部验收。
- 拍照集成：28 项摄影/Shot/景深单测；MX130 上四组严格原生 GPU 功能测试通过，涵盖真实 SPQR、1920×1080 预览和 PNG 一致、景深/深度对焦、HDR 保存重载、白平衡参考、资源复用、几何编辑同步、完整 UI 往返 Arrange/Shot。12 帧编辑器测试 GL 错误为零。
- 滚轮修复：5 项新测试，另有 5 项 Shot、24 项相机回归通过；可越过原观察目标点，Shift/Ctrl 快慢移动，UI 捕获屏蔽输入，保留 Arrange 缩放和镜头姿态。实际窗口已重开，恢复用户视角误差小于 1e-10，Shot 参数完全保留。

HDR 重载曾暴露少量色差，显式设置共享上下文采样状态后严格比较通过；没有放宽像素容差。测试脚本设置 `MINI3D_REQUIRE_NATIVE_PHOTO=1`，禁止 Python 回退掩盖原生失败。

## 性能边界

目标为规定场景/分辨率/画质下完整编辑器 P95 ≤ 33.3ms。历史独立查看器在 MX130、1081×662、4x MSAA、4096近图+2048远图下短测 P95 主街32.643ms、环绕32.191ms，属于无 UI、隐藏窗口、关闭 VSync 的测试。新拍照集成尚未进行完整编辑器的性能验收，不能据此宣布稳定30FPS或无卡顿；不能沿用较早单阴影/1x配置的较高成绩。

## 源码测试入口

在仓库根运行无窗口相机测试：

```powershell
python -B -m unittest discover -s tests -p test_photo_navigation.py
python -B -m unittest discover -s tests -p test_shot_camera.py
python -B -m unittest discover -s tests -p test_camera.py
```

`tests/native_photo_gpu_smoke.py` 和 `tests/native_photo_editor_smoke.py` 包含原生 GPU、景深、摄影工作流和编辑器功能测试；需先按 [构建说明](../NATIVE-PHOTO.md) 生成 DLL，并提供对应本地场景/资产。使用 `tools/native_check.py` 可为专用 Python 运行程序预先注册依赖目录。C++ 数值测试在 `spqr-native/tests/`，测试脚本的参数帮助列出所需库与实景包。
