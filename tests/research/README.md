# 研究与摄影采集

这些程序保留独有场景、断言和测量，不放入持续单测发现目录。以下命令均从项目根目录运行；每次选择新输出目录。两个旧摄影启动器合为 `open_scene.py`，显式输入 JSON，仍加载到现有 Editor 并进入 Shot Camera View。

```powershell
python -B tests/research/photographer_session.py --output captures/my-new-first-session
python -B tests/research/photographer_session_two.py --output captures/my-new-second-session
python -B tests/research/audit_shadow_precision_20261010.py --output captures/my-new-shadow-study
python -B tests/research/render_quality_v1.py v2-check --output captures/my-new-render-quality
python -B tests/research/open_scene.py captures/my-new-first-session/02_sanctuary.json
python -B tests/research/open_scene.py captures/my-new-second-session/01_geometry.json
```

| 原入口 | 当前入口 | 保留能力 |
| --- | --- | --- |
| `tests/photographer_session.py` | 同名 research 脚本 | 原始几何摄影、独立机位、PNG/Scene/重载一致性 |
| `tests/photographer_session_two.py` | 同名 research 脚本 | 静物、遮挡、光照与尺度调整 |
| `tests/audit_shadow_precision_20261010.py` | 同名 research 脚本 | 固定控制变量的地面跨度/阴影分辨率测量 |
| `tests/render_quality_v1.py` | 同名 research 脚本 | 22 组受控场景/摄影、真实 PBR 资产、重载逐像素一致 |
| `tests/open_assets_shadow_audit_20261010.py` | 同名 research 脚本 | CC0 House＋CC-BY CesiumMan 配对基准/运动/摄影/持久化 |
| `open_photographer_session.py` / `open_second_session.py` | `research/open_scene.py SCENE.json` | 两套原 Scene 的加载及 Camera View；支持 `--frames --hidden --screenshot` |

`render_quality_v1.py` 使用本地 DamagedHelmet/Lantern/Avocado。Open Assets 是另一组研究资产，不能替代 Rome：需在输出目录的 `assets/` 中准备脚本固定 SHA 的模型及许可证，或显式请求下载：

```powershell
python -B tests/research/open_assets_shadow_audit_20261010.py --download --output captures/my-new-open-assets
```

下载 URL 固定到历史提交，模型 SHA 与许可证检查保留。`--refine-only` 有意继续分析指定已有实验，其写入范围包含该实验的 refined 输出，使用前先复制原结果到新的实验目录；普通运行拒绝已有目录。历史报告里的旧命令是当时环境记录，当前入口以本页为准；没有变更历史图片、Scene、测量和许可文件。

Windows 阴影研究使用当前桌面 GL，Linux 无 DISPLAY 时保留原 offscreen/EGL 选择。不同 GPU 的阴影照片与耗时不要求彼此字节一致，应分别保留条件。Q1/Q2 的正式原图一致性由统一执行器检查。

部分历史研究报告包含固定历史 commit 标签；重新执行时另外记录实际 HEAD、修改中脚本 SHA 和环境，不能把历史标签当作本次提交。本轮直接 CLI 实测的这些信息保存在新输出的 `runs.json`。
