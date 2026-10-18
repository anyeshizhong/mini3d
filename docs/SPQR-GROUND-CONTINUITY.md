# 摄影地面连续性（2026-10-18）

对应 `SPQR-VISUAL-INTEGRITY.md` 第 2 项。用户确认实际使用
`examples/roman_street/street.json`。本次修复不添加街区或外围建筑。

## 两个可以复现的来源

旧摄影地面虽然覆盖相机附近 `2*far` 的正方形，仍使用普通三角形远裁剪。
在 `far=150`、相机高 300m 时，俯拍整个平面在裁剪距离以外；640×360 的测试
有 230400 个像素显示天空。20m 高、15° 俯角也有 55040 个向下像素显示天空。
Python 和 native 都能复现。

实际街道示例还有另一处配置问题：`atmosphere.ground=false`，所以有限道路以外
没有摄影地面。只修启用地面时的远裁剪不能改变这个示例。现为该示例打开摄影地面，
放在 `ground_z=-.14`，低于道路实体最低点约 `-.12`，不与铺路面或路基共面。
普通场景的默认值、用户保存的开关、创建街道命令的撤销语义保持原有行为。

## 渲染行为

仅摄影地面使用独立的解析平面 program：按每个像素的相机射线计算与实际地面高度
的交点，复用原材质的纹理、法线、PBR、阴影、曝光和色彩处理。向上或背离地面的
射线仍显示天空，未生成可选择的额外场景实体。

近处地面的深度使用真实投影，继续支持物体遮挡、点击对焦和景深。超出远裁剪的地面
延续部分写入天空之前的最后一个深度值；其距离不能从深度缓冲恢复为大于 far 的
真实距离。没有增加相机 far 或降低场景模型的深度精度。地面下方的视角使用背面法线。

普通材质的 shader 不写 `gl_FragDepth`，避免为整个街道关闭 early depth rejection。
有限地面包围盒继续用于局部阴影接收体代理；颜色裁剪不会丢掉解析平面。
native 使用同一份 GLSL，独立绑定对应 program，并在正常没有阴影接收体时关闭该层
阴影，而非报错或退回 Python。

## 验证

`tests/visual_integrity_ground_audit.py` 通过 API 设置相机，逐像素使用独立的
double precision 射线/平面交点作比较。高度 1.7/20/100/300m × 俯角 15/45/90°，
`far=150`、`haze=0`，两后端共 24 组全部无向下射线露天。近处实际深度最大误差小于
`2e-5` 的回归阈值。两后端还通过向上天空逐像素不变、Scene v3 重载颜色与深度逐位
一致的检查。2026-10-18 使用仅含地面修复的新 DLL 重测，源码 HEAD/diff 哈希和 DLL
SHA-256 一并写入结果，不采用混有未验收阴影改动的旧 DLL 作为本次交付依据。

CPU 回归检查解析地面在 far 外仍会绘制、普通 Ground Mesh 仍正常裁剪，以及示例地面
确实低于每块道路路基。既有地面资源共享、场景根节点不变等 atmosphere 回归通过。
9 项 atmosphere 与 12 项 render-plan CPU 测试通过。C++ 测试验证正常可见物体、空接收体、
仅地面、非法地面及非法相机；已有 4 组 Python/native 拟合数值比较通过，最大误差
`3.41e-13`。局部阴影拟合、分辨率与过滤算法沿用本次修复前的实现。

`photographic_ground_gpu_smoke.py` 在两后端分别验证：前景平面遮挡地面、点击地面取得
`z=-.14` 的真实位置、景深不改写深度、开启阴影的 300m 俯拍、向上天空不可对焦，
以及从地面下方向上观察平面。使用 4x MSAA；前景测试采用平行平面，以消除解析像素
中心与 MSAA 实际解析样本位置不同造成的深度比较歧义，未放宽对焦阈值。

实际 Roman Street 保留原 24mm / near=.05 / far=200 / 4x MSAA、光照与色彩设置。
20m/100m/300m 正俯拍全部无天空深度像素；旧版分别有 24687/210747 个天空像素，
300m 时因空阴影接收体报错。修复后始终为 `native-photo`。

## 同画质帧时与限制

MX130、驱动 OpenGL 3.3 NVIDIA 581.08、1081×662，24 帧预热后每条轨迹测 120 帧，
分别记录 CPU 提交、GPU timer 和等待 GPU 完成的完整绘制时间。PNG 保存不在计时区间。
使用 `5d4b3a3` 的源码与原 DLL 作基线，未并入阴影稳定化或深度图缓存优化。

| 轨迹 | 修前帧时 P50/P95/P99 (ms) | 修后帧时 P50/P95/P99 (ms) | 修前/修后 GPU P95 (ms) |
| --- | --- | --- | --- |
| 平移 0.2m | 23.04 / 26.20 / 27.44 | 25.28 / 29.45 / 153.98 | 18.04 / 19.39 |
| 推进 3m | 23.66 / 25.33 / 120.86 | 25.73 / 29.64 / 154.70 | 17.65 / 19.52 |

显示街道以外地面带来绘制成本；本次测试 P95 仍低于 33.33ms，但两版均出现长帧，
修后 P99 更高。不能据此宣称所有帧达标、没有卡顿或完整编辑器稳定 30FPS。
本测试也不是阴影时间稳定性验收，第 3 项仍单独待办。

新验收产物位于 `captures/ground-bug2-20261018/`：`python/`、`native/` 是覆盖/重载检查，
`photo-python/`、`photo-native/` 是摄影路径回归，`street-{before,after}-native/` 保存实际
街道原图、相机、光照、Scene v3、完整 CPU/GPU 原始帧时及分位数。启动记录确认专用
进程的临时 GPU 偏好在测试退出时恢复。

```powershell
& F:/gymenv/python.exe -B tests/visual_integrity_ground_audit.py --output captures/ground-python --backend python
& F:/gymenv/python.exe -B tests/visual_integrity_ground_audit.py --output captures/ground-native --backend native
& F:/gymenv/python.exe -B tests/visual_integrity_street_acceptance.py --output captures/street-native --backend native
& F:/gymenv/python.exe -B tests/photographic_ground_gpu_smoke.py --output captures/ground-photo-native --backend native
```

native 模式要求真实 `native-photo`，禁止以 Python 回退作为验收。
