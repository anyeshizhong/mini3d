# 地形实验审阅快照

此目录保留LAB-00至LAB-02B的原精简证据：35个产物从本地captures逐字节复制，总计约6.6MB；[原manifest.json](manifest.json)记录源路径、字节数与SHA256。另有 [LAB-02B-Q1高度混合](lab02b-q1-20261019/README.md)和 [SUR-00外围对照](sur00-20261020/README.md)，各用独立manifest，不改写旧证据。SUR-00审阅包138个产物约26.8MB；构建二进制、完整Bundle和PNG序列不入Git。

- [当前规划与下一阶段](../../../PROJECT.md)
- [实验运行入口](../README.md)
- [Heightmap报告](../HEIGHTMAP.md)、[雕刻报告](../SCULPT.md)、[三层材质报告](../PAINT.md)

| 阶段 | 原始测量报告 | 直观结果 |
| --- | --- | --- |
| LAB-00 基线 | [JSON](lab00-20261019-run03/report.json) | [斜俯图](lab00-20261019-run03/native-1/oblique/preview.png) |
| LAB-01 高度图 | [JSON](lab01-20261019-final/report.json) | [257×257斜俯图](lab01-20261019-final/native-1/gray16-257/oblique/preview.png) |
| LAB-02A 雕刻 | [JSON](lab02a-20261019-verified/report.json) | [连续雕刻GIF](lab02a-20261019-verified/sculpt-replay.gif) |
| LAB-02B 材质绘制 | [JSON](lab02b-20261019-verified/report.json) | [连续绘制GIF](lab02b-20261019-verified/layered/paint-replay.gif)、[近景](lab02b-20261019-verified/layered/views/close.png) |
| LAB-02B-Q1 高度混合原型 | [指标与核验](lab02b-q1-20261019/summary.json) | [原始A/B及无遮挡坡面](lab02b-q1-20261019/README.md)；功能通过，导航预算/摄影画质未通过 |
| SUR-00 外围表示原型 | [完整原始报告](sur00-20261020/measurements/report.json)、[核验汇总](sur00-20261020/summary.json) | [A/B/C图像、路线GIF](sur00-20261020/README.md)；实测完成，C为后续主线，完整世界/画质/性能未通过 |

报告保持原样，包含当时的设备、工作区、源码摘要、采样与本机绝对路径。报告内部引用的完整构建日志、Bundle、PPM、原始GPU深度和缓冲未打包；可通过实验入口重新生成。两份旧报告作为优化对照保留，不替代各阶段最终验收结果。

源码摘要来自测量时的未提交工作区。Git换行规范化、提交前的文件尾空行清理及文档打包可能改变源码原始字节摘要；审阅产物自身按manifest核验，保留原始字节且不作换行转换。生成证据在GitHub改动页默认折叠，便于先审查代码。

GIF使用固定模拟时间播放，不代表实测墙钟帧率。所有功能仍是独立实验，未接入主编辑器；Spline道路和挖填尚未开始。
