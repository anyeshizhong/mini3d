# LAB-00 · SPQR 独立基线验收

验收日期：2026-10-19。**LAB-00 已完成**，仅代表同框架独立渲染/导出基线建立；地形导入、雕刻、材质绘制和 Spline 尚未实现。

## 结果与复现

使用现有 `spqr-native/CMakeLists.txt` 编译 `spqr-native` target，链接仓库原有 Renderer、bundle、shadow_fit、gl_api 与 Win32/WGL 查看器；没有新增渲染器、修改生产代码或替换编辑器 DLL。实验场景通过既有 v1 导出适配器生成。

本次实际运行命令（仓库根目录）：

```powershell
F:/gymenv/python.exe -B experiments/world-surroundings/run_baseline.py --output captures/world-surroundings/lab00-20261019-run03
```

复现时将 `--output` 换成新的空目录；构建参数与前置条件见 [README.md](README.md)。结果与原始命令/日志保留在 [report.json](review/lab00-20261019-run03/report.json)。独立构建目录为 `captures/world-surroundings/build-lab00`；初次构建从空目录开始，之后复现运行复用 CMake/Ninja 缓存。

| 机位 | 本次首轮原生截图 |
| --- | --- |
| 水平低机位 | [horizontal PNG](review/lab00-20261019-run03/native-1/horizontal/preview.png) |
| 斜俯机位 | [oblique PNG](review/lab00-20261019-run03/native-1/oblique/preview.png) |
| 远景机位 | [distant PNG](review/lab00-20261019-run03/native-1/distant/preview.png) |

主 Agent 已逐张检查：有限地表边界可见，红塔、蓝柱与黄条朝向/遮挡合理，阴影落在地表，程序天空正常；低机位可观察接触关系，斜俯与远景没有明显裂缝、共面闪烁或多余摄影地面。地表之外的背景是天空下半球，不能当成无限地形。上述为静态图像验收，未进行动态导航或 UI 人工交互验收。

## 固定输入与契约

| 项目 | 固定值 |
| --- | --- |
| 空间 | 右手 Z-up；实验约定 1 世界单位 = 1 米；无导入模型的隐式单位转换 |
| 地表 | 36×26 米矩形，Z=0，4 顶点/2 三角形；不是高度图地形 |
| 标记 | 红塔 `(-9,-5)`、蓝柱 `(5,5.5)`、黄条 `(10,-1)`，三种不同形状/高度 |
| 总几何 | 4 Entity、4 Mesh、4 Material，76 顶点、38 三角形 |
| 顶点/索引 | `position3 normal3 uv2 color4` / u32；地表俯视逆时针、法线 +Z；固定对角线 `(0,2)` |
| 矩阵/存储 | 行主序、作用于列向量；Bundle 数字小端；相机局部视线 -Z |
| 场景/帧 | 离线 `SPQRN001` v1；`SPQRF001` 每机位144帧，全部固定相机，route=`orbit` |
| 资源 | 无外部模型或新增素材；复用既有 shader 与随仓库分发的中性 IBL，Bundle 含3个纹理资源 |
| 地面职责 | 普通有限地表 Mesh 接收阴影；Photographic Ground 关闭，不导出 EditorGrid |
| 光照 | Scene Lighting，ambient=0.28、diffuse=1.5；固定正 Z 太阳方向；5500K、sun_size=0.53°、haze=0.002、Reinhard |
| 阴影 | 源场景远图1024，bias=0.0005、PCF；原生默认稳定近图4096与远图共用路径 |

每个 Bundle 的 `metadata.json` 保存精确相机位置/旋转、view/projection、FOV、near/far 和采样口径；不包含预计算可见集或拟合阴影矩阵。实际捕获索引是24和84，两个索引在固定机位下应得到相同图像。

内置 IBL 的原始来源和许可沿用 [IBL NOTICE](../../mini3d/resources/ibl/NOTICE.md)，未改写为实验原创；没有引入额外第三方源码或素材。输入资源、shader、适配器与原生源码摘要保存在报告中。

## 环境与测量

- Windows 10 build19045；Python 3.8.20（`F:/gymenv/python.exe`）。
- CMake 4.0.0、MinGW g++ 15.2.0、Ninja 1.13.0；C++20 Release。
- **native 实际设备**：NVIDIA GeForce MX130，驱动581.08，显存2048MiB；benchmark 的 GL renderer 为 `NVIDIA GeForce MX130/PCIe/SSE2`，与 `nvidia-smi` 设备相符。
- **Python 导出 context**：Intel UHD Graphics620，GL3.3，驱动标识 `27.20.100.8682`。导出与 native 测量串行进行，没有把两块 GPU 的耗时混为一项。
- 渲染1081×662，1x AA，隐藏 viewer、vsync关闭；每次24帧 warmup +120帧测量；三机位各重复两次，共720个测量帧。未启用诊断录制读回，截图在测量结束后生成。

以下是**完整 viewer 帧间隔** `swap_interval_ms`，单位毫秒：

| 机位 | 轮次 | P50 | P95 | P99 |
| --- | --- | ---: | ---: | ---: |
| 水平 | 1 | 2.412 | 2.879 | 3.065 |
| 水平 | 2 | 2.576 | 3.562 | 9.760 |
| 斜俯 | 1 | 2.218 | 2.940 | 3.191 |
| 斜俯 | 2 | 2.105 | 2.797 | 3.134 |
| 远景 | 1 | 1.726 | 2.321 | 2.950 |
| 远景 | 2 | 1.744 | 2.074 | 2.185 |

`render_work_ms` 的六次 P95 为1.434～3.013ms；它包含绘制提交和 `glFinish`，不是独立 GPU timestamp。原始逐帧 `render_work_ms`、`swap_interval_ms`、`swap_call_ms` 及完整统计在报告中。

这是小场景、固定相机的短样本基线，第二轮水平视图 P99 已有可见波动。静态 warmup 后会复用阴影缓存，因此 capture 和测量中的 `shadow_draws=0` 可以是正常情况；检查同时确认 active 标志、实际深度尺寸、有限值和非空几何覆盖，不用绘制次数替代阴影存在性。这里的成绩不代表动态地形、长时稳定性或完整编辑器30 FPS。

## 已执行的验证

| 验证 | 结果 |
| --- | --- |
| 从当前仓库源码独立编译既有 viewer | 通过；构建未改写生产 bin/DLL |
| 两次独立导出、三机位 v1 载入 | 6份 Bundle 均通过 viewer 的 `--validate-only` |
| 相同输入的场景/帧/shader 摘要 | 两次一致；三机位 `scene.bin` 相同 |
| 颜色图像重复性 | 三机位两次运行的改变像素数均为0，最大RGB差均为0 |
| 阴影深度 | 三机位重复运行的深度摘要一致；1024² float32尺寸/有限值/范围通过 |
| 远阴影图非背景像素 | 水平782766，斜俯766250，远景766250 |
| 固定机位首帧与中间捕获 | 三机位分别完全一致 |
| 新增CPU回归 | `unittest discover -s tests -p test_world_surroundings_baseline.py`：5项通过 |
| 既有相关回归 | `test_native_renderer.py`：12项；`test_scene_snapshot.py`：15项，均通过 |
| 图像人工检查 | 三张原生 PNG 已检查；结论与范围见上文 |

此仓库的 `tests` 不作为可直接导入的包使用，回归命令采用 `unittest discover`。未运行全仓测试、完整编辑器 GPU/UI 回归、动态镜头或 Python/native 视觉一致性验收：本阶段没有修改这些生产路径，也没有把它们记作已通过。

场景摘要：`49acd50bba9a3ba52515a6b0108fb2b2e9c869aac68193e25664c9f056257959`。viewer 摘要：`4b6d59f21d6b5b907726c95b75008da00af64f0bbee4ed8b39196b1621aad742`。证据基于 HEAD `4c8b380` 加报告中的工作区源码摘要，不把未提交代码描述成已有提交。

## LAB-01 最小接入设计

下一阶段沿用本实验的导出入口与三个机位，保留相同材质、天空、阴影和测量设置，便于与本基线对照：

1. 独立保存有限高度数据：原点、XY间距、行列数、浮点高程；先平地/不对称坡面，再8/16位单通道 PNG。正式编码前确认保留16位线性值的解码路径，不复用会截成8位的颜色加载。
2. 将现有2三角地表替换为规则网格；以65×65采样起步，再以257×257样例观察规模成本。单元统一采用与本例相同方向的对角线；建立共享边界与法线规则。网格只是高度数据的派生产物，不改变编辑器 Scene v3。
3. 为相同三角剖分实现高度、几何法线和有效范围查询；用鞍形单元区分双线性和三角形插值。至少20个顶点/边界/格线/面内/越界点与实际三角形射线交点对照。
4. 输入相同高度图/配置得到相同网格与 Bundle；三机位真实绘制检验绕序、坡面阴影、接缝与边界。输出沿用现有原始统计，另记录生成时间、顶点/三角形数量和资源成本。

本阶段只提出以上接口接入设计，没有开始 LAB-01，也未移植 Godot 插件或修改正式编辑器功能。
