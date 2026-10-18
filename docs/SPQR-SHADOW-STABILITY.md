# SPQR 阴影时间稳定性（Bug3）

2026-10-18，实际场景：`examples/roman_street/street.json`。

## 修复

原 far shadow 每帧紧贴相机接收区域，XY 纹素相位、尺度及推进时的深度范围变化，引起闪烁。
最终方案保留局部拟合，增加约 2% 保护范围、有限尺度迟滞、整纹素中心吸附及保守深度范围保持。
仅吸附仍会在约 2% 的尺度重拟合时集中跳变；测试过的轴向小步调整也无改善，未采用。

Python/native 均用两层同分辨率 far depth array。尺度、光空间方向或深度网格变化时，冻结旧图及其实际 float32 矩阵，
分别用原 PCF/PCSS 求同一世界点的可见度，在 8 个不同相机姿势间过渡。平移吸附不启动过渡。
每姿势只绘制当前图，保留原生 near cascade；分辨率、滤波半径不变，没有全场景固定 XY 包围盒。

重复同姿势冻结权重，预览和导出一致。太阳、镜头投影、投影物、地面平面或分辨率变化立即取消过渡并失效缓存。
摄影地面的平面内跟随不改变接收平面。缓存、剔除和 GPU 上传使用同一 float32 矩阵；复用深度的新姿势仍推进权重。
GL 状态保存包含 texture array；重建 program 清除 uniform location 缓存。

额外存储一张 far 深度图（2048²，驱动通常约 16 MiB）。过渡时求两次 far 可见度，没有额外 caster pass。
中途停止会保持权重；两图对应相同静态几何，场景编辑立即丢弃旧层。旧图越界使用新图，新图越界不保留旧阴影。
相机身后区域可以退出局部覆盖。

## 验证

图像 GPU：Intel UHD 620；街道原太阳、2048 far、原 PCF/PCSS。横移 0.2m、推进 3m，各 41 姿势；低太阳 61 姿势。
Python 固定观察图 960×540、4x AA；native 约 683×384、1x AA，生产 shader 另采样 73,728 个固定世界点。
保留各后端原 near/far 策略，不直接比较两后端图像数值。

| 对照 | 横移最大单通道变化 | 推进最大单通道变化 | 推进单帧 >4 色阶像素峰值 |
|---|---:|---:|---:|
| Python 原拟合 | 67 | 68 | 3611 |
| Python 修复 | 0 | 13 | 162 |
| native 原 far 拟合，保留原 near | 58 | 49 | 1186 |
| native 仅吸附/迟滞 | 0 | 48 | 861 |
| native 完整修复 | 0 | 9 | 22 |

Python 推进只评价所有姿势共同可见的世界点；`common-visible.png` 保存掩码，完整帧指标及原图同时保留。
相机身后区域退出覆盖会改变旧观察图，不能把它算成实际视野内闪烁。
Native far 世界点最大单步 visibility 从 0.36359 降到 0.04539，横移和低太阳 far 变化为零。
低太阳 near/far 混合权重有正常小量变化，固定观察图仍完全一致。

缓存与强制重绘的原始深度和观察图逐位一致，静止三次一致；变换、太阳变化触发重绘。
Python 另检查过渡中重复姿势不推进。420 项 CPU 测试通过；native fit 常规/旋转/摄影地面/低太阳/大世界/非法输入通过，
242 姿势 temporal 与 Python 矩阵误差约 2.22e-16；空接收体与非法输入诊断通过。
原生 1920×1080 预览与 API.capture PNG 逐像素一致，资产编辑、AA/窗口变化和关闭生命周期通过。
两后端地面遮挡、焦点、DoF 深度、向上天空、地下观察及带阴影俯视回归通过。

证据位于 `captures/shadow-bug3-20261018/`（不提交原图）：

- `python-street-verified/results.json`：姿势、矩阵、完整帧/共同可见指标和重复姿势检查。
- `native-motion/results.json`：before / nofade / stable、原始 float probes、逐帧图像、缓存控制。
- `native-motion/*/*/shadow-timing.json`：强制绘制生产 far+near depth 的 GPU timer，排除 color，2 次预热、9 次测量。
  UHD620 街道 lateral P95 14.93→15.57ms，dolly 16.96→15.63ms。实际相同矩阵会复用，此项不是完整帧 FPS。
- `native-photo-smoke/report.json`、`ground-python/results.json`、`ground-native/results.json`、`cpu-tests.txt`。

## 性能

MX130 / NVIDIA 581.08、1081×662、原 24mm 镜头、4x AA、摄影地面开启、原阴影设置。
每轨迹 24 帧预热、120 帧测量。基线为 `6da536d` 的源码、级联 shader 和同版备份 DLL。
CPU submit 为提交墙钟时间（可能含驱动等待），GPU 使用整帧 GL_TIME_ELAPSED；完整帧含 glFinish，排除 PNG 编码。

首轮完整帧 P95：横移 35.33→24.82ms，推进 30.83→39.98ms。
推进 after 的 88–92 帧 CPU submit 出现 22.89–81.80ms 长段，GPU P95 21.47ms。
此轮未通过性能门槛，完整数据保留在 `perf-before/` 和 `perf-after/`。
最终在其它 CPU/GPU 测试结束后串行复测，P95 横移 27.30→26.49ms、推进 27.79→29.58ms，均低于 33.33ms。
整帧 GPU P95 横移 19.91→17.41ms、推进 20.77→21.41ms。推进的过渡采样有可测的小量成本，保持在现有预算内。
两轮原始数据全部保留；首轮异常的外部原因尚未证实，不删除或归因于特定进程。
仍有长尾（本轮 after 完整帧 P99 71.20/132.84ms），不能宣称完整编辑器稳定 30FPS。
下表为 `perf-before-serial/results.json` 与 `perf-after-serial/results.json`，每轨迹 120 帧：

| Version | Track | Metric (ms) | P50 | P95 | P99 |
|---|---|---|---:|---:|---:|
| before | lateral | frame_ms | 24.82 | 27.30 | 28.55 |
| before | lateral | cpu_submit_ms | 7.35 | 9.35 | 10.51 |
| before | lateral | gpu_ms | 18.64 | 19.91 | 20.53 |
| before | dolly | frame_ms | 25.15 | 27.79 | 156.46 |
| before | dolly | cpu_submit_ms | 7.36 | 9.60 | 11.19 |
| before | dolly | gpu_ms | 18.82 | 20.77 | 149.16 |
| after | lateral | frame_ms | 18.92 | 26.49 | 71.20 |
| after | lateral | cpu_submit_ms | 7.56 | 11.47 | 15.71 |
| after | lateral | gpu_ms | 12.28 | 17.41 | 30.02 |
| after | dolly | frame_ms | 25.70 | 29.58 | 132.84 |
| after | dolly | cpu_submit_ms | 8.17 | 11.20 | 13.85 |
| after | dolly | gpu_ms | 18.93 | 21.41 | 126.55 |

## 复现

```powershell
$env:MINI3D_PHOTO_BACKEND='python'
& F:/gymenv/python.exe -B -m unittest discover -s tests -p 'test_*.py'
& F:/gymenv/python.exe -B tests/roman_street_shadow_motion.py --output captures/shadow-check/python --frames 41 --ground on
cmake --build captures/spqr-native-integrity-build --target spqr_photo spqr_shadow spqr-shadow-audit -j 2
& F:/gymenv/python.exe -B spqr-native/tests/test_temporal_shadow.py --project . --library captures/spqr-native-integrity-build/bin/libspqr_shadow.dll
& F:/gymenv/python.exe -B spqr-native/tests/shadow_gpu_audit.py --output captures/shadow-check/native --executable captures/spqr-native-integrity-build/bin/spqr-shadow-audit.exe --cases street-lateral street-dolly small-low-sun
```

照片验收检查真实 `native-photo`，禁止默认回退。完整帧比较用 `spqr-native/tools/run_gpu.py` 指定高性能 GPU，
不得并行其它 GPU 测试；工具会恢复注册表偏好。独立 audit EXE 的 GPU 以 trace 为准。

本地运行 DLL 已重建更新：SHA256 `5e3fbd78227ca4220945084cccff08da8241291b00ba4d9ae49feedb66b0f505`。
