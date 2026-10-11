# 编辑器画面与性能改进（2026-10-11）

本轮按用户“请你改进”的要求处理已记录的问题，继续使用原来的 Scene、Mini3DAPI、Commands 和 GLRenderer。开始时没有运行中的编辑器；复现使用先前保存的用户场景，测试窗口均由测试脚本临时创建，不代表用户本人已经完成手工验收。

## 牛油果疑似穿模

实际资产、位置、旋转、缩放和相机参数保存在 `tests/fixtures/editor_quality_scene.json`。桌面与牛油果底部的 bounds 差约 `-1.08e-7`，没有将物体额外抬高或改变放置算法。

根因之一是聚焦很小的物体后再远离：巨大地面包围盒跨过相机，近裁剪面继续按旧焦点半径缩小。旧场景 near 为 `0.000004040465`，far 为 `55.02785`，深度精度不足，导致桌面错误遮挡牛油果和其他几何。

跨眼平面的场景现在按当前导航距离设置 near，并单独检查真正位于相机前方的最近包围盒，保留近处的小物体。相机位置、视角、焦点和 Shot 显式裁剪参数不变。原场景 near 为 `0.002954536`，far 不变；牛油果可见像素从 43 增至 71。新增测试覆盖微小、正常和巨大尺度以及跨眼地面旁的近处物体。

## 桌子阴影

编辑视图原来把整个约 124×71 的地面纳入一张阴影图，摄影相机却已经有视锥 receiver/caster fitting。现在两种相机共用已有 fitting，传入实际视口比例，并保留所有潜在场外投影物体；不能完成 fitting 时仍回退整场景 bounds。

原场景 2048 阴影图的光空间宽高从约 `112.91×43.61` 缩至 `56.02×19.49`。同时使用深度比较采样器做线性 PCF，减少阴影边缘的方块跳变；关闭 PCF 时按 texel 中心进行硬比较。[Khronos GLSL 规范](https://registry.khronos.org/OpenGL/specs/gl/GLSLangSpec.4.60.html) 描述了 shadow sampler 的深度比较语义。

这不是级联阴影或接触阴影实现。大地面、低角度阳光和细桌腿仍受到单张阴影图分辨率与 bias 的限制；移动相机也会改变 fitting。已改善块状边缘，没有宣称所有阴影细节问题都已解决。

## Editor View / Camera View

Shot 工作区创建相机后，两种视图都按摄影画幅显示，Editor View 使用摄影预览相同的 Scene 光照、材质、阴影和抗锯齿路径。保留可移动的编辑相机与固定的摄影相机，编辑辅助线仍只用于编辑；PNG 仍按摄影相机原有分辨率输出。Arrange/Lighting 的 Studio 预览选择继续保留。

测试在相同位姿、镜头、比例和输出尺寸下比较编辑预览与真实 `render_shot`，像素完全一致。实际屏幕预览与更高分辨率 PNG 的采样细节允许不同。复制编辑视角产生非预设焦距时，Lens 显示真实焦距，而不再误显示为最近的 24/35/50/85 mm。

## 40 士兵性能

该资产单个约 589879 三角形；40 个加地面约 23595162。持续旋转并绘制阴影时，几何提交仍可达到约 47190324 三角形/帧，Intel UHD 620 依然吃力。本轮保留模型和摄影质量，没有删除物体、减少模型面数或更换资产。

- 主循环保留已经绘制的视口纹理，仅当相机、尺寸、场景、材质、选择或渲染设置变化时重绘。每个 UI 帧仍处理用户输入、IPC 和 UI 合成，截图也继续获取最新完整编辑器帧。
- 阴影深度图比较所有相关输入，静止时复用；物体、相机、光方向、尺寸或 alpha cutout 变化时重新生成。
- 共享材质的 opaque 绘制集中设置材质；透明物体继续按远近排序。相同线性变换在当帧复用 normal matrix。
- Entity 的矩阵计算比较公开数组的实际内容，支持直接修改、父节点变化、重新挂接、撤销/重做；导航包围盒角点按 bounds 内容复用。

实测数据（Intel UHD 620、40 个真实士兵、2048 阴影）：

| 测量 | 之前 | 本轮 |
| --- | ---: | ---: |
| 真实 Editor Runtime 静止 UI 帧中位数 | 264.34 ms | 16.70 ms |
| 前 13 帧中的 Scene 绘制次数 | 13 | 1 |
| 强制逐帧绘制、静止阴影 | 258.62 ms | 138.64 ms |
| 持续旋转并强制绘制阴影 | 288.53 ms | 250.32 ms |

前两项最直接反映静止时操作 UI 的改善。后两项采样少且受 GPU 温度和调度影响，只用于确认工作量与剩余瓶颈，不是稳定 FPS 保证。要让持续旋转 40 个高模士兵也流畅，仍需要单独处理交互 LOD/实例绘制与阴影绘制量。

## 验证与证据

- 296 项 headless 测试通过，包括原有场景保存、历史、API、裁剪、材质与阴影测试。
- `tests/editor_quality_smoke.py`：实际桌子/牛油果场景、可见像素、移动画面变化、阴影缓存失效和两种视图像素一致。
- `tests/editor_retained_view_smoke.py`：真实 40 士兵主循环，API 移动、撤销和直接改光照均重绘；撤销后视口像素恢复。
- `tests/editor_screenshot_smoke.py`：最小化、两个 Shot 视图、缩放、其他 read FBO 和摄影 Capture 后截图。
- `tests/live_editor_ipc_smoke.py`：同一实例中通过注入鼠标事件移动士兵，IPC 读到新位置，API 再移动并更新画面，撤销/重做、灯光、相机、4× MSAA、Capture 和保存加载均通过。这是自动化验收，尚未替代用户手动移动的验收。
- `tests/shadow_smoke.py`：世界空间投影、alpha mask、ambient/emission/unlit、比例、bias/PCF、GL 状态恢复和 Camera View/PNG 一致。

本地前后图片：`captures/editor-quality-scene-before-02/user-view.png`、`captures/editor-quality-scene-after-01/user-view.png`。性能报告：`captures/editor-retained-before/report.json`、`captures/editor-retained-after-01/report.json`。自动 IPC 验收：`captures/live-ipc-quality-final/results.json`。

文中 captures 目录是本地验证输出，不随源码提交；对应测试脚本可重新生成证据。

重启项目中的编辑器即可加载代码改动。相机必须先创建；在 Shot 工作区比较两种视图时，应保持相同镜头、画幅和位姿，移动编辑相机后需再次 Create Camera From View 才会更新固定摄影相机。改动位于 `feature/live-editor-ipc` 分支，合并 main 前仍需用户手动验收。
