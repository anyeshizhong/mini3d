# 第一阶段：骄傲的罗马士兵，夕阳与长影

基于 `feature/live-editor-ipc` 的 `2bd94ec764640f6dd30ec6938eedebdc6a8ea8c8` 开发。
交付照片由 Mini3D 自己的 `GLRenderer → Shot Camera → 4x MSAA → PNG` 路径输出，1920×1280。

## 打开和重拍

```sh
python -m pip install -r requirements.txt
python -m mini3d --scene examples/roman_sunset/scene.json
```

启动即显示已经构图的 Shot Camera；点击 Capture PNG 可重拍。
切到 Lighting 可调整太阳方位、高度、色温、曝光、雾与地面；切到 Arrange 可移动士兵。
新建场景可从资产列表添加 `Roman Soldier (built-in study)`，再使用 Lighting 的 Golden-hour preset。

直接导出，同样使用程序的材质、阴影与摄影机：

```sh
python tools/capture_sunset.py
# Linux 无窗口，有 Mesa/EGL 时：
python tools/capture_sunset.py --headless
```

输出 `captures/proud_roman_soldier.png`，旁边的 JSON 记录参数；可复现场景写到 `scenes/proud_roman_soldier.json`。
`--output`、`--scene` 可选择目的路径。已有合法 GLB 时，可用 `--asset path/to/model.glb` 替换示范模型，
按 Z 轴高度缩放并落地；不同模型的朝向、道具和姿态仍需重新调整。

## 摄影设计

| 项目 | 本次成片 |
| --- | --- |
| 镜头 | 50mm，36mm 水平片幅 |
| 构图 | 3:2；士兵在左侧，影子向右后方伸展 |
| 姿态 | 抬起下巴、挺胸、持盾和长矛 |
| 相机 | `(3.3, -5.8, 2.05)`，看向 `(.45, .45, 1.25)` |
| 太阳 | 方位 −90°，高度 9°；世界坐标 Z 向上 |
| 光色 | 3500K 经验近似，作用于直射光；天空补光偏冷 |
| 曝光 | +0.25EV，线性亮度乘 `2**EV` 后统一映射为 sRGB |
| 地面 | 平铺砂石颜色贴图与法线贴图，世界坐标映射 |
| 阴影 | 4096² 定向阴影贴图、PCF；2m 高度投影约 12.6m |

## 已完成

- 程序化天空、薄云和太阳光盘；天空和光照共用世界空间太阳方向，无需太阳实体建模。
- PBR 模型的暖色太阳、天空反射、冷色环境补光、曝光与距离雾。
- 随相机移动的地面覆盖裁剪体，贴图固定在世界坐标；远处融入天空，视野内没有地面边缘。
- 地面参加阴影接收，不加入编辑实体列表、选择或保存的模型对象；PlacementPlane 仍用于布置。
- Lighting 工作区可调参数、夕阳预设；API 和本地 IPC 支持 `get_atmosphere`、`set_atmosphere`、`sunset_preset`。
- 兼容 Scene v1/v2/v3：旧场景默认关闭新天空/地面；新设置与 Shot Camera 一起保存；错误文件不会替换当前场景。
- 原创内建罗马士兵示范模型，包含面部、盔甲、披风、盾牌与长矛，使用标准 PBR 和真实几何阴影。

## 模型与范围

这张照片使用代码内建的青铜/彩绘风格示范模型，**不是原来的博物馆扫描模型，也不是真人写实模型**。
原仓库和用户提供的旧压缩包不包含 `roman_legionnaire.glb`；公开下载端点要求登录。
本轮没有使用生成图片替代程序渲染，也没有把缺少原模型的 Rome/Quality 测试计作通过。

本轮聚焦这个拍摄场景；天空是程序化环境，尚未做任意 HDRI 导入。
光色与曝光接入 PBR 材质管线，原来的卡通/STL 着色仍保留旧行为。
没有伪造 ISO、快门或光圈的物理效果；景深、运动模糊、传感器噪声和滤镜不属于这次交付。

## 验证

```sh
python -m unittest discover -s tests -p 'test_*.py'
python tests/sunset_gpu_smoke.py
```

共 301 项单测，293 项通过、8 项因缺少原来的可选模型资源跳过。真实 OpenGL/EGL 验收包括：

- 地面阴影超过 10,000 个像素，横向跨度 310px（720×480 验收画幅）；
- 暖/冷色温实际改变脸部的红蓝比；
- 看向世界太阳方向时，太阳光盘位于相机中心；
- 保存/重载照片的最大通道误差为 0；
- 地面不污染编辑场景，渲染后无 OpenGL 错误。
