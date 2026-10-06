# 模型兼容性资产

本目录收集五个测试资产。**五个模型均已下载并检查文件结构。** 以下图片均来自资产发布方，并非 Mini3D 的渲染结果。

| 顺序 | 模型入口 | 状态 | 用途 |
| --- | --- | --- | --- |
| 1 | `01_box/Box.glb` | 已下载 | 基础几何、单材质、坐标与聚焦 |
| 2 | `02_water_bottle/WaterBottle.glb` | 已下载 | UV、贴图、PBR 材质 |
| 3 | `03_side_table/side_table.glb` | 已下载 | 实际尺寸、外部贴图和材质 |
| 4 | `04_fox/Fox.glb` | 已下载 | 骨骼、蒙皮、Survey / Walk / Run 动画 |
| 5 | `05_roman_soldier/roman_legionnaire.glb` | 已下载 | 人物、多部件与材质 |

每个子目录都有 `source.txt`，记录来源与许可；Khronos 模型另保留官方 `upstream_README.md`。完整文件信息、SHA-256 和下载状态见 [manifest.json](manifest.json)。已有 `cube.STL` 保留。

边桌提供两个入口：打包好的 `side_table.glb`，以及原始 `side_table_tall_01_2k.gltf`。原始 glTF 所需的 `.bin`、2K 漫反射贴图、法线贴图和 AO/粗糙度/金属度合并贴图均保留；GLB 仅封装这些原始数据，未更改模型或贴图内容。

五个模型均可通过根目录的 `editor.py` 在 Mini3D 中显示，支持贴图与金属粗糙度材质。狐狸暂显示默认骨骼姿态，不播放动画。

## 1. Khronos Box


作者：Cesium。许可：CC BY 4.0。[原始发布页](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/Box)。

## 2. Khronos Water Bottle


作者：Microsoft。许可：CC0。[原始发布页](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/WaterBottle)。

## 3. Poly Haven Side Table Tall 01


作者：James Ray Cock。许可：CC0。[原始发布页](https://polyhaven.com/a/side_table_tall_01)。

## 4. Khronos Fox


模型：PixelMannen（CC0）；绑定与动画：tomkranis（CC BY 4.0）；glTF 转换：AsoboStudio、scurest（CC BY 4.0）。[原始发布页](https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/Fox)。

## 5. Roman legionnaire


作者：Geoffrey Marchal（geoffreymarchal）。许可：**CC BY-NC-SA 4.0**，需署名、限非商业用途，改作须以相同许可发布。[原始发布及下载页](https://sketchfab.com/3d-models/roman-legionnaire-40b87797180148e4bace023b6da0c45a)。

这与最初推荐的 Tharusha Thimod 版 Low-Poly Roman Soldier 是不同模型，许可也不同。预览图已换为本 GLB 对应模型的 Sketchfab 官方缩略图。
