# Mini3D

基于 Python、Pygame、NumPy 和 OpenGL 的三维展示原型，支持 STL 模型、基础几何体、URDF 实体树和关节运动。

## 运行

本机工作环境为 `F:/gymenv`（Python 3.8）。在 PowerShell 中执行：

```powershell
& F:/gymenv/python.exe "F:/python_project/mini3d/1.py"
& F:/gymenv/python.exe "F:/python_project/mini3d/1 copy.py"
& F:/gymenv/python.exe "F:/python_project/mini3d/2.py"
```

- `1.py`：球体、圆柱、方块和 STL 模型；Tab 切换物体，I/J/K/L 平移，U/O 旋转。
- `1 copy.py`：方块在 XZ 平面做圆周运动；Tab 切换聚焦目标，启动视野覆盖整个运动路径。
- `2.py`：小车 URDF；I/J/K/L 移动整车，U/O 旋转整车，Tab 切换车轮关节，Z/X 调节关节角。

资源路径相对脚本文件解析，可从其他工作目录启动。依赖为 `pygame`、`numpy`、`numpy-stl`、`PyOpenGL`，主渲染器需要支持 GLSL 3.30 的 OpenGL 环境。

## 相机操作

三个示例统一使用 Orbit 相机，启动时自动取景。

| 操作 | 功能 |
| --- | --- |
| 左键或中键拖动 | 围绕观察目标旋转 |
| Shift + 左键/中键拖动，或右键拖动 | 沿屏幕平面平移 |
| 鼠标滚轮 | 按比例拉近/拉远，保持镜头视角不变 |
| F | 聚焦当前选中的物体及其子节点 |
| Home | 显示全场景，包括地面 |
| 1 / 3 / 7（支持小键盘） | 前视 / 右视 / 顶视 |
| Ctrl + 1 / 3 / 7 | 后视 / 左视 / 底视 |
| R | 恢复启动视角 |
| Esc | 退出 |

数字键 2 也可切换顶视，兼容原实验入口。`2.py` 初始聚焦整车；Tab 选中车轮后，F 聚焦该车轮，R 恢复启动时整车视角。`1 copy.py` 的 F 聚焦物体当前所在位置，不持续跟随移动；Home 也按当前姿态取景。

世界坐标为 Z 向上；前视从 +X 看向目标，右视从 +Y 看向目标。预设视角仍使用透视投影。原有 WASD/方向键飞行相机已由鼠标轨道操作替代；Fly、Follow 和正交投影留待后续实现。

## 相机结构

- `mini3d/camera.py`：纯相机，只存位置、旋转矩阵、垂直视角与裁剪面，不处理输入，不保存 orbit target。
- `mini3d/orbit_controller.py`：管理 target、distance、yaw、pitch；提供旋转、平移、缩放、自动取景与六向视角。
- `mini3d/viewer.py`：连接场景和输入；计算包含层级变换的世界包围盒，提供 `focus(entity)`、`frame_all()`、`set_view(name)`、`reset_camera()`。

```python
from mini3d.viewer import Viewer

viewer = Viewer(scene, width, height)  # 自动显示全场景
viewer.selected_entity = robot
viewer.focus(robot)
viewer.save_camera()                 # 可选：把当前视角设为 R 的恢复位置

# 事件循环：应用自己处理退出、渲染器 resize 和实体控制
viewer.handle_event(event)
scene.update()
renderer.render(scene, viewer.camera)
```

相机使用标准 OpenGL 坐标（右、上、-Z 朝前），旋转仅存一份 3×3 正交矩阵，方向和 view matrix 都由此推导。`fov_y` 的单位是度，替代原先以像素为单位的 `camera.fov`。Renderer 每帧根据窗口宽高计算投影；CPU 渲染器也已适配。

鼠标相对位移直接按像素处理，不再乘帧间隔；持续按键控制的物体/关节运动使用秒为单位的 `dt`。聚焦考虑窗口横纵比例及模型深度，并随模型尺寸调整缩放范围与 near/far。

## 验证

在项目目录中执行：

```powershell
& F:/gymenv/python.exe -B -m unittest discover -s tests -v
& F:/gymenv/python.exe -B tests/render_smoke.py
```

单元测试覆盖投影、不同尺度的自动取景、层级包围盒、拖拽、预设、重置和 resize。第二条在隐藏 OpenGL 窗口中运行三个真实示例，注入导航事件并检查模型像素及 GL 错误；需本机图形驱动，可追加截图输出目录参数。
