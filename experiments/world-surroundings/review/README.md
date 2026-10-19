# 地形实验审阅快照

此目录包含LAB-00至LAB-02B的精简证据，供GitHub直接审阅。35个产物从本地captures逐字节复制，总计约6.6MB；[manifest.json](manifest.json)记录源路径、字节数与SHA256。

- [当前规划与下一阶段](../../../PROJECT.md)
- [实验运行入口](../README.md)
- [Heightmap报告](../HEIGHTMAP.md)、[雕刻报告](../SCULPT.md)、[三层材质报告](../PAINT.md)

| 阶段 | 原始测量报告 | 直观结果 |
| --- | --- | --- |
| LAB-00 基线 | [JSON](lab00-20261019-run03/report.json) | [斜俯图](lab00-20261019-run03/native-1/oblique/preview.png) |
| LAB-01 高度图 | [JSON](lab01-20261019-final/report.json) | [257×257斜俯图](lab01-20261019-final/native-1/gray16-257/oblique/preview.png) |
| LAB-02A 雕刻 | [JSON](lab02a-20261019-verified/report.json) | [连续雕刻GIF](lab02a-20261019-verified/sculpt-replay.gif) |
| LAB-02B 材质绘制 | [JSON](lab02b-20261019-verified/report.json) | [连续绘制GIF](lab02b-20261019-verified/layered/paint-replay.gif)、[近景](lab02b-20261019-verified/layered/views/close.png) |

报告保持原样，包含当时的设备、工作区、源码摘要、采样与本机绝对路径。报告内部引用的完整构建日志、Bundle、PPM、原始GPU深度和缓冲未打包；可通过实验入口重新生成。两份旧报告作为优化对照保留，不替代各阶段最终验收结果。

源码摘要来自测量时的未提交工作区。Git换行规范化、提交前的文件尾空行清理及文档打包可能改变源码原始字节摘要；审阅产物自身按manifest核验，保留原始字节且不作换行转换。生成证据在GitHub改动页默认折叠，便于先审查代码。

GIF使用固定模拟时间播放，不代表实测墙钟帧率。所有功能仍是独立实验，未接入主编辑器；Spline道路和挖填尚未开始。
