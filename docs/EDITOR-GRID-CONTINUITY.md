# 编辑网格连续性修复

2026-10-18；仅修改 Arrange/Editor 的辅助网格。

## 原因与行为

旧网格只有每方向 21 条线，覆盖范围为 ±200×grid_scale，线距为 20×grid_scale。
缩放只调整范围和间距，中心固定在世界原点，因此拉远会看到方形边界，平移较远会完全丢失网格。

现在使用 OpenGL 3.3 全屏三角形，对每像素计算视线与 placement_plane.z 的交点，再按世界 XY 绘制线条。
覆盖当前可见平面，没有固定的方形端点；线条在无法分辨的远处、Far Clip 和地平线附近平滑淡出。
保留原距离档位决定的间距、原点锚定、红色 X 轴和绿色 Y 轴，支持从平面上下两侧观察。

网格读取已有场景深度，使用真实交点深度参与 LEQUAL 测试，始终关闭深度写入；支持非默认 glDepthRange。
它没有实体或碰撞，不改变模型拾取、有限 PlacementPlane 查询、真实 Ground 或摄影地面。
Shader/VAO 按需创建，关闭时释放，重复关闭安全；绘制后恢复深度、混合、剔除、polygon mode、program 和 VAO 状态。
编辑器的 GL 3.3 core context 对正反面统一设置 polygon mode。

## 验证

`tests/editor_grid_gpu_smoke.py` 在 UHD620 和 MX130 上通过真实 OpenGL/FBO 检查；完整最终数据以 MX130 结果为准：

- 12 个机位/设置：缩远、平移到 (1000,2000)、十倍格距、平面升到 Z=7、斜视、仰视、地平线、向上天空、
  在平面下背向观察、相机位于平面、Near Clip 前、Far Clip 后。
- 缩远时画面外圈可见网格像素从 0 增至 36,036；平移后从完全无网格变为仍有 82,368 个网格像素。
  相机与平面同时升高 7m 的图像逐像素一致；十倍间距确实减少线密度；两个坐标轴在已知世界位置保留正确颜色。
- 所有机位的 Grid On/Off 深度缓冲逐像素一致；房屋 1x 与抬高平面 4x MSAA 的完全覆盖内部区域遮挡正确。
  4x 用例还使用 depth range (0.2,0.8)。MSAA 的部分背景样本可以正常看见网格，不能把 resolved depth 当成所有样本都被遮挡。
- 故意设置非默认混合方程、混合因子、关闭深度测试、开启线框，再绘制网格，调用方状态完全恢复。
- Python/native 照片中 Grid 开关的 RGB 完全一致，native 确认实际运行 native-photo。
- 421 项 CPU 回归通过，包含 6 项地面/拾取/放置职责分离测试。

本地证据：`captures/editor-grid-20261018/`。
`before/after` 是早期 UHD620 检查；`mx130-before/mx130-after` 是完整最终对照，基线 `a9819a8`。
对应 launch JSON 记录高性能 GPU 偏好已恢复；`cpu-tests.txt` 保存 CPU 测试结果。

## 开销

MX130，1081×662，网格单独一次绘制，10 次预热、60 次计时，前后串行运行。
场景已经准备好；complete 包括这次调用及 glFinish，CPU submit 可能包含驱动等待；GPU 为这次网格 pass 的 GL_TIME_ELAPSED。
照片、PNG 编码、完整 ImGui 编辑器循环均不计入此表。

| 网格 pass，ms | 修改前 P50/P95/P99 | 修改后 P50/P95/P99 |
|---|---|---|
| GPU | 0.028 / 0.028 / 0.029 | 0.295 / 0.296 / 0.296 |
| CPU submit | 0.269 / 0.546 / 0.812 | 0.690 / 1.119 / 1.517 |
| complete | 0.413 / 0.658 / 1.029 | 1.125 / 1.765 / 1.986 |

覆盖全视野的网格有额外成本（GPU P95 约增加 0.27ms），不是把旧的少量线段免费扩展到无限远。
这些数据不代表完整编辑器 FPS；本次未重新测量完整城市编辑器的实时帧率。

## 复现与使用

```powershell
& F:/gymenv/python.exe -B tests/editor_grid_gpu_smoke.py --baseline-ref a9819a8 --output captures/grid-check/before
& F:/gymenv/python.exe -B tests/editor_grid_gpu_smoke.py --output captures/grid-check/after
$env:MINI3D_PHOTO_BACKEND='python'
& F:/gymenv/python.exe -B -m unittest discover -s tests -p 'test_*.py'
```

保存当前工作后重启编辑器即可使用，无需修改场景存档或重新编译原生 DLL。
视觉网格的扩展不代表 PlacementPlane 查询范围也变为无限；原有查询范围与错误语义保留。
