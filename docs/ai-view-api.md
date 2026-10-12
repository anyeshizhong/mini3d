# AI API 与用户当前画面

AI 应连接现有编辑器的 IPC 实例，使用同一个 Editor、Scene、Viewer 和命令历史。不要另建 Mini3DAPI 状态来代替用户窗口。

## 当前画面查询

`get_view_state()` 返回共享的 workspace（Arrange / Lighting / Shot）、view（Editor / Camera）、active_camera、editor_camera、shot_camera、viewport、render_mode 和 selected_ids。

运行中 IPC 将此查询安排在完成画面渲染后。displayed_frame 包含 frame_id、窗口宽高和该帧的 view_state；view_matches_displayed_frame 表示当前视图是否与该已渲染帧一致。无窗口的独立 API 返回 displayed_frame=null。

`screenshot(path)` 截取用户窗口的完整已渲染画面，包含 UI，返回对应的 displayed_frame。它与仅导出摄影相机成片的 `capture(path)` 用途不同。比较画面时以 screenshot 的元数据为准，不能把 capture 的摄影机位假定成当前编辑视图。

## 操作当前窗口

所有命令通过现有 JSON dispatcher / IPC 开放。

| 命令 | 行为 |
|---|---|
| set_workspace(workspace) | 使用与 UI 相同的工作区；离开 Shot 会返回编辑视图 |
| set_view(view) | Editor 显示导航相机；Camera 显示已有摄影相机并进入 Shot；未创建相机时拒绝 |
| frame_all() | 框取全部可见实体，并显示编辑相机 |
| focus_entity(entity_id) | 选中并框取指定可见实体，并显示编辑相机 |
| select_entities(entity_ids, primary_id=None) | 更新用户窗口相同的选择状态 |
| set_editor_view(preset) | front / back / left / right / top / bottom，并显示编辑相机 |
| set_editor_camera(position, target, fov_y=None) | 定位导航相机；继续使用现有鼠标导航和自动裁剪 |
| create_camera_from_view() | 复用 UI 的 Create Camera From View，复制当前编辑机位；需先显示 Editor |

这些视图命令不进入 Placement transaction，也不会清空已有撤销历史。参数在改变视图前验证。frame_all / focus_entity 调整编辑构图；随后进入 Camera View 时应用该构图。

示例（client 是连接现有窗口的 EditorClient）：

```python
client.call('focus_entity', entity_id='ent_000002')
client.call('set_workspace', workspace='Shot')
client.call('create_camera_from_view')
client.call('set_view', view='Camera')
state = client.call('get_view_state')
frame = client.call('screenshot', path='captures/current-window.png')
```

工作区现在由 Editor 持有，UI 直接读写同一状态。IPC 修改先于 UI 布局构建，避免切换视图时把新相机渲染到旧工作区的矩形中。

镜头预设校验接受 1e-6 mm 内的浮点误差，查询得到的 49.999999999999986 mm 可写回 50 mm 预设；任意非预设镜头仍被拒绝。

## 编辑与摄影预览衔接

从 Camera View 进入 Editor View 时，复制摄影相机的精确位置、旋转和视角到导航相机。中键旋转、Shift+中键平移、滚轮推近或拉远均继续使用当前构图。在 Camera View 中开始中键操作或滚轮操作，也会自动进入 Editor View。

再次进入 Camera View 会应用编辑后的构图，并保留光圈、对焦、景深、白平衡、色彩预设、画幅及抗锯齿设置。显式 create_shot_camera 创建的机位仍优先使用，不会被未提交的编辑机位覆盖。Update Camera From View 可显式应用当前构图。

set_view_lens(focal_mm) 和 set_view_aspect(name) 操作当前可见视图；顶部 Lens 显示当前编辑视角对应的焦距。Editor View 保持清晰以便编辑；景深在 Camera View 中预览。关闭景深且无编辑辅助图形时，同一 Shot 工作区中的两个视图使用相同输出尺寸及质量设置。

地面雾化只由实际 haze 决定，不再随相机 far 强制混入背景色。
