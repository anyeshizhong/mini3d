# Editor 集成审计

范围：`feature/editor-viewport` 的入口、模块连接与输入仲裁。此次没有增加动画、灯光、物理、glTF 特性，也没有重构 Renderer。

## 审计结果与修复

原来的 Editor 主循环已经连接了各模块，且没有调用 `Viewer.handle_event()`，因此实际调用链中不存在左键同时 Orbit 和选择。风险在于 Viewer 的默认绑定没有显式隔离，且 `Editor.handle_event()` 忽略了 UI 提供的 `mouse_captured`：已经开始的相机或 Gizmo 拖拽可能继续穿透 UI。

- 新建 `editor_app.py` 作为统一命令行入口；旧 `editor.py` 仅转发到同一个 `main()`，没有第二套循环。
- Editor 使用 `Viewer(input_enabled=False)`。即使误把原始事件传入此 Viewer，也不会触发旧的左键 Orbit、右键 Pan 或 R 重置绑定。原有三个独立示例维持默认绑定。
- `Editor.handle_event()` 独占场景输入：释放/失焦先结束手势，其次处理 UI 捕获，最后才进入选择、Gizmo 或相机。
- 相机拖拽与 Gizmo 拖拽互斥。UI 捕获鼠标或开始资产拖放时，已有视口手势结束；缺失松键事件也可由后续 motion 的 buttons 状态解除，避免持续拖拽。

## 实际模块连接

```text
editor_app.main
  -> mini3d.editor.run
       -> Editor: Scene + AssetCache + Viewer + TransformGizmo
       -> EditorUI: 资产拖放 / Outliner / Inspector / 捕获状态
       -> Editor.handle_event: Picking / Gizmo / Viewer.controller
       -> Scene.update: 同一实例树的世界矩阵
       -> RenderTarget.bind
       -> GLRenderer.render -> MaterialRenderer: glTF/STL 材质
       -> MaterialRenderer.render_selection: 选中轮廓
       -> EditorUI 的视口 image 使用 RenderTarget.texture
       -> ImGui backend 合成界面
```

资产的拖放 payload 由真实 ImGui source/target 传递，`Editor.drop_asset()` 实例化缓存资产并加入 Scene。Picking 返回根实例，Gizmo 修改其 TRS；Inspector 读取并编辑同一个实例，不保存另一份变换副本。

| 输入 | 唯一接收者 |
| --- | --- |
| 左键点击 | 先尝试 Gizmo 命中，否则 Picking 选择 |
| 左键拖动 | 已命中的 Gizmo；普通选择拖动不会改变相机 |
| 中键拖动 | Viewer.controller.orbit |
| Shift + 中键拖动 | Viewer.controller.pan |
| 滚轮 | 视口悬停且 UI 未捕获时 zoom；Gizmo 拖动期间不改变相机 |
| UI 捕获鼠标 / 模态框 / Assets 拖放 | 不执行场景鼠标操作 |
| UI 捕获键盘 | 不执行场景快捷键 |
| 松开鼠标 / 窗口失焦 | 清理拖拽，不受 UI 捕获阻挡 |

ImGui 会把作为窗口内容的视口 image 也计入原始 `want_capture_mouse`；因此使用 `EditorUI.mouse_captured` 作为仲裁结果，允许普通视口 image 悬停，仍阻止活动输入控件、菜单和资产拖放。真实测试覆盖了 Inspector 控件保持活动、鼠标已移入视口的情况。

## 验证

```powershell
& F:/gymenv/python.exe -B -m unittest discover -s tests -v
& F:/gymenv/python.exe -B tests/editor_integration_smoke.py
& F:/gymenv/python.exe -B tests/editor_smoke.py
& F:/gymenv/python.exe -B tests/render_smoke.py
& F:/gymenv/python.exe -B tests/stl_render_smoke.py
& F:/gymenv/python.exe -B tests/file_dialog_smoke.py
& F:/gymenv/python.exe -B editor_app.py
```

单元测试 79 项通过。新增 `editor_integration_smoke.py` 在临时目录生成 GLB，并通过统一入口的真实 ImGui/OpenGL 循环驱动：Assets 鼠标拖放 → Scene 实例 → 模型像素 → 几何选择 → Gizmo 移动 → Inspector 数值同步 → Inspector 反向编辑。没有伪造 payload、替换拾取或跳过渲染；只注入鼠标/键盘事件并记录 UI 控件位置和值。另检查了左键相机不动、中键 Orbit、Shift+中键 Pan、滚轮及 UI 捕获，逐帧检查 GL 错误。

本机原有编辑器交互、三个旧示例、STL 三模式和 Tk 文件对话框检查均通过。外部模型未安装时，相关资产测试会标记跳过。

## 已知问题与当前边界

- UI 先提交本帧控件，再处理视口事件，所以 Gizmo 导致的变换在 Inspector 下一帧显示；两者引用同一实体，不存在长期状态分叉。
- 模型解析与首次 GPU 上传仍在主线程；大型资产可能短暂停顿。文件选择对话框本身已在独立进程中，不阻塞渲染。
- 拾取按三角形几何进行，不判断贴图透明像素；透明区域也可能被选中。
- 原有示例的 numpy-stl 自动检测二进制文件时可能打印 ASCII 尝试失败信息，但会继续成功加载；Editor 的 STL 入口已显式检测二进制格式。
- 固定面板、根实例级选择、无撤销栈等既有边界保持不变；本次没有扩展这些功能。
