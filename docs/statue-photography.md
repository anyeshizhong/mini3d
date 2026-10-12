# 实际雕像摄影验收

2026-10-12 通过已登录的 Sketchfab 浏览器下载两件大英博物馆扫描模型，使用 4K GLB。模型本体仅安装在本地，GitHub 记录来源、SHA-256 与摄影工具；不会随仓库分发大型扫描文件。

| 模型 | 本地入口 | 三角面 | 实物高度 | GLB 字节数 |
| --- | --- | ---: | ---: | ---: |
| [A marble head of Vespasian](https://sketchfab.com/3d-models/a-marble-head-of-vespasian-4ded41793d4f45f78c7a72945769cd54) | `model/12_vespasian/vespasian.glb` | 281508 | 0.4572m | 12426928 |
| [Statue of Asclepius](https://sketchfab.com/3d-models/statue-of-asclepius-8c7150eddf4a48acab80dcd2fc309193) | `model/13_asclepius/asclepius.glb` | 500686 | 0.6223m | 19056140 |

作者：The British Museum；扫描制作者：Daniel Pett。两件均为 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)，需要署名、非商业使用，改作使用相同许可。由这两件模型制作的测试照片沿用此许可。头像原物缺鼻，扫描底部也有原始不完整处；程序不修补雕像。

先从上述页面下载 4K GLB，放到表中入口，再运行：

```powershell
python -B tools/capture_statues.py --output captures/statue-dof
```

工具先按世界包围盒高度统一尺度、居中并接地。双雕像近景按实物尺寸拍摄：85mm，脸部对焦距离约 1.6195m，背景约 3.2m。输出关闭景深以及 f/1.4、f/2.8、f/8 三档照片，另外输出背景对焦照片。背景理论模糊半径分别约 44.29、22.15、7.75px；f/1.4 被现有 32px 上限截断，另外两档未达到上限，三档画面确有差异。

实际 Intel UHD Graphics 620 验收通过：

- 两个真实扫描模型、纹理和多部件层级成功导入。
- 改光圈与前后对焦都改变实际照片。
- 1920×1280 预览、PNG 和保存重载的 f/2.8 照片逐像素一致。
- 静止相机只改曝光时，视口缓存失效；刷新后的预览与导出逐像素一致。
- 另拍一张阿斯克勒庇俄斯完整雕像夕阳长影照片。该构图使用放大至 2.4m 的展示副本，不冒称实物尺寸。

本次同时修复了审阅发现的环境缓存遗漏：`viewport_key` 纳入完整 `_atmosphere` 字典。回归覆盖曝光、色温、雾、地面尺度/高度/纹理、天空/强度、太阳大小、色调映射和开关，包括直接修改字典。311 项全量单元测试通过，无跳过。原景深 GPU、IPC 和 UI 验收仍见 [depth-of-field-validation.json](depth-of-field-validation.json)；新增真实雕像结果见 [statue-validation.json](statue-validation.json)。

## 下一阶段

浏览器中“拍照程序收尾建议”已审阅提交 `6947bb8`，并独立复跑 16 项相机/景深单测和 EGL GPU 验收。其建议先修环境缓存、用真实雕像完成照片验收，再加入点击脸部对焦，接着补白平衡与少量色调预设。本地已完成前两项；点击对焦和后期参数留作下一阶段。

目前仍是屏幕空间近似：失焦前景外轮廓扩张有限，BLEND 透明层不独立写入深度，光圈不改变曝光。还未在 MX130 上测量排除写盘的交互 P95；不将已有含导出耗时作为实时性能承诺。
