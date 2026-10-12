# 对焦距离与光圈景深

在 **Shot → PHOTO / SHOT CAMERA** 打开 **Depth of field**，设置 **Focus (m)** 和 **Aperture**，或先选中模型再点击 **Focus selected subject**。切换 **Camera View / Preview photo** 检查成片，**Capture PNG** 导出相同画面。Editor View 保持清晰，便于摆放。

相机首次从视图建立时，对焦距离取导航目标的相机空间深度；API 指定 target 时同样初始化。对焦选中模型使用完整层级世界包围盒中心；它不是脸部/眼睛识别。对焦点位于相机后方时明确报错，不改变相机位置或旧参数。

## 参数与单位

- 摄影距离约定 **1 个场景单位 = 1 米**；原始模型导入不会自动换单位，请先缩放到实际尺寸。
- 对焦距离：0.1–1,000,000 米，沿相机观察轴测量，而不是到目标的欧氏距离。
- 光圈为 f-number，支持 0.7–64；UI 提供 f/1.4–f/64 常用档位。数值越小，离焦模糊越大。
- 相机仍使用 36mm 水平片幅、24/35/50/85mm 预设；画幅比例与原来的焦距换算一致。
- 景深默认关闭；缺少新增字段的旧 Scene v3 自动恢复为关闭、5m、f/2.8。新设置通过原 serializer 保存，无另一套相机状态。
- 光圈只控制景深，不改变曝光亮度；现有 exposure_ev 继续控制曝光。

## API / IPC

```python
api.create_shot_camera(position=[0, -3, 1.6], target=[0, 0, 1.6],
    focal_mm=85, aspect='3:2', dof_enabled=True, focus_distance=3, f_number=1.4)
api.focus_on(entity_id)             # 模型完整包围盒中心
api.focus_at([0, 0, 1.7])           # 也可指定脸部等世界空间点
api.set_depth_of_field(enabled=True, focus_distance=3.0, f_number=2.8)
api.capture('captures/portrait.png')
```

原 JSON Dispatcher 和 Live Editor IPC 支持 `set_depth_of_field`、`focus_at`、`focus_on`，参数名与 Python 方法一致；`get_shot_camera` 返回 `dof_enabled`、`focus_distance`、`f_number`。三种新命令按原规则拒绝活动 Placement transaction，错误参数原子拒绝。UI、IPC、重载、成片共用 ShotCamera；对焦/光圈修改使保留视口缓存失效。

## 渲染

从已有 MSAA resolve 深度计算相机空间深度，使用薄透镜弥散圈近似。设 f 为米制焦距，N 为 f-number，s 为对焦距离，z 为像素深度，W 为输出宽度，水平传感器宽度为 0.036 米：

```
signed radius_px = W/2 * f*f * (z-s) / (N * 0.036 * z * (s-f))
```

公式来源：[NVIDIA GPU Gems 3 — Practical Post-Process Depth of Field](https://developer.nvidia.com/gpugems/gpugems3/part-iv-image-effects/chapter-28-practical-post-process-depth-field)。这里独立实现 48 点等面积圆盘采样，在线性颜色中加权后恢复 sRGB，使用深度约束避免背景模糊覆盖对焦主体。Camera View 和 PNG 使用同一函数、相同 1920 像素源图；不处理编辑网格、Gizmo 和 UI。

只替换已 resolve 的颜色，保留深度/模板；过滤器缓存 GPU 资源，不在每帧读回 CPU。Renderer.close 释放所有资源，可重复关闭。恢复纹理、采样器、FBO、视口、program、VAO、深度/模板/混合等借用 GL 状态。

这是屏幕空间摄影近似，不能恢复被遮挡背景；前景外轮廓的散景扩张有限。透明材质沿用原渲染器深度，玻璃等透明层景深可能不准确。性能上限为 1920 像素宽图像的 32 像素模糊半径，其他分辨率按比例缩放；极近距离/大光圈的更大弥散圈会截断，不是路径追踪或多层景深。处理在现有色调映射之后执行，无 HDR 高光散景强化、镜头叶片形状、衍射或自动曝光。

## 验证

```powershell
python -B -m unittest discover -s tests -p 'test_*.py'
python -B tests/depth_of_field_gpu_smoke.py captures/dof-new
python -B tests/live_editor_ipc_smoke.py --output captures/dof-ipc-new
python -B tests/editor_screenshot_smoke.py captures/dof-ui-new
```

GPU 验收使用真实导入的棋盘纹理平面，分别位于 2m、8m，验证对焦前后景互换、对焦平面保持清晰、小光圈恢复细节、MSAA 深度不被修改、1920×1280 预览/PNG/重载像素完全一致、GL 状态恢复与资源释放。`live_editor_ipc_smoke.py` 另验证实际本地扫描士兵通过 IPC 改对焦改变成片，以及带景深场景重载一致。
