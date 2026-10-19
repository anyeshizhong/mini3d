# LAB-02A · 动态更新实验设计

本设计是 LAB-02A 的实现边界，先于共享核心改动写入；最终效果以 SCULPT.md 的实测为准。

## 接入方式

现有 SPQR 支持实例变换更新，没有公开的网格顶点更新接口。为验证地形编辑，独立实验 DLL 编译并使用同一份 `bundle/gl_api/renderer/shadow_fit` 源码。Python/Pygame 只负责窗口、输入、CPU笔刷和实验调用，不提供替代的地形渲染器。

共享源只增加 `renderer.hpp` 中由 `SPQR_TERRAIN_LAB` 宏启用的 `TerrainLab` friend 测试钩子，模式沿用现有 opt-in ShadowAudit 的隔离方式。顶点更新与实验 C ABI 位于实验目录；生产构建不定义此宏，正式 `spqr_photo` ABI、Bundle v1/v2、Editor/Scene/Placement/API/UI不变。实验使用独立 CMake/build 目录，不覆盖现有 DLL 或 viewer。

## 一次更新的契约

1. 初始化时从已验证的离线 v1 Bundle 创建一次 Renderer；后续笔刷不重新导出 Bundle，不重建 renderer/program/VAO/VBO/EBO/material/texture。
2. 单次实验批量更新只替换固定拓扑脏块的顶点数据，布局仍为 `position3 normal3 uv2 color4`。只允许Z和法线变化；XY、UV、颜色、顶点数和索引保持不变。
3. 整批先校验索引、重复块、数量、数值和属性约束，再提交 CPU数据及已有 VBO 的 BufferSubData。非法输入拒绝整批，CPU/GPU保持原状；真实 GL 上传失败属于致命状态，不能承诺驱动错误下的原子回滚。
4. 更新 CPU bounds 与 renderer 使用的网格数据，失效近/远阴影深度、拟合与过渡缓存；测试需与相同最终地形的全新 Renderer 比较颜色和阴影，避免仍使用旧高度或旧阴影。
5. 调用必须在创建线程及创建 GL context；失败/关闭均遵守资源所有权。记录上传批数、字节和 shader 编译数，核验没有隐式重建。

## CPU 与输入

独立 SculptSession 实现 Raise/Lower/Smooth/Flatten、可回放时间权重、笔画提交/取消和区域差异 Undo/Redo。Flatten目标在一笔内固定；Smooth每次从稳定输入计算。历史只保留受影响样本矩形的前后数据；超预算拒绝并回滚当前笔画。

当前 Heightfield 是不可变数据，首版 CPU 预览仍构建新的完整 Heightfield/全局法线；这是待测成本。GPU只上传实际变化的网格块，法线变化包含高度脏区的一采样邻域。先用65×65验证完整交互，不将257×257的静态成绩当成动态性能保证。

实验窗口提供笔刷模式、鼠标落笔、半径调节、提交、Esc取消和Undo/Redo；自动回放与手工输入走相同笔刷业务入口。真实鼠标命中使用当前CPU网格，替换派生Mesh后不能复用旧拾取缓存。自动验收记录完整帧与更新延迟，动画读回/编码的成本与无读回测量分开。

## 验证和集成限制

验证笔刷数值/事务与重复回放、GPU缓冲读回、更新后边界与拾取、阴影刷新、取消和撤销重做、无效批次原子拒绝、编译计数稳定、同状态全量新建参考图像，以及连续编辑录像和帧时。常规 CPU/GPU回归根据实际受影响契约选择。

friend钩子是实验通道，不是正式地形渲染API。LAB-03评审后再决定怎样将顶点更新收敛到生产接口、怎样局部重算法线/拾取，以及怎样纳入正式统一命令历史；不因实验通过直接合并编辑器。
