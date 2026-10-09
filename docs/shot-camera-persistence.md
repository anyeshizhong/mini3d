# Shot Camera 场景持久化

2026-10-09，分支 `feature/shot-camera-persistence`，基于 `52ee1ee`。

Scene v3 保存独立摄影相机；重新启动 Editor 或新建 Mini3DAPI 后加载场景，可直接进入 Camera View 或 Capture，无需重新创建相机。Editor 导航相机仍使用原有 `camera` 字段。

## 格式与行为

新增可选顶层 `shot_camera` 对象：`position` 为三维位置，`rotation` 为右手正交 3×3 旋转矩阵，`aspect` 为 `16:9`、`3:2`、`4:3` 或 `1:1`，另存 `focal_mm`、`fov_y`、`near`、`far`。直接保存 FOV 和完整旋转，保留非预设镜头以及 roll；按 36mm 水平画幅校验焦距与 FOV 一致。输出尺寸沿用画幅预设，不另存可冲突的宽高。

- 没有相机时保存 `null`。加载 v1/v2/v3 的缺失字段或 `null`，清除上一场景摄影相机并返回 Editor View。
- 加载有相机的场景时保留当前视图选择；全新 Editor 默认进入 Editor View，可切换 Camera View。
- 成功加载清除待执行 Capture 和旧 `last_capture`。视图选择、构图网格、历史截图路径不属于摄影相机持久化参数。
- 非法类型、布尔/字符串数值、非有限数、错误形状、非正交或反射矩阵、无效裁剪面、冲突的焦距/FOV、非有限投影均在替换当前场景前拒绝。失败保留场景、相机、历史和待拍摄状态。
- Python API 与 JSON dispatcher 复用 Editor 保存/加载，`get_shot_camera` 返回格式保持兼容；查询结果与内部状态分离。

生产代码修改沿用断线前已有实现：`mini3d/shot_camera.py`、`mini3d/editor.py`、`mini3d/api.py`。本次接续补充跨进程 GPU 验证和文档。

## 验收

在 `F:/gymenv/python.exe`（Python 3.8.20）、Intel UHD Graphics 620 上运行：

```powershell
& F:/gymenv/python.exe -B -m unittest discover -s tests -v
& F:/gymenv/python.exe -B tests/shot_camera_persistence_smoke.py
& F:/gymenv/python.exe -B tests/photo_smoke.py captures/shot-camera-persistence/photo-regression
```

- 全部 239 项单测通过，包括新增的 10 项持久化测试；覆盖全部 4×4 镜头/画幅组合、非预设 FOV、独立 Editor 导航、旧场景兼容、非法输入及失败状态保护。
- 新 GPU 测试使用仓库自带 STL 立方体和 Ground，开启方向光与阴影。保存进程退出后，在全新进程通过 JSON API 加载，并禁止调用 API 创建相机方法，直接输出 35mm、4:3、1920×1440 PNG。
- 重启后输出与保存前逐像素一致，差异像素 **0**；加载后切换视图并执行 Editor orbit/pan/zoom，再拍摄差异像素仍为 **0**。截图已查看，立方体、地面及阴影可见。GL 错误检查通过。
- 原摄影 UI 回归通过：实际按钮输入、四种镜头/画幅、6 张 PNG、预览一致性、构图网格不进入照片、相机独立性。

证据位于本工作树 `captures/shot-camera-persistence/`：`before.png`、`after.png`、`after-navigation.png`、`scene.json`、`resaved.json`、`state.json` 和 `result.json`。截图和生成场景由既有 `.gitignore` 排除，不属于源码交付。

本轮验证针对持久化和摄影流程；未重新进行 Rome 场景构图或阴影质量验收。
