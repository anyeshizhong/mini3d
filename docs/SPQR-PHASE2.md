# SPQR Phase 2：浏览性能、模块对齐和天体照明

基于 Phase 1.1 `7f0c5d8`。本轮修改留在工作区，等待用户检查后再决定提交。

## 天空与光照

打开街景，进入 **Lighting**，可用 **Day / Stars / Moonlight** 按钮，或已有夕阳按钮。预设设置场景方向光的方向、直射/环境强度、色温、天空、曝光和阴影开关；不会变更建筑、编辑机位或摄影机。天空来源选择与灯光选择也可分开调节。

**Light azimuth** 覆盖完整一周，**Light elevation** 为 −90°～90°。方向始终是世界空间的“表面指向光源”，不随相机转动。Main light 在 Sun / Moon 之间切换；Light temperature / Disc diameter 调节当前光源的色温与可见盘面，直射强度沿用 Lighting 的 diffuse 控件。日月共用一个投影光源，不支持同时两套日月阴影。

启用天空时，光源在地平线以下会停止提供直射光；在地平线上方最后0.5°淡出。保存的diffuse值不会因此被覆盖。关闭天空仍可使用任意方向的手动灯光。月夜默认较暗，可调整曝光、ambient和diffuse。Stars预设是无月光的晴夜，Moonlight预设增加月盘和投影月光。

星点由世界方向上的固定程序分布生成，不含时间闪烁、实际星图、天文日期或月相模拟。天空仍是全屏背景，使用现有反射/雾化路径。HDR图片保留其烘焙内容，切换Main light不会把HDR照片中的太阳替换为月亮；月夜请使用程序夜空或适当的自有HDR。

```python
api.sky_preset('moonlit')  # day / sunset / stars / moonlit
api.set_atmosphere(azimuth=90, elevation=25, sun_temperature=8500,
                   celestial_body='moon', sun_size=.53)
api.set_lighting(diffuse=.7, ambient=.025)
```

`sun_temperature`、`sun_size`、`azimuth/elevation`沿用旧参数名，表示当前唯一的天体光源。`sky_texture`新增`stars`与`moonlit`，`celestial_body`新增`sun`/`moon`。旧文件默认sun；场景仍为v3。Python、JSON dispatcher和IPC共用这些命令，预设不允许嵌入Placement事务。

## 模块相邻对齐

在Arrange中Shift多选，把最后选中的实例作为固定参照。Inspector显示 **Align beside primary**：设置Gap，点击+X/−X/+Y/−Y。其余可编辑模块按选择顺序依次排列，每个模块的世界包围盒边缘与前一个相隔指定距离。保持其余两个坐标、旋转、缩放与分组；锁定成员不动，参照可以锁定。此操作只做世界轴方向的相邻排列，不是接点吸附或沿弯路排列。

一次操作对应一次Undo；可Redo、保存与加载。

```python
api.align_adjacent(entity_ids=[shop_id, house_id], reference_id=reference_id,
                   axis='y', side=1, gap=.1)
```

API还支持Z轴。该命令可以放进现有Placement事务，UI/API/IPC使用同一个Commands实现。

## 性能改动和画面稳定性

- 批量变换仿射包围盒，保留非法或不支持变换对象，不冒险剔除。
- 阴影只剔除实际光源投影裁剪范围外的包围盒；颜色相机看不到的物体仍可以投影。
- 材质分组顺序使用稳定的场景遍历顺序，避免重新加载后内存地址改变造成少量共面边缘差异。

后续 Performance 工作已接入兼容不透明模块的 GPU instancing 与值检查缓存，见 [性能实现与验收](SPQR-PERFORMANCE.md)。未新增 LOD、地形、流式世界、GI、CSM 或复杂云层；已有摄影质量设置保持原有职责。

## 验收

```powershell
python -B -m unittest discover -s tests -p 'test_*.py'
python -B tests/spqr_phase2_smoke.py --output captures/spqr-phase2
python -B tests/spqr_phase2_performance.py --baseline-ref 7f0c5d8 --output captures/spqr-phase2-performance.json
```

GPU测试对比开启和关闭剔除的同机位成片，验证夜空保存重载、太阳−90°/0°/90°、月光反向和GL错误。性能测试在同一GL进程中交替使用固定Phase1.1和新规划/阴影实现，各运行3次、预热4帧、采样20帧，960×540、1×AA、2048阴影、glFinish同步；此结果不代表完整编辑器的呈现FPS，也不报告未经测量的显存数据。
