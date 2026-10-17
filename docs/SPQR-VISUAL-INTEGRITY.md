# SPQR Visual Integrity — 三项摄影穿帮修复

协作分支：`fix/spqr-visual-integrity-20261017`，来自
`feature/api-camera-trajectories-20261016`（PR #11），后者来自 `feature/spqr-phase1`。
本分支用于可复现的 Bug 修复，**不启动世界外围系统开发，不做大规模引擎重构**。

## 必须修复的三个问题

### 1. 砖缝透出天空（几何与遮挡）

**已修复的明确来源**：`mini3d/roman_assets.py` 中 `builtin:roman-arch`
的 18 块拱圈砌石使用 `+.0016/- .0016` 角度偏移保留放射状缝隙，
但没有完整的背衬。新增环形砂浆内衬，靠后于石块两面，且不跨越拱门真正的通道；
新增 `tests/test_roman_arch_integrity.py` 无 GPU 检查 17 个拱圈接缝及开放的拱孔。

**未解决/待确认**：用户实际看到的漏光是否来自这块程序化拱门，还是
`builtin:roman-house`、`builtin:roman-shop`、外部 glTF 城市资产或 GPU 剔除行为。
需定位模型路径、实体 ID、相机 pose；区分模型真空洞、三角面绕序、背面剔除、
alpha mask、Z-fighting、远裁剪引起的意外露天。
不要用全局 `doubleSided`、额外背景板或强雾来掩盖真实漏孔。

验收：静止相机正反、左右、低角度和高角度拍摄；非设计孔洞不得露出背景；
真正的门洞/拱门不能被错误封死。独立重新生成 Scene v3、从保存文件加载后结果一致。

### 2. 摄像机俯拍时地面突然露出天空（地平线/远景不连续）

可疑路径：
- `mini3d/atmosphere.py:prepare_photographic_scene`：地面是随相机平移的
  `size=2*camera.far` 正方形，仍受 Far Clip 限制
- `mini3d/sky_renderer.py`：全屏天空背景，按视线方向计算
- `mini3d/material_shaders.py`：地表雾由实际距离和 `hazeDensity` 混合
- `mini3d/shot_camera.py`：Shot 渲染及 Python/native 切换

先采样相机高度（1.7m / 20m / 100m / 300m）与俯仰角，
用相同 Scene/光照/曝光/尺寸，记录 `position`/`rotation`/`far`/`haze`，
确定是否确由 Far Clip 导致，而不是法线、透明、地面与实际城市场景几何重叠。
远处地面被裁剪前是否已经渐变到一致天空颜色？要求画面无突兀地平线、
高机位俯拍仍有合理地表。不得只把远裁剪距离无限增大、造成深度精度恶化。

### 3. 摄像机移动时静态阴影跳动（时间稳定性）

可疑路径：
- `mini3d/shadow_fit.py:receiver_matrix`：相机相关的接收体拟合，
  `lo/hi` 与 `scale` 随帧变化；当前没有显式 texel-snap 步骤
- `mini3d/shadow_map.py:ShadowMap.render`：camera matrix 作为缓存 key，
  摄像机一动就可能重新计算 ShadowMap
- `tests/shadow_motion_audit_20261010.py`：已有真实 GL 深度与固定 world
  probes 对照，支持 locked-fit 参考和动态 fit

先用固定场景、固定太阳、固定物体只移动摄像机，记录：
相机轨迹、每帧 `lightMatrix`、阴影图变化、world probe visibility、
阴影边缘突变及 GPU 耗时。使用 locked-fit 对照，区分 texel-grid 漂移、
拟合边界跳变、深度偏置/过滤等原因。
不能未经验证就提高 ShadowMap 分辨率、增大 PCF 模糊、扩大到整场景固定 shadow
bounds；这些可能牺牲已有画质和性能。Python 与 native photo 后端需分别验收。

## API 驱动的复现 / 测试

项目已拥有 `Mini3DAPI` 的相机与环境/阴影控制 API，
`tests/api_camera_trajectories.py` 提供可重用的 `linear_path` 和 `orbit_path`。
尽可能走 `api.set_shot_camera_pose`、`api.set_shadows`、`api.set_atmosphere`
等公共 API；只有 ShadowMap GPU 内部观测才用底层调用。
留存：`scene.json`、相机轨迹 `poses.json`、原始 PNG 和测量数据；这些
测试产物保存在 `captures/`，不要提交海量视频/原图至源码仓库。

Windows 命令：

```powershell
& F:/gymenv/python.exe -B -m unittest discover -s tests -p "test_roman_arch_integrity.py"
& F:/gymenv/python.exe -B -m unittest discover -s tests -p "test_api_camera_trajectories.py"
& F:/gymenv/python.exe -B -m unittest discover -s tests -p "test_*.py"
& F:/gymenv/python.exe -B tests/shadow_motion_audit_20261010.py --output captures/spqr-shadow-regression --frames 121 --resolutions 1024 2048
```

已有 PR #11 的 GPU 入门验收也可复用：
`tests/api_camera_trajectory_smoke.py --output captures/api-track --backend native`。
原生模式必须确认真实运行 `native-photo`，禁止默默回退到 Python。

## 性能底线

用户已报告当前版本稳定约 30 FPS / 33 ms；这只是底线，未来仍需性能余量。
每次修复保持同一场景、分辨率、渲染后端、GPU/驱动和摄影参数，
分别记录完整帧时间、CPU、GPU、P50/P95/P99 与阴影绘制成本，
剔除冷启动和第一次资源上传。**不能仅用 PNG 保存速度代表实时 FPS**。
任何突破 33.33ms 底线、导致画质下降的修复，不要合入；应报告原因并迭代。
`tests/test_roman_arch_integrity.py` 是 CPU 几何回归，不等于真实 GPU 验收通过。

完成流程：每个 Bug 一个独立提交，标明复现场景、修复依据、CPU/GPU 测试结果
及性能变化；如证据不足，保留诊断记录，不声称已解决。
