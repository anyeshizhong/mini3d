# LAB-01 · Heightmap、网格与表面查询验收

验收日期：2026-10-19。**LAB-01 独立实验已完成**：平地创建、8/16位灰度 PNG 导入、规则三角网格、静态分块、精确高度/几何法线查询和真实 SPQR 渲染已验证。雕刻、材质绘制、道路及正式编辑器接入属于后续阶段。

## 复现与证据

从仓库根目录运行，Python/构建前置条件见 [README.md](README.md)：

```powershell
F:/gymenv/python.exe -B experiments/world-surroundings/run_heightmap.py --output captures/world-surroundings/lab01-20261019-final
```

再次运行请换一个新的空输出目录。原始 [report.json](review/lab01-20261019-final/report.json) 包含输入 PNG、映射参数、每个查询、原始帧时间、源码/资源/可执行文件摘要和命令日志。构建复用 LAB-00 的独立 CMake 目录，同一 SPQR viewer 摘要仍为 `4b6d59f21d6b5b907726c95b75008da00af64f0bbee4ed8b39196b1621aad742`。

| 输入 | 水平低机位 | 斜俯 | 远景 |
| --- | --- | --- | --- |
| 16位65×65 | [PNG](review/lab01-20261019-final/native-1/gray16-65/horizontal/preview.png) | [PNG](review/lab01-20261019-final/native-1/gray16-65/oblique/preview.png) | [PNG](review/lab01-20261019-final/native-1/gray16-65/distant/preview.png) |
| 16位257×257 | [PNG](review/lab01-20261019-final/native-1/gray16-257/horizontal/preview.png) | [PNG](review/lab01-20261019-final/native-1/gray16-257/oblique/preview.png) | [PNG](review/lab01-20261019-final/native-1/gray16-257/distant/preview.png) |
| 8位33×49 | [PNG](review/lab01-20261019-final/native-1/gray8-rect/horizontal/preview.png) | [PNG](review/lab01-20261019-final/native-1/gray8-rect/oblique/preview.png) | [PNG](review/lab01-20261019-final/native-1/gray8-rect/distant/preview.png) |

三类输入由实验内原创的不对称丘陵/山脊公式生成，没有外部高度图或新增素材。它们共享36×26米占地、相同高程映射及 LAB-00 的三个机位/材质/天空/阴影设置，比较的是采样密度与分块成本，不代表128米或256米场景已按同样性能验收。

## 数据与接口

- `Heightfield` 拥有只读 float64 高度；提供 `flat`、`mesh_arrays`、`to_mesh`、`iter_mesh_chunks`、`query_surface`。非法形状/数值、非正尺寸和 float32 会坍缩的XY格点明确拒绝。
- 输入列向 +X，行向 +Y；8位最大值255、16位最大值65535。高程固定按 `base_z + sample/max_value*height_range` 映射，无逐图重归一化或颜色空间变换，允许显式 `flip_y`。
- `heightmap_io` 使用 Pillow 直接读整数数组，验证 PNG 签名/IHDR、尺寸预算、原始位深/色型、完整性与解码形状。拒绝调色板、RGB、alpha及灰度 `tRNS` 透明度；gAMA/sRGB 元数据不改变原始高度值。本机实测 Pillow9.5.0；依赖只声明在实验 requirements 中。
- 网格顶点先规范为 float32，查询使用同一套实际轴与Z值；不是用 float64 理想表面查询、用量化后的另一表面绘图。`bounds` 暴露实际XY端点。
- 单元统一输出 `(a,b,c)`、`(a,c,d)`，俯视逆时针、法线向上；`v<=u` 归首三角。内部格线归正侧单元、最外边归最后单元；高度连续，几何法线在折线处按所选三角确定，渲染平滑法线另行计算。
- 分块复制同一全局顶点、UV和面积加权平滑法线，边界位置/法线逐位相同；单元恰好覆盖一次。没有 LOD、动态编辑或局部 GPU 更新。
- 三个标记模型只按查询结果锚定底部中心，保持直立；斜坡上宽模型的其他底角可能离地或穿入，不将此实验描述成已解决地基/碰撞或正式 Placement 集成。

## 数值与规模

| 输入 | 原始不同灰度数 | 全局顶点 | 地形三角形 | 32单元块数 | 射线对照点 | 最大高度误差 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 16位65×65 | 3787 | 4225 | 8192 | 4 | 41 | 3.11e-15 |
| 16位257×257 | 25027 | 66049 | 131072 | 64 | 101 | 3.44e-15 |
| 8位33×49 | 157 | 1617 | 3072 | 2 | 42 | 3.55e-15 |

每组覆盖角点、外边、格点/格线、两种三角面内部及分块边界，另验证四个越界查询返回 miss。射线调用已有 `picking._triangle_hit` 检测**实际分块 Mesh**，不调用 Heightfield 插值函数反证自己；几何法线另与实际对应三角面的叉积比较。CPU回归还有70点射线对照、平面/不对称坡面、鞍形单元中三角插值与双线性插值的区别。

导出器/原生 loader 的实体及网格数还分别核对为7、67、5（地形块数+3标记），避免只凭标记物存在便认定地形已导出。静态三机位的重复 Bundle、PNG颜色与阴影深度均一致；图像验收需结合实际预览，单纯“有深度”不能证明地形画面正确。

| 输入 | 导入+CPU网格/法线构建 | 高度源字节 | 分块几何数组字节 | 单份 Bundle 全目录字节 |
| --- | ---: | ---: | ---: | ---: |
| 16位65×65 | 10.467ms | 33800 | 255120 | 9959988 |
| 16位257×257 | 129.120ms | 528392 | 4081920 | 14587847 |
| 8位33×49 | 3.953ms | 12936 | 96264 | 9768096 |

导入计时包含 PNG 验证/解码与 `Heightfield` 的静态网格/全局法线生成，不含单独的射线验证、Bundle导出及GPU初始化。几何字节为各块顶点/索引/法线/UV数组之和，包含重复边界顶点，不是进程峰值内存；Bundle还包含既有 IBL、shader、相机帧和元数据。

## 原生画面与性能

与 LAB-00 使用相同环境：Python3.8.20、NumPy1.24.3、Pillow9.5.0；C++20 Release、g++15.2.0/CMake4.0.0/Ninja1.13。Python导出在 Intel UHD620 GL3.3 上执行，native 实际使用 MX130/驱动581.08/2GiB，报告分别记录。

三机位各两次，1081×662、1x AA、vsync关闭、每轮24帧预热+120帧测量。远阴影1024，原生稳定近阴影4096。共18次原生测量、2160个测量帧；截图在计时后生成。以下为**完整 viewer 帧间隔**，每格为第1轮/第2轮，单位ms：

| 输入 | 机位 | P50 | P95 | P99 |
| --- | --- | ---: | ---: | ---: |
| 16位65×65 | 水平 | 2.962 / 2.801 | 3.314 / 3.173 | 3.544 / 3.680 |
| 16位65×65 | 斜俯 | 2.579 / 2.398 | 3.189 / 2.798 | 3.352 / 2.914 |
| 16位65×65 | 远景 | 1.992 / 1.935 | 2.427 / 2.473 | 2.531 / 2.656 |
| 16位257×257 | 水平 | 3.837 / 3.661 | 4.426 / 4.118 | 4.664 / 4.273 |
| 16位257×257 | 斜俯 | 3.677 / 3.633 | 3.995 / 4.111 | 4.125 / 4.282 |
| 16位257×257 | 远景 | 2.763 / 2.666 | 3.286 / 3.240 | 3.400 / 3.346 |
| 8位33×49 | 水平 | 2.784 / 3.139 | 3.303 / 3.735 | 3.700 / 4.006 |
| 8位33×49 | 斜俯 | 2.432 / 2.269 | 3.253 / 2.645 | 3.602 / 2.920 |
| 8位33×49 | 远景 | 2.162 / 2.092 | 2.742 / 3.771 | 3.311 / 35.083 |

8位远景第2轮 P99 出现35.083ms长尾，原始样本保留，未用更好的重复成绩替换。LAB-00 水平 P95 为2.879/3.562ms，可作为相同视图下的简单地表参考；静态小样本不能推导长期稳定性、动态编辑延迟或完整编辑器30 FPS。`render_work_ms` 包含提交与glFinish、不是独立GPU timestamp；固定机位预热后复用阴影缓存。

主 Agent 检查了默认65×65的三机位及另两种采样的斜俯图：丘陵/山脊与有限边界可辨，标记物/阴影随高度变化，没有明显分块裂缝或法线拼接线。低机位的宽标记底角差异属于上述单点锚定边界；远景是有限地形，边界之外保留背景，没有以摄影平面补成无限地表。

## 自定义导入与回归

另行实测了从现有PNG文件导入、Y翻转及非默认空间参数：

```powershell
F:/gymenv/python.exe -B experiments/world-surroundings/run_heightmap.py --output captures/world-surroundings/lab01-import-20261019 --heightmap captures/world-surroundings/lab01-20261019-final/inputs/gray8-rect.png --size 72 52 --origin -10 4 --base-z -2 --height-range 9 --flip-y --chunk-cells 20
```

该运行保留原文件字节，生成6个地形块，完成46点射线对照与三机位各两轮验证；详见 [自定义导入 report.json](review/lab01-import-20261019/report.json)。它补充验证 CLI 的用户文件分支与映射选项，不代表导入了新的外部素材。

- 实验CPU回归：`unittest discover -s tests -p test_world_surroundings_*.py`，27项通过（LAB-00原有5项、Heightfield12项、PNG10项）。
- 既有相关回归：`test_placement.py`10项、`test_native_renderer.py`12项、`test_scene_snapshot.py`15项，均通过。合计64项CPU回归。
- 未运行全仓回归、正式 Editor UI/Shot GPU 工作流或动态笔刷验收；本阶段只新增实验模块、测试、依赖说明与相关规划/登记，没有修改这些生产接口。
- 实验源数据与fixture为原创；Pillow仅作为依赖使用，没有复制其源码。天空、材质与 IBL 的既有来源/许可继续沿用 [LAB-00说明](BASELINE.md)。

## 下一步：LAB-02A

先用同一高度场做可回放的 Raise/Lower/Smooth/Flatten 操作与区域差异撤销，再建立链接同一 SPQR 核心的连续编辑验证入口。当前分块是静态 Mesh 派生结果，现有 native 更新接口仍只支持实体变换；动态顶点/纹理上传、修订号、脏区法线/拾取/阴影失效与更新延迟必须单独实现并实测。LAB-01 的静态 Bundle 截图不作为交互雕刻已完成的证据。
