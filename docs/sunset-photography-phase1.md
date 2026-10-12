# 骄傲的罗马士兵：夕阳摄影样片

Mini3D 自己通过 `GLRenderer → Shot Camera → 4x MSAA → PNG` 拍摄，1920×1280。
当前交付完善了天空、材质与光照；士兵仍是原创占位模型，尚未达到写实人物照片质量。

## 打开和重拍

在项目根目录运行，直接进入已经构图的 Shot Camera：

```sh
python -m mini3d --scene examples/roman_sunset/hero.json
```

点击 **Capture PNG** 重拍。`hero.json` 是较低机位的仰拍；
`examples/roman_sunset/scene.json` 保留原来的全身和长影构图。
切到 Lighting 调整太阳角度、色温、曝光、天空补光和太阳大小；
新场景可点击 **Photographic sunset preset** 使用同一组实拍材质。

批量导出同一场景：

```sh
python tools/capture_sunset.py --hero --output captures/proud_roman_soldier_hero.png
# Linux 无窗口，有 Mesa/EGL 时：
python tools/capture_sunset.py --headless --hero --output captures/proud_roman_soldier_hero.png
```

不加 `--hero` 导出原机位。旁边的 JSON 记录相机、光照与环境参数。
用 `--asset path/to/model.glb` 可替换为已有的真实 GLB；按 Z 轴高度缩放、落地，
不同模型的朝向与道具仍需调整。

## 当前画面

| 项目 | 仰拍 | 原机位 |
| --- | --- | --- |
| 镜头与画幅 | 50mm、36mm 水平片幅、3:2 | 同左 |
| 摄影机位置 | `(3.3, -5.8, 1.1)` | `(3.3, -5.8, 2.05)` |
| 看向 | `(.45, .45, 1.4)` | `(.45, .45, 1.25)` |
| 太阳方位 / 高度 | −90° / 9°，世界 Z 向上 | 同左 |
| 色温 / 太阳直径 | 3500K / 0.53° | 同左 |
| 直射 / 手动补光 | 5.0 / 0.05 | 6.0 / 0.09 |
| HDR 天空与环境光强度 | 0.45 | 0.7 |
| 曝光 | −0.45 EV | −0.25 EV |
| 地面 | 实拍砂砾颜色、法线、AO 与粗糙度；一块 2.5m | 同左 |
| 输出 | Filmic 曲线、高光压缩、sRGB | 同左 |

## 环境与光照

- 内置实拍 **Belfast Sunset (Pure Sky)** HDRI，不需额外下载；也可在 Lighting
  的 HDR file 输入 `.hdr` 路径，点击 Load HDRI。
- 天空穹顶随太阳方向整体旋转，记录的最亮天空方向与实际太阳向量一致。
  自定义 HDR 以最亮上半球像素估计太阳；含建筑或没有明确太阳的环境，
  这个估计可能不代表真实太阳。首阶段推荐纯天空 HDR。
- 同一 HDR 提供背景、Lambert 漫反射、GGX 粗糙度反射和雾色。
  环境光滤波输入去除小太阳区域，直射阳光由有阴影的独立太阳提供。
- 内置环境预先滤波，普通帧只采样；自定义 HDR 在首次使用时滤波一次。
  为控制内存，支持 `-Y +X` 的 Radiance RGBE RLE，最多 8 百万像素，建议 1K–4K。
- 太阳大小大于零时使用 16 个 blocker 搜索、16 个比较采样的正交 PCSS。
  半影随遮挡物到接收面的距离扩大；零大小保留原来的 3×3 PCF。
  地面参与接收与拟合，不作为投影遮挡物。
- 地面随相机覆盖裁剪体，UV 固定在世界坐标，远处融入天空；这是视觉无限地面。
  不增加编辑对象，不影响拾取或场景实体保存。
- 光照与环境设置均可通过 `set_atmosphere` / IPC 操作，与 Shot Camera 一起保存。
  旧场景缺省关闭这些效果，错误 HDR 或参数不会替换当前场景。
- PNG 先完整编码、检查结束块，再原子替换目标，避免暴露未完成的文件。

资源作者、下载路径与 CC0 说明见 `mini3d/resources/photography/NOTICE.md`；
原文件与打包资源哈希见 `manifest.json`。

## 验证与实际限制

```sh
python -m unittest discover -s tests -p 'test_*.py'
python tests/sunset_gpu_smoke.py
```

304 项单测：296 通过、8 因原可选模型缺失跳过。GPU 结果记录在
`sunset-photography-validation.json`：长影、脸部色温、软阴影、HDR 太阳方向、
自定义 HDR 背景、GL 状态恢复、保存重载完全一致。Lighting、Arrange、Shot 的
ImGui 帧也均可构建。这些检查不等于 Windows MX130 的性能和交互验收。

仍未实现光圈景深、对焦距离、白平衡、运动模糊、ISO 噪声与后期滤镜。
Filmic 是 ACES 近似曲线，非完整 ACES 色彩管线；温度是黑体色的经验近似。
新曝光与环境光主要作用于 PBR，原卡通/STL 着色继续使用旧行为。
现在应先验收这组环境和照片，然后再完成摄影机功能。
