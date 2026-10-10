# Renderer V2 开源引用

Milestone 1 没有集成、复制或移植新的第三方代码，没有新增 Python/C++ 依赖。六平面 AABB 支撑值判定为项目内实现，使用既有 NumPy 矩阵运算；独立八角点 oracle 单测及真实 V1/V2 像素对照验证其行为。

cglm、meshoptimizer、pybind11、Khronos Sample Viewer、Filament 和 bgfx 目前均只是后续路线图候选，不应标记为已采用。以后实际集成时，在本文逐项记录上游 URL、固定版本/SHA、许可证、署名、使用范围、构建依赖及实测收益。

本轮真实 PBR 资产沿用已有 DamagedHelmet 来源与许可证清单：[asset-sources.json](../render-quality-v1/asset-sources.json)。没有提交原始模型或贴图；[里程碑报告](milestone-1.md) 为输出图片提供作者署名和许可说明。既有渲染依赖、阴影 shader 来源与行为未因本轮而替换。
