# Roman Legionnaire 原生导入卡顿：复现与修复验收

实际复现使用 `model/05_roman_soldier/roman_legionnaire.glb`，不是替代模型。
文件 29,411,784 字节，589,879 个三角形、6 个网格，两张 4096×4096 纹理。
Editor 原始比例 1 的初始位置为 `[1.297401538, 2.509000647, 1.735865951]`，
与用户“导入或选中后未响应”截图中的 Inspector 数值吻合。

检索入口包括 `docs/live-editor-test-notes.md` 的士兵卡顿记录、
`docs/editor-quality-improvements.md` 的历史真实资产测试，以及当前
`native_renderer`、`capture_texture`、`write_scene_binary`、`kMaxItems` 调用链。
历史 Python 渲染成绩没有用于替代此次 native Arrange 实测。

## 修复前的实际失败

同机 Intel UHD Graphics 620、Python 3.8.20、846×662 视口，逐阶段日志记录：

| 阶段 | 耗时 / 结果 |
| --- | --- |
| CPU 导入并选中原始 GLB | 0.113 秒 |
| 两张纹理的浮点 RGBA 读回 | 0.413 + 0.302 秒 |
| 整体材质导出 | 1.948 秒（包含上述读回） |
| `write_scene_binary` | 11.347 秒 |
| 原生加载 | `array count exceeds safety limit at byte 56` |

4096² RGBA 纹理的顶层已有 67,108,864 个 float，超过 loader 通用数组上限
20,000,000。两个完整 mip 链的浮点纹理数据约 682.7 MiB，还会经历序列化复制。
主线程先支付读回、复制和文件写入成本，再遇到加载错误；auto 模式的 Python
回退不能消除已经发生的阻塞。这解释了为什么可见模型不代表 native 加载成功。

另一个实测问题是纯变换会重新创建 native renderer。仅修复纹理传递后，移动帧
仍耗时 2.399 秒；因此同时补充了实例矩阵的增量同步。

## 当前实现

- 在线 bundle v2 只记录同一 GL context 中的纹理 target/handle，省去像素读回、
  浮点展开、落盘和重复上传；原来的 v1 离线入口保留并拒绝 v2。
- native 不改借用纹理的采样/存储，也不在正常关闭、构造失败或重建时删除它。
  Python MaterialRenderer / Environment 所有者在 native handle 销毁后才释放纹理。
- 纯变换批量更新所有变化的子网格 world/normal/mirrored 数据，整批校验后提交，
  并失效阴影缓存；选中和取消选中不导出资源。拓扑、显隐、材质变化仍可重建。
- 新 Python 适配器要求 DLL 提供 shared-create 和 transform 两个入口；本机 DLL
  已重新构建并复制到 `native/spqr_photo.dll`。已有进程需保存场景并重启后加载。

协议细节见 [FORMAT](../spqr-native/FORMAT.md) 和 [运行说明](../NATIVE-PHOTO.md)。

## 实测与必要回归

真实完整 Editor Runtime 的 `tests/native_legionnaire_editor_smoke.py` 已通过，
包括原比例导入、取消/重新选中、11 个连续 SDL 手柄移动帧、撤销重做、保存重载、
Arrange/Shot 切换、借用纹理和 IBL cube 的生命周期、构造失败清理，以及离线 v1
create/destroy。鼠标手势为测试注入，未声称人工操作验收。实际截图已查看。

在该次 28 帧测试中，首次 native 场景准备为 3.746 秒；12 个拖动/释放帧
P50=16.57ms、P95=22.33ms、最大 28.92ms。选中和移动期间 bundle 构建计数保持 1。
另一次逐阶段 profile 的 bundle 写入为 0.073 秒，文件 23,353,550 字节，移动帧为
0.014 秒。首次资源上传/着色器准备仍有冷加载成本；短场景结果不是所有场景的 FPS 保证。

已执行：

```powershell
F:/gymenv/python.exe -B -m unittest discover -s tests -p "test_*.py"
F:/gymenv/python.exe -B tests/native_legionnaire_editor_smoke.py .runtime/legionnaire-editor-lifecycle
F:/gymenv/python.exe -B tests/native_arrange_gpu_smoke.py .runtime/legionnaire-fix-arrange-regression-final2
F:/gymenv/python.exe -B tests/native_photo_gpu_smoke.py .runtime/legionnaire-fix-shot-regression
$env:MINI3D_REQUIRE_NATIVE_RENDER='1'
F:/gymenv/python.exe -B tests/live_editor_ipc_smoke.py --output .runtime/legionnaire-fix-live-ipc
```

433 项单测通过；Arrange 的 16 项 GPU 检查通过，包含错误变换批次原子拒绝、
镜像/零缩放增量更新与重建颜色/深度一致。Shot 1920×1080 预览与 PNG 逐像素一致。
真实士兵的跨进程 IPC、注入手柄、共享 Undo/Redo、4x MSAA、景深和照片重载一致检查通过。

本地原始证据不随源码分发，可由上述入口重新生成：

- [修复前逐阶段日志](../.runtime/legionnaire-before-fix.log)
- [修复后逐阶段 profile](../.runtime/legionnaire-transform-fix/profile.json)
- [完整士兵 Editor 报告](../.runtime/legionnaire-editor-lifecycle/report.json)
- [实际编辑器截图](../.runtime/legionnaire-editor-lifecycle/arrange.png)
- [Arrange GPU 报告](../.runtime/legionnaire-fix-arrange-regression-final2/report.json)
- [Shot GPU 报告](../.runtime/legionnaire-fix-shot-regression/report.json)
- [真实士兵 IPC 报告](../.runtime/legionnaire-fix-live-ipc/results.json)
