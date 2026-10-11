# 性能基准

从项目根目录运行，输出使用新目录。脚本迁移仅改变路径和导入 bootstrap，全部原断言、资产、场景、计时口径保持。真实模型按 `model/manifest.json`；没有资产时明确失败，不自动下载替代 Rome。

```powershell
python -B tests/benchmarks/placement_v2_performance.py captures/my-new-placement/performance.json
python -B tests/benchmarks/renderer_v2_cpu_cache_benchmark.py --assets-root . --output captures/my-new-cache --gpu --samples 21
python -B tests/benchmarks/shadow_fit_performance_20261010.py real --output captures/my-new-shadow/results.json --cpu-samples 21 --gpu-samples 5 --resolutions 1024 4096
```

| 基准 | 独有验证 | 统一执行器 |
| --- | --- | --- |
| Placement V2 | 实际 Editor Roman 1/40/100、选中/复制/Gizmo/Undo、资源上传与同步帧计时 | 手动独立运行 |
| Renderer CPU cache | Git f36a0ff 配对、真实 GLB、CPU热点、GL正确性、PNG与独立遮挡验证 | quality/all |
| Shadow Fit | 原始 CPU proxy 与真实 Rome＋40、receiver fit、完整同步 Shot；另有 fixture-smoke 模式 | real 模式由 rome/all 调用 |

`--profile-only`、`--offscreen-only`、`cpu-proxy`、`fixture-smoke` 是不同观察模式，不替代真实资产验收。具体参数保留于各 CLI。GL测试按顺序运行，不并发跑 GPU 基准。`results.json` 中的 raw samples、资产 SHA、实际 GPU 和参数应随结果保存；旧实验结果不覆盖。
