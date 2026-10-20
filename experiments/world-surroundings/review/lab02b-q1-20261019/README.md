# LAB-02B-Q1 审阅证据

这组资料是独立 SPQR 原生渲染输出；PNG 与 `captures` 原图逐字节一致，没有重绘或后期增强。GIF 是单独真实回放的缩小记录，采用固定模拟播放时间，不代表墙钟帧率。

完整解释、限制和复现命令见 [QUALITY.md](../../QUALITY.md)，算法和许可见 [QUALITY-SOURCES.md](../../QUALITY-SOURCES.md)。本阶段只实施高度混合，未开启去重复或 Triplanar。整体视觉、移动性能及正式集成均未宣告通过。

- [汇总与独立检查](summary.json)
- [正序原始测量](measurements/forward/report.json)、[逆序原始测量](measurements/reverse/report.json)
- [修复后A_control/depth正序](measurements/guard-forward/report.json)、[修复后逆序](measurements/guard-reverse/report.json)；不混入旧depth数据
- [LAB-02A 雕刻 GPU 回归](measurements/sculpt/report.json)
- [文件摘要与原始路径](manifest.json)

`baseline` 是原 LAB-02B 地形，`steep` 是全部方案共用的陡坡诊断地形。每个方案的 `views/` 使用真实绘制回放最终权重，`diagnostic-*.png` 使用同一受控混合坡带。`A_control` 同时关闭高度效果和验证零层采样优化的输出误差，不能把它的性能变化归功于高度公式。

| 原始权重混合 A，近景受控交界 | 高度混合 B_depth，同机位同权重 |
| --- | --- |
| ![A](baseline/A/diagnostic-close.png) | ![B_depth](baseline/B_depth/diagnostic-close.png) |

| A，陡坡 | B_depth，陡坡 |
| --- | --- |
| ![A steep](steep/A/steep-diagnostic.png) | ![B steep](steep/B_depth/steep-diagnostic.png) |

比较 [B_power 近景](baseline/B_power/diagnostic-close.png)、[depth 真实绘制近景](baseline/B_depth/views/close.png)、[远景](baseline/B_depth/views/distant.png)、[移动镜头](baseline/B_depth/camera-motion.gif) 和 [绘制/擦除/取消/Undo/Redo](baseline/B_depth/paint-replay.gif)。输入权重和高度保存在各地形的 `inputs/` 中。

坡面表格使用无遮挡补拍：A/B_power 来自原测量，A_control/B_depth 来自近零抑制修复后的输入。原遮挡机位的 PNG 仍保留。两次补拍均未重测性能，来源与统一相机分别见 [原记录](measurements/unoccluded-slope-report.json) 和 [修复后记录](measurements/guard-slope-report.json)。
