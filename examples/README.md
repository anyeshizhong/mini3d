# 示例入口

从项目根目录运行。所有示例的导入均不会创建窗口。

| 命令 | 用途 | 必需资源 | 旧入口 |
| --- | --- | --- | --- |
| `python -B -m examples.primitives` | 球体、圆柱、方块、STL；Tab 选择，IJKL/UO 移动旋转 | 随仓库提供的 STL | `1.py` |
| `python -B -m examples.circular_motion` | 方块在 XZ 平面做圆周运动 | 随仓库提供的 STL | `1 copy.py` |
| `python -B -m examples.urdf_car` | 小车层级和关节；Tab 切换，Z/X 调整 | 本地 `model/07_urdf_car/` | `2.py` |
| `python -B -m examples.triangle` | OpenGL 立即模式三角形实验 | 无；需要兼容模式 OpenGL | `3.py` |

前三个示例共用 `legacy_scene.py`，相机和渲染器复用 `mini3d` 引擎。旧入口仅转发到这些模块。

`legacy_scene.py` 保留原示例的标量缩放、`[pitch, yaw, roll]` 旋转及 `extra @ T @ R @ S` 变换约定，供 URDF 适配使用。编辑器的 `mini3d.scene` 使用向量缩放、XYZ 旋转和不同的导入基底组合顺序。新增场景功能应使用 `mini3d.scene`，不要向示例适配层添加第二套编辑器实现。

相机：拖动环绕，Shift+拖动或右键平移，滚轮缩放；F 聚焦、Home 全景、1/3/7 预设、R 重置、Esc 退出。
