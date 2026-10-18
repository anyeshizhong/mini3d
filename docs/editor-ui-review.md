# UI 重构：评审、实现与验收

## 评审方式与范围

通过 Playwright 与 Google AI Studio 中的 Gemini 完成了两轮交互评审。第一轮提供实际 UI 布局、Python/Pygame/pyimgui 2.0（ImGui 1.82、无 docking）及 Scene/Commands/摄影输入契约；第二轮纠正建议中与代码不符的快捷键、相机和放置语义。浏览器拒绝本地图片上传，因此 Gemini **没有看到截图**，仅依据文字描述。未上传项目源码，也未开启 Google Drive 保存授权。

后续按用户要求，在 [Gemini 网页对话](https://gemini.google.com/app/f97ecf647f45c199) 中分批提交短需求和必要接口，取回资产库、全局工作区栏与紧凑工具栏候选代码。最终采用局部需求协作，不依赖整仓上下文。候选中发现了 ImGui 返回值、错误状态归属、溢出尺寸等问题，由主 agent 适配后接入；没有直接执行网页返回的代码。

首版已落实到 `mini3d/editor_ui.py`；启动呈现顺序位于 `mini3d/editor_runtime.py`。实际截图来自桌面 OpenGL 编辑器，不是网页原型。

## 当前已实现

- 全宽工作区栏及库开关、Undo/Redo；视口工具栏不再承担工作区导航。
- 资产名称与 Add to scene 固定在列表之前；模型列表和受限高度的预览详情分别滚动。Quick add 保留 Ground Mesh 与 Roman Street。
- Arrange 用工具选择器保留 Q/G/R/S 和 Surface Move，Place on Surface 单独显示；More 收纳坐标系、锚点、网格和取景动作。
- 左/右栏宽度及右栏上下分界可以拖动；忽略按下首帧的鼠标跳转位移，防止面板突然跳动。
- Outliner 使用独立滚动树与 Actions 菜单；Inspector 先名称/状态和 Transform，Formation 位于 Placement 之后。
- Lighting 参数集中于右栏，Render 菜单导航至工作区，移除重复浮窗；调整输入宽度以显示完整标签。
- Shot 顶部明确两种视图和 Guides；右栏集中创建/更新相机、镜头/比例和 Capture PNG。进入工作区不会隐式创建相机。
- 菜单外部点击关闭时捕获该次输入，不会同时选取场景；保留实际 image rect、letterbox、拖放和 Inspector 事务。
- 可见交互启动先呈现界面及 Preparing 提示，再准备首次场景；隐藏验收和单帧截图保持同步真图。详见 [启动黑屏分析](editor-startup.md)。

未实现任意 Docking、中文本地化或全新的灯光控件；下表包含后续设计方向，不代表每个高级分组已经改造。

## 已执行的验收

- 全部 `test_*.py`：433 项通过。
- `editor_ui_layout_smoke.py`：真实 SDL 鼠标滚动到资产 79、固定按钮添加、More 关闭不穿透、三条分界拖动、900×700 库隐藏恢复、显式 Shot 创建及切换、头栏 Undo/Redo、保存载入和干净 PNG，严格 native 路径通过。
- `editor_smoke.py`（auto，含 Wireframe 回退）、`editor_integration_smoke.py`：快捷键、文本捕获、GLB 拖放、拾取、Gizmo、Inspector 编辑通过。
- `lighting_ui_smoke.py`、`shadow_ui_smoke.py`：真实数值编辑、零方向拒绝、阴影开关及像素恢复通过。
- `editor_screenshot_smoke.py`：1440×900、900×700、最小化/恢复、三个工作区、独立截图 FBO 和干净照片通过。
- `native_legionnaire_editor_smoke.py`：实际 589879 三角形士兵的选择、11 次变换提交、Undo/Redo、保存重载、Shot 和借用纹理生命周期通过，结果在 `.runtime/ui-legionnaire-final/`。
- `photo_workflow_ui_smoke.py`：按 `docs/photo-workflow.md` 的雕像摄影配置重建测试场景，验证启动准备帧、重复表面对焦、黑边/天空拒绝、窗口缩放、IPC 色彩、交互降分辨率及静止预览/PNG/重载逐像素一致，结果在 `.runtime/ui-photo-statues-final/`。该脚本的固定取样点针对雕像场景；不能用任意街道场景替代其天空断言。

结果分别保存在 `.runtime/ui-layout-published/`、`.runtime/ui-screenshots-final/`、`.runtime/ui-lighting-verified/`、`.runtime/ui-shadow-verified/` 以及对应日志。自动输入验收不等于用户易用性认证，仍需实际试用反馈。

## 真实问题

在 `.runtime/ui-review-repro/resized-arrange.png`（900×700）可观察：资产列表占满左栏，选中资产的添加按钮藏在列表之后；视口工具占多行，网格等尾部选项被截断；右栏优先显示 Formation，而基本变换和后续操作需要滚动。Lighting/Shot 还存在顶部与 Inspector 的重复入口。

## 收敛后的首版方案

| 区域 | 首版行为 | 保留的契约 |
| --- | --- | --- |
| 全局任务栏 | Arrange / Lighting / Shot 始终可见；库开关、Undo/Redo 与全局动作归位 | 通过现有 `set_workspace` 切换；不创建第二份 Scene |
| Assets | 搜索、导入、选中名称与 Add 常驻；长列表独立滚动，预览详情可折叠 | 双击添加、资产拖放和现有稳定 ImGui ID 保留 |
| Arrange 视口 | 紧凑工具栏保留 Q/G/R/S；Surface Move 与 Place on Surface 分开；低频 Grid/Anchor 等放 More | 连续表面拖动与一次目标放置是两个动作；快捷键不改 |
| Lighting | 右栏作为设置主入口；优先预设、方位/仰角、强度，精细参数折叠 | Studio/Scene 预览与最终照片的区别明确；沿用已有大气与灯光接口 |
| Shot | 顶部明确 Editor View / Camera View 状态；右栏集中创建/更新相机、摄影参数和导出 | 进入 Shot 不自动建相机或进入 Camera View；更新按钮不在锁定预览下假装可用 |
| Object Inspector | 名称/可见性/锁定 → Transform → Placement → Formation/高级操作 | 单模板生成 Formation 仍可访问；字段编辑与拖动各占一次 Undo |
| 面板尺寸 | 可调整侧栏和 Outliner/Inspector 分界；小窗口优先保证视口和操作入口 | 实际 image rect 继续驱动拾取、Gizmo、对焦和拖放；工具栏不覆盖画面 |

900×700 时不能机械平铺所有按钮。即使左右 210/270 留出 420 宽，完整 Arrange 工具仍放不下，必须收纳次要项，或折叠资产库。1440×900 时展开常用操作。布局尺寸应由实际文字宽度和 ImGui 样式验证，而非照抄建议中的固定像素。

空相机流程：先在 Editor View 取景 → 明确点击 Create Camera From View → 切 Camera View 审阅并 Capture PNG。仅保留一台现有 Shot 相机，不扩展多相机、点光源、画中画等无关能力。

## 未采纳的 Gemini 建议

- W/E/R：项目实际为 Q/G/R/S，不能擅自改键。
- 把两种 Surface 操作合为磁铁开关：动作语义不同。
- 进入 Shot 自动切相机、多相机管理和画中画：与已有状态模型不符。
- 只在多选时显示 Formation：单模板也能生成阵列。
- 浮动栏和全局 `WantCaptureMouse` 的简单判定：图像窗口自身也会捕获鼠标，不能替代已有实际 image rect 的输入路由。
- `BeginDisabled`：当前 ImGui 版本未暴露此接口；禁用状态需使用实际可用 API 并验证鼠标、键盘都无法触发。
- 120px 同时放导入、搜索、预览、名称及添加按钮：高度估计不足；优先保证入口，预览按空间折叠。

## 验收要求

1. 900×700 和 1440×900 下，主操作无重叠或不可访问；资产 Add 无需滚到长列表末尾。
2. 点击工具栏/弹窗/分隔条不拾取场景；输入文本时不触发删除或工具快捷键；跨面板释放/取消手势正确。
3. 真正通过鼠标完成资产添加、选择、移动与 Inspector 修改；Undo/Redo 回到准确初始状态。
4. 工作区切换不丢选择、镜头或未显式保存的数据；Scene/API/Commands 仍共用原状态。
5. Shot 空状态有明确下一步；Editor/Camera View 状态和创建/更新动作可区分；PNG 无编辑辅助线并符合预览。
6. 实际 GL 窗口截图与交互回归之外，还需用户试用反馈；不能把像素非黑检查或单测通过当作易用性认证。

## 基线测试发生的原生崩溃

执行 `F:/gymenv/python.exe -B tests/editor_screenshot_smoke.py .runtime/ui-review-baseline` 时，测试进程 PID 13788 弹出 Windows 内存读取错误。该进程由本次基线检查启动，**当时未修改 UI 生产代码**。

首次测试已生成 `minimized-shot.png`，未生成 `resized-arrange.png`，故失败发生在两者之间；这段测试包含 frame24 的窗口 restore/resize。没有故障线程栈或 dump，不能断言具体崩溃调用就是 resize。

依据当时进程模块地址及本机 `python38.pdb`，截图地址 `0x7ffabe01f536` 对应 `python38.dll + 0x17f536`，符号为 `pymalloc_alloc + 0x56`。这是检测到异常的位置，**不是造成内存破坏的代码定位**，不能因此归咎于 Python、C++ 或驱动。首次进程退出前未取得 dump。

后续使用 `.runtime/repro_ui_crash.py` 开启 faulthandler，局部设置 Windows 错误模式避免重复弹出 JIT 对话框；只影响测试进程，不改全局系统设置。完整复跑 1 次、普通分配器重复 5 次、`PYTHONMALLOC=debug` 加 tracemalloc 重复 5 次，以及 `MINI3D_REQUIRE_NATIVE_RENDER=1` 严格原生重复 1 次均通过。日志与截图在 `.runtime/ui-review-{repro,repeat1..5,allocdebug1..5,strictnative}/` 及 `.runtime/ui-crash-*-trace.log`。这 12 次通过**不能消除首次失败，也不构成修复**。

继续重复时，`.runtime/ui-review-stress5/` 再次失败，退出码 `-1073741819`；`.runtime/ui-crash-stress5-trace.log` 捕获主线程位于 `editor_runtime.py:175` 的 `pygame.event.get()`，而不是 native render 或 ImGui 调用。

根因在测试脚本的窗口包装对象生命周期：[Pygame 2.6.1 `Window.from_display_module`](https://github.com/pygame/pygame/blob/2.6.1/src_c/cython/pygame/_sdl2/video.pyx#L212) 将 Python wrapper 的裸指针存入 SDL 的 `pg_window`；borrowed wrapper 析构直接返回，没有清空该数据。[事件转换](https://github.com/pygame/pygame/blob/2.6.1/src_c/event.c#L1233) 随后读取并增加这个对象的引用计数。测试 frame24 的局部 `window` 在回调返回后可能被释放，后续窗口事件就会访问悬挂的 Python 对象。普通分配器的内存复用使故障随机出现。

修正 `tests/editor_screenshot_smoke.py`、`tests/editor_smoke.py`、`tests/file_dialog_smoke.py`，将 wrapper 存入测试全程存活的 `state['window']`，保持到 `run()` 完成 SDL 退出之后。生产编辑器没有调用 `from_display_module()`，这次不需要修改 C++ 渲染或其资源管理。`photo_workflow_ui_smoke.py` 原本已经持有这个引用。

修正后 `.runtime/ui-review-fixed1..5/` 连续 5 次完成恢复、缩放、三个工作区及 PNG/IPC 截图检查，均通过。先前 12 次未复现不是修复依据；这里的依据是故障栈、上游对象归属契约与具体引用生命周期修正。

旧的 `docs/photo-workflow.md` 也记录过 SDL Window 包装对象导致的访问违规，当时仅摄影脚本已保活。此次将同类模式修正到其余三个脚本，并在 `docs/ai/CAUTIONS.md` 保留跨脚本约束，便于按 `from_display_module`、`SDL`、`访问违规` 检索。
