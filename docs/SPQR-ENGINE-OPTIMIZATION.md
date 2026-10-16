# SPQR：成熟引擎优化试验

参考 Godot 的 CPU 优化方法：定位热点、减少重复准备、重新测量。

- https://godotengine.org/article/rendering-cpu-optimizations/
- https://docs.godotengine.org/en/stable/tutorials/performance/optimizing_3d_performance.html

## 保留的实现

颜色可见性确定之后才创建绘制记录，省去画外实体的矩阵转换和 DrawItem 分配，保持绘制顺序、摄影细节和阴影投影者集合。

新增可局部重算边界的 SpatialIndex 原型，叶片最多 16 项；数量变化时重建，同数量重新排列仍按当前边界重算。Scene 持有树，摄影浅拷贝共享，不进入存档。默认关闭，仅供内部显式设置 scene.spatial_culling_enabled=True 且有效边界达到 512 项时使用。无效边界、辅助轴与外扩轮廓仍按原规则保守保留。

## 实测与撤回

Intel UHD 620，435 实例，960×540、1x AA、2048 PCF 阴影；每路线三轮各 16 帧交替测量。包含空间索引、阴影数组复用和连续小矩阵计算的试验组合：主街 141.87→138.78 ms，拱门 134.26→133.70 ms，环绕 131.40→139.24 ms，俯视 141.94→140.40 ms。没有稳定收益，环绕回退约 6%，主街 P95 也恶化。

撤回阴影计算改动，空间索引默认关闭。不能把原型宣称为已完成的性能提升。本轮没有引入引擎依赖、LOD、CSM、GI 或 streaming。

现有多个模块为兼容公开可变数组，反复校验全场物体；在外面加树仍需扫描所有输入、重新整理列表。435 实例的原 NumPy 平面测试较便宜，额外树维护会抵消收益。后续需由编辑命令与兼容校验共同驱动持久渲染快照，复用对象记录和派生数据，再让索引直接查询快照。阴影仍须考虑画外投影者。

## 验证

新增树查询与全量测试一致性、局部更新、重排/增删、无效裁剪平面，以及 Scene 编辑/显隐后的颜色及阴影集合兼容测试。

```powershell
python -B -m unittest discover -s tests -p "test_*.py"
python -B tests/spqr_performance_smoke.py --baseline-project PATH_TO_SNAPSHOT --output captures/engine-visual --photo-samples 4 --pompeii
python -B tests/spqr_engine_benchmark.py --baseline-project PATH_TO_SNAPSHOT --output captures/engine-timing.json --sizes 85 435
```

基线应含本轮之前的 mini3d 包与 model/manifest.json。照片回归新增市场、庭院、全景、住宅巷，保留屋顶、夜空、极端太阳角度、直接数组修改、透明材质、选中轮廓与释放重建检查。性能默认对 85 / 435 实例测四条路线，含 GPU 完成等待，不含 UI、显示和 PNG 编码。性能测试须独立运行，避免其他测试干扰。
