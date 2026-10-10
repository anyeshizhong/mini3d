# 下一轮摄影渲染技术评估

2026-10-10。本文件仅研究和建议，本轮没有开发抗锯齿、环境照明或背景控制。证据来自 [22 组真实摄影基线](baseline.md)及[阴影改后对照](shadow-camera-fit.md)，没有以生成图片代替引擎输出。

## A. 成片抗锯齿

当前 `mini3d/render_target.py` 离屏颜色纹理和深度/模板附件为单采样。geometry-front/close 中模型轮廓有像素阶梯；圆柱的大片折面还来自原模型分段，抗锯齿不能增加几何细节。大地面的阴影阶梯来自 ShadowMap 世界采样跨度，第三阶段已单独改善，不能把这些问题混为同一类。

最小下一轮实验是仅为 Shot 输出提供可选 4× MSAA：多采样颜色/深度附件，渲染一次后 resolve 到现有单采样颜色纹理，再沿现有 PNG readback 输出。默认保留单采样；需查询 `GL_MAX_SAMPLES` 和具体附件格式支持。本轮未验证当前 GPU 的实际可用样本数，也没有测量 AA 照片或耗时。[Khronos 多采样附件文档](https://wikis.khronos.org/opengl/GLAPI/glRenderbufferStorageMultisample)和[resolve 说明](https://wikis.khronos.org/opengl/Multisample_Texture)支持该流程。

MSAA 主要改善几何覆盖边缘，对片段着色/纹理高频和已经粗糙的 ShadowMap 内部边缘帮助有限。可对照 2× 线性尺寸 SSAA（4× 像素面积），在 GPU 下采样后再读回 PNG；SSAA 可平均更多着色细节，但不能恢复 ShadowMap 没有记录的信息，也可能抹掉细节。

估算 1920×1080、RGBA8 + DEPTH24_STENCIL8：单采样附件约 15.8 MiB；4× MSAA 附件约 63.3 MiB，加 resolve 颜色 7.9 MiB，约 71.2 MiB。2× 尺寸 SSAA 的高分辨率附件加输出颜色也约 71.2 MiB。实际额外深度附件、驱动对齐与缓存会增加占用。MSAA 并不必然执行四次完整着色；SSAA 的片段/填充负载接近四倍，具体耗时必须实测。Shadow pass 不必因此重复执行。

涉及 RenderTarget、Shot 摄影导出路径、API 摄影参数及小范围 UI。主要风险是附件格式支持、集成显卡显存/带宽、MASK/BLEND 边缘、resolve/readback 状态与大幅输出失败后的资源释放。值得安排下一轮 Issue，先限定导出 AA，并用同一照片分别比较 1×、4× MSAA 与 2× SSAA，记录性能后再确定默认值。

## B. 环境照明

geometry-front 的金属球大部分偏黑，仅有限方向高光；Helmet/Lantern 切换光向后也缺少环境反射层次。当前 Scene 模式环境项为 `(1-metallic) * baseColor * AO * ambientIntensity`，纯金属没有这一漫反射贡献，只有 Directional 的直接镜面光。Studio 的辅助展示光不等价于 Scene/Shot 的环境照明。这是现有光照模型的限制，不应归因于 Rome/Pantheon 的 Unlit 材质。

最小方向是固定、许可明确的环境，提供漫反射 irradiance、按 roughness 预滤波的镜面环境和 BRDF LUT；先不做编辑器实时烘焙或复杂环境管理。也可研究解析天空渐变的近似环境，但需明确它与真实 IBL 的质量差异，不能仅增加 ambient 强度就宣称解决金属问题。[Khronos PBR 介绍](https://www.khronos.org/gltf/pbr)、[官方 Sample Viewer](https://github.com/KhronosGroup/glTF-Sample-Viewer)及[Sample Environments](https://github.com/KhronosGroup/glTF-Sample-Environments)是后续实现与参考图的主要资料。

涉及 MaterialRenderer 的 PBR shader、环境资源加载/生命周期、Scene Lighting 状态、API、保存验证及 UI。Unlit 应保持跳过光照。粗略估算 512 面尺寸 RGBA16F 镜面 cubemap 含 mip 链约 16 MiB，128 面尺寸漫反射约 1 MiB，256² RG16F LUT 约 .25 MiB；1024 镜面 cubemap 约 64 MiB。每片段通常增加漫反射、镜面和 LUT 取样；离线预计算可避免每帧卷积成本。以上为设计估算，未运行 GPU 原型。

风险包括线性/sRGB 与 HDR 色调映射、环境旋转/亮度一致性、roughness mip、材质法线约定、资源许可证及加载失败的原子性。值得单独安排 Issue，优先用固定环境验证金属与非金属，并保存相同镜头的 Scene 照片；之后再扩展可替换环境。

## C. 背景控制

geometry-far/reverse 等照片的空白区域只能使用固定清屏颜色，摄影时无法选择底色或建立统一作品风格。地面覆盖整个画面的测试不适合证明背景价值。

最小下一轮方案是 Shot 可选纯色背景，默认沿用当前颜色；随后才考虑背景图（明确 fit/crop）和天空环境。纯色只改变清屏颜色，不增加附件或明显 GPU 工作。背景图使用一次关闭深度写入的全屏绘制，在场景几何之前完成；1920×1080 约增加 207 万背景片段，RGBA8 1080p 纹理约 7.9 MiB，4K 纹理约 31.6 MiB（含 mip 约 42.2 MiB）。天空可复用 IBL 环境，避免重复存储；显示背景和用于光照的环境应有明确独立语义。

涉及 GLRenderer 清屏/背景顺序、Scene/Shot 配置、API、UI 和 v3 可选字段。需明确颜色空间、透明 PNG、背景图宽高比、Editor/Shot 独立性及丢失图片时的加载行为。与深度/阴影混用导致遮挡错误及状态泄漏是主要风险。纯色背景值得独立的小 Issue；背景图/天空建议在 AA、固定环境验证之后安排。

## 交付状态

已修复：Issue #5 跨面板移动事务。已优化：Shot 接收区域约束 ShadowMap，并保留画外投影物。已知限制：单张阴影图、拟合 CPU 开销、高分辨率耗时增长、连续移动稳定性未专项量化；缺少导出 AA 和环境反射。新测得的代价与边界已写入第三阶段报告。本文件建议的三个功能均未开发，等待审查和下一轮明确安排。
