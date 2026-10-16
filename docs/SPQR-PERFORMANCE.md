# SPQR Performance：同画质减少每帧准备与提交

本轮沿用 Scene / Commands / API / AssetCache / Shot。未换引擎、安装库或引入原生扩展，也没有降低默认分辨率、阴影质量或三角形数量。代码保持本地待验收，不自动提交。

## 实现范围

- 阴影：同一 Mesh 的不透明实例合并为一次 `glDrawElementsInstanced`。颜色相机剔除仍不限制阴影投射者；MASK 仍测试 alpha，BLEND 仍不投射透射阴影。
- 颜色：相同 Mesh、相同材质、相同绕序的连续不透明记录批量绘制。保持原有稳定排序，不跨其他 Mesh 重排，以保护共面边缘的深度顺序。MASK / BLEND 走原路径，透明深度排序不变。
- 实例传入各自模型矩阵和 pseudoinverse 法线矩阵，支持镜像、非均匀缩放及扁平物体。每个建筑仍是独立可选、可改、可保存的实体。
- 每个 Mesh 的实例 VAO/VBO 由 MaterialRenderer 持有，独立于单物体与选择轮廓 VAO；没有为每个建筑分配永久 VBO。阴影借用此缓存。`release/close` 在当前 GL context 中释放，可再次按需构建。
- 实例数据值相同时复用已上传内容；改变时使用流式 buffer 上传。颜色和深度各自保留实例数据，避免互相覆盖后重复上传。
- 几何缓存比较完整 bounds/world 数值，不依赖仅由 UI 命令设置的 dirty 标记。父变换、公开数组原地修改、Undo/Redo、模型替换与重载均会重新准备。导航深度仍逐相机计算，但复用静态世界角点并批量求深度。
- 法线矩阵/绕序缓存最多 256 种线性变换。阴影局部角点、包围平面与逆矩阵最多 2048 条值记录；改变相机和灯光时仍重做接收者/投射者相交与最终拟合，不盲目缓存最终阴影。
- 部分相交盒的边/平面裁剪改成 NumPy 批量运算，保留原容差、保守规则、退化回退以及标量参考算法。无需 C++ 就能减少大量小调用。
- 材质 pass 只在状态变化时重设混合、深度写入、剔除和绕序。GL 状态快照读取后恢复 active texture，避免读取快照本身改变调用者状态。

## 诊断开关

内部 Python 调试可设置 `renderer.gpu_instancing = False`，使颜色/阴影回到逐物体提交；这不是对用户新增的场景选项，不写入存档。比较阴影时须移动相机或清空 `renderer.shadow_map._cache_key`，否则未变化画面的正确行为是复用已有阴影贴图、零次重绘。

关闭实例化并不会关闭几何缓存或批量裁剪，因此完整版本性能比较必须使用修改前的源码快照。不要将此开关的结果写成完整旧版性能。

## 复现

使用项目已有 Python/OpenGL 环境。先保存本轮修改前的完整源码快照（至少 `mini3d` 包及 `model/manifest.json`），以下 `BASELINE` 指快照项目根，输出目录应为新目录：

```powershell
python -B -m unittest discover -s tests -p 'test_*.py'
python -B tests/spqr_performance_smoke.py --baseline-project BASELINE --output captures/performance-images
python -B tests/spqr_engine_benchmark.py --baseline-project BASELINE --output captures/performance-timing.json --sizes 85 118 170 340
python -B tests/spqr_editor_performance.py --baseline-project BASELINE --output captures/performance-editor
```

GPU 回归比较完整照片与阴影深度，覆盖屋顶两侧/下沿、街口、星空/月夜、太阳 −90/0/90/3 度、摄影地面、透明/MASK/legacy、镜像/非均匀/零缩放、直接数组修改，以及选择轮廓和资源释放/重建。

性能脚本在同一 GL context 交替运行两个完整版本，三轮反转顺序，预热后取样；固定 960×540、1×AA、2048 阴影。四条移动路线测 85 根实例，并以 118/170/340 根实例测沿街和俯瞰；全部规模现由统一的 `spqr_engine_benchmark.py` 的 `--sizes` 控制，原有分规模脚本已删除。记录每帧、P95、draw、三角形和 GPU 时间线；`glFinish` 完成延迟不等于完整编辑器呈现 FPS。

编辑器脚本额外运行真实 SDL/ImGui/runtime，1440×900 窗口，Arrange 视图固定布局，1×AA/2048 阴影。每帧移动相机并验证视口确实重绘；测输入处理、UI、场景、呈现到 flip 的完整循环和帧间隔，截图编码在计时后执行。隐藏窗口便于自动化，不能代表用户桌面其他应用负载、显示器同步或所有摄影质量设置。

## 当前边界

不透明重复模块收益最大。透明、独特网格、连续变化的复杂层级和高分辨率摄影仍各有成本；完整城市的性能不能由一条街道外推。30 FPS 与更大规模仍以具体机器、场景、画幅的实测为准。未实现 LOD、streaming、CSM、GI 或全局渲染后端迁移。
