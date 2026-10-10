# Shot Camera 阴影范围拟合 V1

2026-10-10。基线 `7b51eae`（Renderer 仍为原始全场景拟合），功能分支 `feature/shadow-camera-fit-v1`。测试 GPU：Intel UHD Graphics 620，OpenGL 4.6.0，驱动 27.20.100.8682。

## 实现与正确性边界

仅 Shot Camera 使用新的范围拟合。Editor Camera 继续使用全场景 ShadowMap；无有效接收区域时回退原算法。未改变 API、Scene v3、材质、分辨率、PCF、bias、draw calls 或阴影附件。

`mini3d/shadow_fit.py` 将实体的变换后局部包围盒与摄影机视锥做凸多面体交集，取得可见接收范围的光源 XY 边界，并保留余量。随后用该 XY 区域形成沿光源方向延伸、覆盖全场景深度的棱柱，将所有实体包围盒与棱柱相交以确定所需光源 Z 范围。光线沿光源 Z 传播，XY 不变，因此在画外甚至摄影机 far 以外、仍能向接收区域投影的遮挡物会被保留。所有原实体仍提交阴影绘制，未采用摄影机视锥剔除遮挡物。

交集计算包含双方顶点及双方边与另一方平面的交点；不依赖“有顶点落入另一个盒子”的错误假设。8 个专项单测覆盖无包含顶点的交叉、独立三平面交点 oracle 的 35 组旋转/缩放随机实例、大小尺度、远处/画外遮挡物、无接收范围与奇异矩阵回退。

## 真实照片与测量

使用[基线报告](baseline.md)完全相同的 22 组场景、镜头、灯光、材质和分辨率。原始参数在基线 `scenes/`；摄影机数据未改变。新运行的完整结果为 [camera-fit-results.json](camera-fit-results.json)，逐场景比较为 [shadow-comparison.json](shadow-comparison.json)。

| 地面/分辨率 | 原每 texel 世界跨度 X/Y | 新跨度 X/Y | 阴影 pass elapsed 原→新 ms | 同步 wall 原→新 ms |
| --- | --- | --- | --- | --- |
| 10 / 1024 | .007517 / .012310 | .007492 / .011657 | .247 → .320 | 1.858 → 3.743 |
| 200 / 1024 | .147669 / .245039 | .013116 / .017222 | .244 → .409 | 1.954 → 3.847 |
| 200 / 4096 | .036917 / .061260 | .003279 / .004306 | 6.749 → 10.436 | 8.952 → 13.600 |

200 地面、1024 下 X/Y 精度分别提升约 11.26/14.23 倍；32 和 200 地面得到相同的摄影区域拟合。阴影阶梯明显缩小，PBR 模型的细节投影也改善。请查看实际 Mini3D PNG：

- 大地面：[原图](baseline/ground-200-1024.png)、[改后](optimized/ground-200-1024.png)。
- Helmet：[原图](baseline/DamagedHelmet-front.png)、[改后](optimized/DamagedHelmet-front.png)。
- [改后低太阳高度画外遮挡物投影](optimized/offscreen-low-sun.png)。

22/22 摄影机深度缓冲 SHA 不变，没有可见几何丢失；Shadow Off 的照片像素不变。3 个 PBR 模型保存并创建新 API 实例加载后，镜头参数和照片逐像素相同；全部 GL error 为零。不同方向、近远镜头、小/大地面均运行。

普通和低太阳高度的画外遮挡物测试在改前、改后都产生中心阴影，亮度下降分别为 53/20。受控地面的接触点、内部阴影点亮度下降均为 50；3 个受光点均为 0，改前改后一致。所查看照片和这些有限探针未发现新的接触分离、Acne 或 Peter Panning；这不是对所有资产/连续镜头运动的无伪影保证。

## 性能与尚存限制

这是质量与耗时的交换，不能宣称免费优化。拟合每次 Shot 渲染重新执行，当前简单场景额外 CPU 开销约 1.5–2 ms；复杂实体数量会增加开销。阴影贴图覆盖率上升也可能增加片段开销，4096 场景退化明显。没有新增阴影 pass 或贴图显存。

计时采用 5 次预热、7 次测量并排除头两次，记录中位数。`GL_TIME_ELAPSED` 测量窗口含 CPU 提交等待/空隙，不能解释为纯 GPU 忙碌时间；同步 wall 另行列出。性能仅在上述集成显卡实测。

包围盒是保守近似，复合模型空隙及宽广地平线仍可能扩大拟合。未做遮挡可见性、缓存或 texel snapping；连续摄影机移动可能产生阴影抖动，尚未专项量化。当前 bias 的归一化深度语义保留，Z 范围改变会改变其世界距离；其他场景仍需选择合适 bias。未引入 CSM、GI、SSAO 或 Renderer 重构。

## 验证与复现

251 项单元测试全部通过，无跳过；原有 12 组实际 GPU 回归及旧 Renderer 阴影基线生成通过，记录在 [regressions/](regressions/regressions.json)。覆盖 Placement、Ground/Surface Move、摄影、AI API、Lighting、Scene clipping、Shadow/UI、Shot 持久化。Issue #5 原始 65 检查及追加跨面板松开 81 检查已在第一阶段通过；最终 UI 复跑记录另存同目录。

```powershell
python -B -m unittest discover -s tests
python -B tests/render_quality_v1.py camera-fit
python -B tests/stabilization_regressions.py docs/render-quality-v1/regressions
python -B tests/ui_photography_journey_20261010.py --panel-release --output captures/render-quality-v1/ui-final
```

资产和旧 Renderer 基线准备要求见基线及 Issue #5 报告。完整原始 PNG 保留在本地 captures，仓库只提交少量对照；不提交第三方模型。未重新进行 Rome 军团布局验收，也未处理 Unlit 动态受光、材质重构或本轮范围之外的功能。
