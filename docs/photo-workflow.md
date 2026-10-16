# 点击对焦与相机色彩

打开雕像场景，在 Shot / Camera View 点击脸部，选择光圈，调整白平衡或预设，然后点击 **Capture PNG**。绿色十字显示焦点和观察轴距离（米），UI 标记不会进入照片。手动修改距离会清除旧标记。

点击读取当前显示图像的已 resolve 深度，在像素中心反投影后调用 `focus_at`。它正确处理窗口缩放、四种画幅、上下黑边和交互分辨率。天空深度为 1，黑边没有对应像素，均保留旧焦点。相机位置改变但新帧尚未渲染时拒绝点击，避免用旧图像对焦。透明 BLEND 材质沿用原渲染器的后方深度；本功能不承诺玻璃独立对焦。

白平衡范围 2000–12000K，默认 6500K。它是黑体 RGB 比例的艺术近似，较高数值使照片偏暖。预设仅 Original、Warm、Low saturation；Reset photo color 恢复 6500K / Original。PBR 与天空在线性颜色中、曝光和色调映射之前调整。旧无贴图 Realistic / Toon 路径没有 HDR 色调映射，使用原显示色的 sRGB 解码/调整/编码。默认设置旁路，保持原图逐像素一致，不改变太阳、天空色温或其他光源参数。

Scene v3 在 `shot_camera` 增加 `focus_point`、`white_balance_kelvin`、`color_preset`。缺少字段的旧场景恢复无标记和默认色彩，非法参数在更改场景之前拒绝。相机色彩进入视口缓存键。

```python
api.focus_screen([screen_x, screen_y])  # 当前编辑器窗口坐标，需 Camera View
api.set_photo_color(white_balance_kelvin=7400, preset='Warm')
api.reset_photo_color()
api.set_depth_of_field(enabled=True, f_number=2.8)
api.capture('captures/portrait.png')
```

同名命令可经现有 JSON / IPC 调用。`focus_screen` 需要已绘制图像；离屏 Python 可以继续使用世界坐标 `focus_at`。

## 交互画质与实测

首次和静止预览使用 1920 宽度。参数变化或正在操作控件时使用 960，停止 180ms 后恢复 1920；导出始终使用完整 Shot 尺寸。渲染保持同一纹理标识，使当帧 UI、深度和照片使用同一目标；低分辨率仅用于交互，静止预览与 PNG 一致。

真实 Vespasian + Asclepius、85mm、3:2、4x MSAA。实际 `GL_RENDERER` 是 **Intel(R) UHD Graphics 620**，本记录不代表 MX130。每档预热 5 帧、采样 24 帧，连续改变对焦距离；计时包含 GPU 完成，排除 PNG、读回和交换窗口。

| 宽度 / 景深 | 中位数 ms | P95 ms |
| --- | ---: | ---: |
| 960 / 关闭 | 39.76 | 43.07 |
| 960 / 开启 | 60.42 | 62.66 |
| 1920 / 关闭 | 87.80 | 129.52 |
| 1920 / 开启 | 137.53 | 149.33 |

完整 1920 交互超过 100ms，因此采用上述临时低分辨率。真实编辑器另外记录参数更改到完成窗口帧的 25 个连续样本，包含 UI 和显示，中位数 56.53ms、P95 61.05ms；结果见 `photo-workflow-validation.json`。性能受桌面负载与温度影响，只报告实际样本，不保证所有机器。

## 打开历史摄影会话

原有两套本地摄影会话的 **生成/拍摄测试仍保留** 在 `tests/photographer_session.py` 和 `tests/photographer_session_two.py`。手工打开其已生成场景使用统一工具，不再维护两个临时 Editor 启动器：

```powershell
python -B tools/open_photo_session.py --session photographer 02_sanctuary
python -B tools/open_photo_session.py --session still-life 01_geometry
```

前者读取 `captures/photographer-session/*.json`，后者读取 `captures/second-session/still-life/*.json`。场景来自原会话脚本生成的本地 `captures/`，未生成时工具会明确报错。可附加 `--frames N --screenshot PATH --hidden` 用于定帧查看；该工具只是打开已保存场景，不执行 GPU 自动断言。

## 验证与复跑

316 项单元测试通过，无跳过。真实 GPU 验证四种画幅和缩放矩形、深度读取状态恢复、线性色彩数值、重置返回旧图、真实雕像脸部对焦、预览/PNG/重载精确一致。真实编辑器还验证输入路由、窗口缩放、IPC 修改色彩、960→1920 恢复及最终导出一致。鼠标测试使用实际事件路由注入，不冒充人工验收。

```powershell
python -B -m unittest discover -s tests
python -B tools/capture_statues.py --output captures/statue-dof
python -B tests/photo_workflow_gpu_smoke.py captures/photo-gpu captures/statue-dof/statues-portrait.scene.json
python -B tests/photo_workflow_ui_smoke.py captures/photo-ui captures/statue-dof/statues-portrait.scene.json
python -B tools/benchmark_photo_workflow.py captures/photo-perf.json captures/statue-dof/statues-portrait.scene.json
```

雕像 GLB 只安装在本地，需按 `model/manifest.json` 来源下载后复跑。另补齐 f/1.4↔f/2.8、f/2.8↔f/8 相邻差异和背景梯度清晰度单调递增检查，三档梯度值为 1.0023、1.1882、2.1067。

一次验收脚本使用了立即释放的 SDL Window 包装对象，触发原生访问违规；将包装对象保留到运行结束后，同样的缩放和完整流程重复通过。该问题属于测试脚本，原用户编辑器未退出、场景未损坏。旧 `tests/photo_smoke.py` 按钮流程仍过时，未计为通过。

前景散景扩张、多层透明、ISO 噪声与运动模糊保留为后续范围。
