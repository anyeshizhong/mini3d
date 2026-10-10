# Rendering 质量基线 V1 — 2026-10-10

基线分支 `test/render-quality-v1`，基于已修复 Issue #5 的 `406d697`。本阶段没有修改 Renderer、ShadowMap、材质、Camera 或 RenderTarget。Windows / Python 3.8.20 / Intel UHD Graphics 620 / OpenGL 4.6.0，直接读取真实 Mini3D framebuffer 并导出 PNG。

复现：`F:/gymenv/python.exe -B tests/render_quality_v1.py baseline`。原始 22 张照片、22 组场景和完整参数保留在 `captures/render-quality-v1/baseline/`；全部可重新生成。本目录仅提交 6 张代表照片、[场景参数](scenes/)、[完整测量](baseline-results.json)及[本地资产来源](asset-sources.json)，没有上传第三方 GLB 或贴图。

## A. 基础几何与受控地面实验

复用项目 box/sphere/cylinder 生成器和摄影审计的 glTF 导出器。材质包括粗糙非金属、纯金属 roughness 0.2 和显式 Unlit 标记。拍摄正面、反面、85mm 特写、较远机位，并改变方向光。近景金属球的大片暗区、高光及轮廓阶梯是真实输出；圆柱分面也受测试几何/法线影响，不全部归因于 ShadowMap。

代表照片：[几何正面](baseline/geometry-front.png)。不同机位/光向可在对应 scene JSON 和脚本中复现。

与 Work 的受控实验使用相同方块、地面、位置、镜头和灯光：1×1×2 主体，50mm/4:3/1920×1440，position `[7,9,13]`，target `[0.6,0.5,0]`，near/far `0.05/400`，光向 `[-3,-2,3]`，ambient `0.3`，diffuse `3`，bias `0.0003`，3×3 PCF。

| 地面 | ShadowMap | 世界单位/texel X / Y | 阴影 pass GPU 中位 ms |
| --- | ---: | --- | ---: |
| 10 | 1024 | 0.00752 / 0.01231 | 0.2466 |
| 10 | 4096 | 0.00188 / 0.00308 | 7.1677 |
| 32 | 1024 | 0.02375 / 0.03926 | 0.2463 |
| 32 | 4096 | 0.00594 / 0.00981 | 5.9907 |
| 200 | 1024 | 0.14767 / 0.24504 | 0.2439 |
| 200 | 4096 | 0.03692 / 0.06126 | 6.7486 |

原图：[地面 10 / 1024](baseline/ground-10-1024.png)、[地面 200 / 1024](baseline/ground-200-1024.png)。已人工查看：后者明显出现大像素块/PCF 灰度条带，接触区也不精确。4096 在大地面上仍比小地面 1024 稀疏，不作为主要修复手段。

GPU 时间为 `GL_TIME_ELAPSED` 阴影 pass 的 5 个暖机后样本中位数；CPU+GPU 同步 wall time 同时记入 JSON。它不包含 PNG 编码，不是编辑器 FPS，也不代表复杂 Rome 场景性能。集成显卡时钟/负载会造成测量变化。

## B. 三个本地原始 PBR 资产

来自已有 `model/11_benchmark_round01`，复用已下载原件与来源记录，SHA-256 已重新计算。采用同一机位、灯光、200 地面和 1024 ShadowMap；每模型等比缩放到高 2 个世界单位，底部贴地、XY 包围盒居中。正面镜头 `[4,-6,3.5] → [0,0,1]`，50mm/16:9；另有反面 `[−4,6,3.5]` 对照。

| 模型 | 加载到 Renderer 的纹理 | 观察与来源 |
| --- | --- | --- |
| DamagedHelmet | Base Color、Metallic/Roughness、Normal、AO、Emissive | 金属/粗糙度变化和发光细节可见，暗部非常暗；[原图](baseline/DamagedHelmet-front.png)。ctxwing CC BY 4.0 转换，theblueturtle_ 原始版本 CC BY-NC 4.0；截图保留来源和非商业限制。 |
| Lantern | 三个材质均含 Base Color、Metallic/Roughness、Normal、Emissive | 木材、金属、发光灯罩可区分；[原图](baseline/Lantern-front.png)。sbtron/Microsoft 原始版本及 Frank Galligan 转换，CC0。 |
| Avocado | Base Color、Metallic/Roughness、Normal | 非金属、有机纹理与法线细节；[原图](baseline/Avocado-front.png)。Microsoft，CC0。 |

三个原件的 `extensionsRequired`/`extensionsUsed` 均为空，不涉及引擎不支持的必需扩展。标准纹理均成功加载；本测试不是与权威参考渲染器逐像素比对，因此不宣称完整 glTF/PBR 一致性认证。资产源链接、版本、作者、许可证、SHA 和原始 material 定义见 JSON。

三个模型的阴影边缘均受大地面明显影响，和无纹理方块的机制一致。未把 Rome/Pantheon 的 Unlit 材质当作动态光照错误，未转换任何第三方材质。

## 功能与边界检查

- 22 组捕获都经过 `render_shot` 与 PNG 精确像素对照，GL error 为 0。
- 方块/几何场景 Shadow Off/On 的 Camera depth 逐值一致；Unlit 标记的采样颜色完全一致。
- 画外方块 `[4,0,4]` 与低角度光下的 `[20,0,4]` 都向镜头中心地面投影；中心亮度分别下降 53/20 灰度单位。后者的直接光原本较弱，不能用与高太阳相同的亮度阈值判定失败。
- 三个 PBR 模型在新 API 实例加载 scene 后，不创建摄影机，镜头参数及照片逐像素一致。
- 所有照片保存原始 PNG 与 Scene v3，Shot 参数就在 scene 中；不依赖 `views.json`。

## 针对性阴影最小方案

下一阶段拟只调整 Shot Camera 的阴影投影拟合：用各真实实体包围盒与摄影视锥的交集约束接收区域，在光空间拟合 XY；然后用这个 XY 区域向光源方向覆盖所有可见实体的投影深度。绘制时仍提交所有原有遮挡物，保留画外投影。大地面作为接收物参与裁剪，不能直接排除。

Editor Camera 沿用全场景拟合；没有摄影接收区域或数值异常时保守回退。沿用一张贴图、现有分辨率、bias、PCF 和 API，不增加 CSM、额外 GPU pass 或新材质系统。需证明完整包围盒/视锥交集，而不是只保留视锥内物体；并检查截断、画外阴影、接触、不同方向、场景尺度及 CPU/GPU 成本。证明不足则仅交实验报告。
