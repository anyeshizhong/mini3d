# LAB-02B-Q · 源码来源与适配记录

基线为 `spqr-terra@7a4e8849ab91aa6f448426916373cb53559d2846`；Q 使用同一 SPQR OpenGL 3.3 渲染核心，实验编译宏为 `SPQR_TERRAIN_LAB`。本文件记录 Q-1 已采用的数学思路和后续候选，不表示所有上游功能已移植。素材来源另见 [高度素材记录](assets/material-heights/NOTICE.md) 与原 [PBR 素材记录](assets/materials/NOTICE.md)。

## 锁定来源及调查

| 来源 | 固定版本与实际文件 | 核实内容 |
| --- | --- | --- |
| HTerrain | [`7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3`](https://github.com/Zylann/godot_heightmap_plugin/tree/7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3)，`addons/zylann.hterrain/shaders/simple4.gdshader`、`simple4_lite.gdshader`，同插件 `doc/docs/index.md` | `get_depth_blended_weights` 以 bump+splat 与其他层最大值做正残差，抑制近零层并归一；`depth_blend2` 用最大高度减阈值。bump 在 albedo alpha，roughness 在 normal alpha。四层函数仍有边界 TODO。 |
| HTerrain | 同版本 `simple4.gdshader::texture_antitile` / `texture_triplanar`，`tools/brush/shaders/splat4.gdshader` | 双 UV 扭曲棋盘去重复；只给第四个 cliff 槽三向投影，且与该槽去重复走不同分支。坡度限制通过地形高度邻采样法线限制笔刷 opacity，不是侵蚀/自动沉积。Q-1 仅调查，未采用这些功能。 |
| Terrain3D | [`59bacc5e61aede7d0fd96ae9cd263f4cc0f09858`](https://github.com/TokisanGames/Terrain3D/tree/59bacc5e61aede7d0fd96ae9cd263f4cc0f09858)，`src/shaders/main.glsl::accumulate_material`，`project/addons/terrain_3d/extras/shaders/lightweight.gdshader` | albedo alpha 为高度；按空间插值权重、材质权重、高度与 sharpness 幂次重加权，最终以总权重保护性归一；overlay 另用底层世界法线。低端示例保留高度混合并舍弃 projection/detiling/UV 绘制变化。 |
| Terrain3D | 同版本 `src/shaders/auto_shader.glsl`、`src/shaders/macro_variation.glsl`、`src/terrain_3d_editor.cpp` 的 TEXTURE 分支、`doc/docs/texture_prep.md` / `texture_painting.md` / `performance.md` | Autoshader 按 up 法线和世界高度在 auto 标记区域产生 blend；Spray 渐进修改双 ID 的 control map 权重，可量化旋转/缩放；detile 的 cell 旋转/位移还依靠控制点过渡和导数变换。Q-1 未引入这些数据格式、编辑工具或效果。 |

HTerrain 依赖 Godot Shader 内建变量、资源 include、GDScript 与 GPU 笔刷流程。Terrain3D 是依赖 `godot-cpp` 的 GDExtension，使用 Godot Shader 模板、分区纹理数组及 packed control map。Mini3D 没有引入上述依赖；GLSL 3.30 中重新表达选定数学，沿用世界 Z-up、已有材质纹理/权重 atlas、PBR 与阴影。没有复制上游完整 Shader、光照、编辑器或运行时。

## Q-1 实际适配

`quality_blend.py` 是独立 NumPy 数值参考；`quality_materials.py` 将同一运算写入实验 Bundle 的 Shader 副本。两者接受三种连续手绘权重，输出派生混合权重，不写回 CPU 手绘数据。

1. 先将非负手绘权重归一为 `p`，全零回默认土壤。材质线性高度 `h` 在 `[0,1]`，不是地形高程或米制位移。
2. **depth 候选**：`s=(p+h)*smoothstep(0,.05,p)`，在 `p>0` 的层中求 `m=max(s)`；`q=p*max(s-m+width,0)` 后归一。这借鉴 HTerrain 的正残差及近零抑制思路，但改成对称三层、显式零层保护、权重乘子和失败回退；不是其四层函数或二层顺序覆盖。CPU 参考先除公共 width，改善极小 width 数值范围；GPU 参数限定 `width∈[1e-4,2]`。
3. **power 候选**：`q=p*(p+h)^sharpness` 后归一，以 log-softmax 实现。这借鉴 Terrain3D 的幂次重加权；去除空间控制点权重、双 ID 顺序与 overlay 法线偏置。CPU 参考先中心化以支持极值，GPU sharpness 限于 `[0,64]`。实际参数通过 CLI 记录。
4. 最终 `effective=(1-strength)*p+strength*q`。零层始终缺席，纯层保持纯层，strength=0 恢复权重混合；等高并不意味着两种候选都保持 p，须观察是否过度锐化。颜色、normal、roughness 用同一 effective；normal 归一，颜色保留线性运算，roughness 保持线性、metallic=0。
5. 以当前不透明地形 baseColor atlas 的 alpha 打包材质高度。颜色 RGB 与旧 LAB-02B 完全相同，线性高度分别预滤/量化；不改变普通模型透明度。世界 XY、九级预滤图块与导数 LOD 暂不改变。高度不增加额外纹理读取。
6. `A` 仍用原 LAB-02B Shader 与资源；`A_control` 用 Q 的集中采样路径但 strength=0；`B_depth/B_power` 仅启用相应高度混合。A_control 用于分离采样整理与算法的成本，不能把两种变化的性能增量全部归因于高度混合。
7. Q 路径仅在采样后的人工权重**严格等于零**时跳过该层纹理读取，A_control 与 B 采用相同优化；没有用 epsilon 抹掉轻微笔触。手动预滤 LOD 的导数在分支前计算，单GL级atlas使用显式 `textureLod(...,0)`，避免非一致控制流中的隐式导数。A 保留原实现。这项优化必须以 A_control/原A 的实际像素对照及导航帧实测验证，不把节省成本归因于高度混合公式。

HTerrain 的二层函数注释另致谢 Andrey Mishkinis 的文章。Q 没有复制文章代码或该函数，保留思路归属；不要将上游项目许可证自动外推到其链接的文章、演示素材或其他依赖。

补充三层边界审查发现：初版仅用乘数 p，未给 score 加近零抑制；`p=(.4999995,.4999995,.000001)`、`h=(0,0,1)` 时，第三层可能因独占最高残差而在归一后骤增至约.75（strength=.75）。修正版采用上游的smoothstep抑制后，该层约为2.5e-7，并加入趋零和置换回归。受影响的 A_control/B_depth 单独重测，旧数据与源码保留，不混用旧depth帧时或原图。Power Shader 字节未变，沿用其既有正逆序测量并核对生成源码一致。

## 实验 GPU 计时边界

计时扩展由 `SPQR_TERRAIN_LAB` 编译隔离，默认禁用，生产 DLL ABI 不变。完整帧仍是 CPU 主循环至交换完成；GPU timestamp 单独标记地形颜色绘制区间，包含该区间的顶点/光栅/PBR/阴影查询等 GPU 工作，不是纯 Shader 算术时间。结果异步轮询，不通过等待查询结果强制阻塞；原 Renderer 自身已有的 `glFinish` 保留。实际范围及样本完整性见运行报告。

## 适用上游授权原文

下列 MIT 通知随算法适配记录保留；不代表原始素材由此获得授权。

### HTerrain MIT

```text
HeightMap terrain for Godot Engine
------------------------------------

Copyright (c) 2016-2023 Marc Gilleron

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### Terrain3D MIT

```text
MIT License

Copyright (c) 2023-2026 Cory Petkovsek, Roope Palmroos, and Contributors.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
