# Mini3D · World Surroundings 与 Terra 开发规划

> 版本：v0.11 · 2026-10-20
> 当前优先：**World Surroundings（世界外围环境系统）。SUR-00固定罗马郊外、A/B/C回放与首轮实测已完成，选择C三维地理继续开发；完整世界、摄影画质与性能仍未通过。下一工单SUR-01先处理大地表分块、近/远阴影参与及覆盖，再扩建连续世界。**
> 已有LAB-00/01/02A与LAB-02B/Q-1原型保留；Q整体画质/导航预算未通过。近景材质续作、完整Spline道路、正式Terra Editor集成延后，不取消需求，也不把未通过项标为完成。
> 本文是后续任务与验收依据，实际能力以源码、测试、真实图像和性能证据为准。

## 0. 目标与本次调整

当前首先交付的体验是：**摄影机在约定区域内离开街道、升到城市上空、横移和转向时，仍看到连续可信的城市、郊外与远景。** World Surroundings不是普通天空/天气功能，也不以无限世界为首版目标。

当前设计、摄影范围、源码接入判断、原始研究及验收口径见 [SURROUNDINGS.md](experiments/world-surroundings/SURROUNDINGS.md)，实际实现、图像与成本诊断见 [SUR-00.md](experiments/world-surroundings/SUR-00.md)。首轮目标为相对城市锚点X/Y各±200m、无遮挡可用地表上1.6～120m，包含360°转向与高空垂直俯视；SUR-00已有固定机位和路线探测，**完整范围及手动自由摄影仍待SUR-01～03验证**。

本版优先顺序：

**SUR-00 确定视野与地理布局/简化对照 → SUR-01 建造连续世界 → SUR-02 建立可信郊外 → SUR-03 完整世界摄影验收与性能诊断 → SUR-PERF 后续性能专项。** 近景材质Q、完整Spline、正式UI和Terra集成继续后置；原需求及其未通过项不变。

- 完整Spline编辑器不是外围实验前置。先复用Roman Street及固定贴地道路，验证城市出口接入郊外；局部悬空、穿地或断裂仍是外围验收阻塞，必须修复。控制点编辑、道路历史与通用路基挖填留在LAB-02C。
- 复用现有高度场、地形查询、SPQR核心、天空/Haze、共享罗马资产与测量工具。A保留天空基线、B仅做必要简化对照、C三维外围为主要开发方向，不把三种方案各做成完整系统；HLOD、clipmap、流送和物理大气不作为前置。
- 地表覆盖、接缝、裁剪/深度、阴影和视差是当前正确性要求；性能持续诊断，33.33ms/25ms转为后续SUR-PERF目标，不阻断SUR-00～03世界构建。严重导航停顿、每帧重建/无意义上传或远山破坏城市阴影等架构问题仍须当期处理，Q昂贵近景路径不默认铺满外围。
- 地理构图从SUR-00开始：先确定城市台地/盆地、主山脊、谷地和出城方向，SUR-02丰富田块、树林、农庄的合理过渡。先做一个罗马郊外示例，以少量配置和确定性生成实现，不新增地理编辑器/侵蚀模拟；海岸和庞贝场景后续再验证。
- 保留“先做独立实验、同一SPQR核心、真实图像与动态验证后再评审”的路线。SUR-03后可单独评审外围最小接入，不以完整道路/Scene v4为其前置；正式写入Editor、UI、API或存档契约另列工单，不自动启动。

长期保留的Terra完整流程：

**创建地形或导入 Heightmap → 雕刻/平整 → 绘制土壤、岩石、草地材质 → 编辑 Spline 道路并按需挖填路基 → 摆放建筑、树木和其他模型 → 保存、重开、摄影。**

以下要求保留为后置的Terra编辑器V1，不再决定当前外围实验的先后顺序：

- 高度图导入进入第一阶段；雕刻、三种材质绘制、Spline 曲路和必要的操作 UI 都是 V1 必交能力。
- 直路是 Spline 道路的测试用例，曲路必须交付。已有 Roman Street 可以提供示例资产，但不能代替曲线路面生成。
- 保留“**先做独立实验、复用同一 SPQR C++/OpenGL 核心、通过评审再集成**”的路线；增加动态编辑验证，静态 Bundle 截图不能证明能交互编辑。
- 不强制依次移植四套地形来源。当前前移连续外围与低成本远景；动态LOD、程序无限延伸、大规模植被与庞贝一键生成仍后置。
- 用户审阅后要求先建立摄影画质标准：LAB-02B 改记为功能通过、视觉待验收；以 `spqr-terra` 的 `7a4e884` 为基准，增加 LAB-02B-Q 材质真实感实验。优先移植经过源码核实的成熟算法，以同场景原始图像和动态画面判断改善，不能用 Shader 编译、跑分或像素一致性代替视觉验收。
- Q-1材质高度混合已有原型与实测，整体Q视觉/性能关卡仍开放，续作暂缓。Q不包含三维草丛、石块/碎石散布、植被动画或新地形编辑器。外围示例可使用少量静态简化树形/农庄，但不因此宣称已有正式散布或植被系统。

Terra编辑器V1范围：一个有限、Z-up的二维高度场；三种可绘制材质；恒定宽度、无交叉的道路；已有资产体系下的模型布置。外围原型与该完整编辑器是不同验收范围。高度场每个XY只有一个Z，洞穴、悬挑、桥隧、路口、交通模拟、无限世界、大规模植被散布与完整地基求解另行规划。

## 1. 仓库现状与接入判断

原方案核对基于`main`的`4c8b380`；Terra基准为`spqr-terra@7a4e884`，当前外围工作分支为`world-surroundings`。工作区另有用户的编辑器加载相关改动，继续保留，不混入外围提交。

下表记录生产模块的接入缺口；LAB-01 的独立实验数据/导入/查询实现见实验报告，不视为主编辑器已集成相应能力。

| 已核对的实际结构 | 可复用能力 | 本项目仍需新增 |
| --- | --- | --- |
| `mini3d/scene.py`、`scene_io.py` | Entity/Mesh/Group；Scene v1～v3 读取、v3 写入；先验证再替换活动场景 | Terrain/Road 数据所有权、资源持久化和新版本迁移 |
| `commands.py`、`placement.py`、`surface_drag.py` | 模型命令、表面命中、锚点、锁定、连续拖动与撤销事务 | 地形/材质/道路操作；当前快照不保存高度、权重或网格内容 |
| `assets.py`、`asset_loader.py`、模型加载器 | 共享模型资源、后台 CPU 准备、主线程接入；glTF/GLB/STL 等既有路径 | 地形表面摆放与显式重新贴地；不默认已有树木资产或植被编辑器 |
| `scene_renderer.py`、`shot_camera.py` | Arrange/Shot 共用场景绘制入口；现有天空、光照、阴影与摄影流程 | 让两工作区绘制同一修订版本的 Terrain/Road |
| `scene_snapshot.py`、`native_renderer.py` | 场景派生缓存、native 资源准备、变换同步与回退诊断 | 几何/权重修订及缓存失效；原地修改顶点不能假定自动被所有缓存识别 |
| `material_renderer.py`、`material_shaders.py`；`spqr-native/src/renderer.*` | 既有模型材质及 SPQR 绘制核心 | 地形三层混合、权重图、连续局部更新，尚无现成 Terrain 分层通路 |
| `native_photo_bundle.py`、`spqr-native/FORMAT.md`、`native_photo.h` | 离线 v1 像素 Bundle、live v2 借用纹理；现有批量实体变换接口 | 交互网格/材质更新策略；现有变换接口不能上传雕刻后的顶点 |
| `atmosphere.py`、`editor_grid.py`、`placement_plane.py` | 摄影地面、编辑辅助网格、数学摆放平面各有职责 | 与真实地形的显式表面选择，避免重复地面、错误贴地或照片穿插 |

**结论**：当前外围实验以普通Scene/Mesh/共享模型和有限地表复用SPQR，SUR-00共同地表尚未分块，不依赖先完成Terrain/Road正式数据模型。下列2.1～2.6保留Terra集成设计；外围的当前接入与缺口见[SURROUNDINGS.md](experiments/world-surroundings/SURROUNDINGS.md)。不引入Godot运行时或另造光照渲染器。

## 2. 核心设计与必须先明确的契约

以下2.1～2.6描述后置Terra正式集成的设计与建议接口；部分算法已有独立实验。当前World Surroundings按2.7执行；正式名称、文件拆分和协议编号在实施时依据真实调用链确定。

### 2.1 Terrain 数据、创建与 Heightmap

- Terrain 由 Scene 持有独立数据记录，保存稳定 ID、原点 XY、尺寸、采样间距、行列数、浮点高度、材质层和修订号；初期只允许一个，保持世界 Z-up，不支持普通对象式任意旋转/非均匀缩放。
- 创建入口首先支持平地与导入高度图。程序噪声属于可选增强，不阻塞雕刻、材质或道路。
- 首版导入 **8/16 位单通道灰度 PNG**，16 位为推荐。定义图像列向 +X、行向 +Y，提供翻转 Y 的预览选项；高度按 `z = base_z + value / max_value * height_range` 解码。导入时预览尺寸、方向及高程范围；显式指定世界尺寸，支持矩形图。
- 灰度数值作为线性高度数据读取，禁止当 sRGB 颜色解码、静默截为 8 位或自动归一化每张图；RGB、损坏图像、无效尺寸、超出资源预算的输入明确报错。重采样必须显式选择并预览；RAW/EXR/地理坐标导入延后。
- 网格、射线命中、`query_surface(x,y)` 共用最终高度与固定的单元三角剖分；精确表面查询用三角形分片插值。双线性插值可用于滤波，不用于冒充实际三角面高度。区分几何法线与渲染平滑法线。
- 原型基线建议 128×128 世界单位、65×65 采样；交互目标样例 256×256、257×257 采样。它们是待实测样例，不是已支持上限；世界单位在新地形工具中约定为米，已有模型保持原单位并显式缩放。
- 保存实际编辑后的高度数据和来源元信息；重开不依赖最初 Heightmap 仍留在原机器路径。

### 2.2 雕刻、平整与事务

- V1 提供 Raise/Lower、Smooth、Flatten；半径、强度、衰减可调。Flatten 支持数值目标或点击采样目标高度，并在一次笔画内固定。
- 笔画按世界空间间距采样、按行程或时间明确累计强度，避免事件频率/帧率改变结果；平滑从稳定输入区域计算，避免扫描顺序影响结果。
- 左键拖动显示范围与结果预览；松开提交一次 Undo；Esc、取消或工具切换恢复笔画前状态。鼠标被 UI 捕获时不落笔，笔画中不触发模型选择/Gizmo。
- 使用脏矩形/网格块更新，法线更新包含邻接采样；同步 bounds、拾取、阴影、视口与 Shot 缓存。不能每个鼠标事件重建整座城市或重新编译 shader。
- 将地形、材质、道路与既有模型命令纳入同一 Undo/Redo 时间顺序；当前 Placement 快照不足，需扩展历史记录的载荷/恢复机制。高度和权重用受影响区域的前后差异，设置内存预算，不能每笔深拷贝全场景。
- 失败的导入、编辑或联动命令回滚全部修改；预览与取消不生成历史。保存前明确完成/取消活动编辑，避免保存到半次笔画。

### 2.3 土壤、岩石、草地材质绘制

- 三个真实地表层：土壤、岩石、草地；每层最少包含 Base Color、Normal、Roughness 和世界空间纹理尺度，地表默认为非金属。权重图与高度图允许不同分辨率，必须共享同一世界坐标映射。
- 权重非负且归一化，默认土壤权重 1；画笔增加目标层并按规则分配其余层，避免黑洞或总亮度漂移。覆盖、擦除、边界、Undo/Redo 与保存重开均有确定语义。
- LAB 可先把三层烘焙为普通材质纹理，通过现有 SPQR 路径验证权重和视觉；这只证明混合结果。随后在 LAB-02 对比“脏区烘焙 + 局部纹理上传”和专用三层 shader，按画质、更新耗时与内存确定首版方案。
- 若烘焙无法满足近景纹理密度/法线质量或交互预算，再扩充共用地形 shader 与纹理绑定；沿用现有光照、阴影和色彩流程。不得把顶点颜色染成三种颜色当成材质绘制完成。
- 草地材质属于地表纹理，不等于三维草丛。树木、草丛模型按普通资产布置；植被刷和风动画后置。坡度/高度自动着色可选，不代替手工绘制。

### 2.4 Spline 道路、纵断面与地形挖填

- 首版采用可编辑的分段三次 Bézier 中心线，保存控制点/切线、宽度、材质、纵向 UV 尺度、路肩宽度、过渡距离与是否调整地形。支持增加、移动、删除控制点与整条道路。
- 按弧长及曲率自适应采样生成连续带状路面；控制点是权威数据，路面网格可重建。直路、S 弯、坡道都必须验证；现有直街模块只复用合适的资产/材质，不强行弯曲整栋建筑。
- 区分两种行为：**仅沿地形铺路**，或 **按指定道路高程整形地形**。初始控制点可采样地表高度，整形时保存的纵断面才是目标；不能每次先贴回原地形导致永远无法挖填。
- 整形模式以控制点 XYZ 和切线的 Z 分量表达目标纵断面，允许数值/拖动编辑；创建时的地形采样在提交时固定为目标高程，后续重算不自动重采样。切换模式或主动“重新采样地表”是显式、可撤销的操作。
- 对中心线左右路基区域求目标高程，低处填高、高处挖低，路肩外平滑过渡；默认无横向超高。预览受影响范围与最大挖填，超出地形、曲率导致带状网格翻折、自交/道路重叠或纵坡超限时拒绝提交并定位问题。
- **基底高度（导入/创建 + 手工雕刻）与道路整形层分离**。最终高度由基底及道路参数确定性计算；移动/删除道路从当前基底重新求值，恢复旧走廊，不能在上次挖填结果上累计修改。
- 路基范围内雕刻修改基底，再评估道路层；UI 提示道路仍控制最终路面高程。手绘材质权重与道路生成的覆盖范围同样分离，删路不会抹掉原手绘结果。
- 道路、挖填高度、路肩及生成遮罩的一次编辑共同提交/撤销；不自动移动已有建筑树木。V1 拒绝交叉走廊，未来再定义多条路的优先级与路口求解。
- 路面与地形接触按实际三角面检查；微小深度偏移仅用于消除共面闪烁。网格过粗、窄路或急弯无法达到误差预算时，细化局部网格或明确限制输入，不能靠大幅抬路掩盖悬空。

### 2.5 建筑、树木与其他模型

- 复用现有资产导入、共享实例、选择、变换、分组、锁定与 PlacementCommands；地形不进入普通模型复制/编组流程，道路通过专用编辑模式修改。
- “放到地形”显式查询 Terrain；鼠标“放到表面”继续允许建筑等模型的三角面，选择最近有效命中。无 Terrain 时保留旧 PlacementPlane 行为；有 Terrain 的范围外不静默退回 Z=0。
- 默认建筑和树木保持直立与当前 yaw；沿法线倾斜为可选策略。底部锚点继续沿用现有语义；单点贴地不等于大型建筑底部完全贴合。
- 地形变化默认保持已摆模型的世界变换，提示可能悬空/埋入。提供显式“将所选模型重新贴地”，整批一次 Undo，锁定实例跳过并报告。自动追随地形/坡度散布后置。
- 重新贴地先验证全部可编辑成员；若有越界或无支撑表面，整批不提交并列出失败 ID。历史按“雕刻 → 重新贴地”的顺序记录，Undo 也依次恢复模型位置和地形，不隐式合并两次操作。
- 批量重新贴地默认以 Terrain 为目标，也可显式指定 Road ID；只在该支持面求解，不自动改贴到楼顶或其他模型。指定道路已删除或目标范围不覆盖锚点时按无支撑失败处理；鼠标“放到表面”的最近命中规则单独保留。
- 导入建筑/树木保留原模型尺度；用已安装、来源明确的模型验收，缺少树木资产时提供明确的准备说明，不把下载任意第三方素材当成已有能力。

### 2.6 保存、渲染与资源生命周期

- 计划引入 Scene v4 存储 Terrain/Road 引用及参数，继续读取 v1/v2/v3；旧文件缺 Terrain 时保持旧地面/摆放行为。Scene JSON 版本、Bundle v1/v2、DLL ABI 是三个独立契约。
- 高度/权重使用可无损往返的二进制旁文件，JSON 保存版本、形状、dtype、相对引用及内容摘要；纹理随可搬移资源目录管理。精确编码在 WS-00 冻结，禁止把临时路径或 live GL handle 写进存档。
- 存档权威数据为含手工雕刻的基底高度、手绘权重、道路控制参数及求值算法版本；最终地形、路面与道路生成遮罩为可重建派生数据。重开后删路仍须恢复当前基底，不能只保存已挖填的最终高度。
- 保存先写齐新的资源版本，最后原子替换 JSON 清单；旧资源仍可用，失败不损坏旧存档。加载先完整验证资源、尺寸、数值和引用，再替换活动 Scene；重复保存不因量化损失逐次改变地形。
- Terrain与Photographic Ground必须明确分工，避免重叠深度或平面穿坡；外围按连续地表覆盖与接续验收，不能把核心地形外沿直接暴露给有效摄影区。EditorGrid仍只作辅助，PlacementPlane保留旧用途，普通Ground Mesh仍是模型；正式接入时保留无Terrain旧场景行为。
- 离线实验先导出普通 Mesh/Entity 为 **v1 Bundle**；live v2 的借用纹理句柄只用于同进程/context，不能当磁盘资源或交给独立 viewer。
- 当前 native 支持变换更新，几何/材质变化依赖资源重建。LAB-02 必须比较分块重建与最小局部顶点/纹理更新方案，定义显式修订和缓存失效；正式交互若达不到预算，就先完成必要的最小桥接扩展。
- Terrain 独占其可编辑网格/权重，不原地修改 AssetCache 的共享模型模板。现有 Python GPU 和拾取三角缓存也依赖 Mesh 身份，需用显式修订/失效或替换派生 Mesh 刷新并释放旧资源；更新不能只修 native 而留下过期拾取/回退画面。
- native 作为本功能主要验证路径；Python fallback 要么提供等价实现，要么给出明确、不丢数据的能力限制。最终 V1 必须完成 Python 的小规模等价绘制验证，不允许 auto 静默回退后宣称 native 通过。
- CPU 解码/计算可用 worker；Scene、History、GL 上传在主线程/context。以修订号丢弃取消或过时结果，GL 资源在正确线程释放；Shot 等待最新提交的地形/道路/材质资源就绪，不能拍旧帧。

### 2.7 World Surroundings 当前契约

区分核心可编辑区、有效摄影区、视觉支撑区。近景保留真实城市，中景使用连续地表和少量三维郊外物体，远景优先固定世界坐标的低模地理轮廓与现有天空/Haze。只在有限范围承诺完整；不能靠二维山墙、摄影机跟随山体、浓雾或缩小测试路线隐藏缺口。

摄影区、FOV/near/far、网格支撑范围、低Haze几何检查、城市阴影保护、范围外提示、简化A/B/C方法与分项验收统一定义于 [SURROUNDINGS.md](experiments/world-surroundings/SURROUNDINGS.md)。增加长焦和夕阳侧光观察；85mm对照记录传感器尺寸及实际FOV。不把大尺度Scene bounds无条件纳入近阴影，也不默认已有远景专用pass；必要扩展先隔离实测。地理配置可重配，低精区域升级Terra与人工数据迁移后置。

## 3. 开源复用与实现成本

### 3.1 LAB-02B-Q 上游源码调查（锁定源码，Q-1数学适配已完成）

2026-10-19 锁定以下版本，阅读实际 Shader、笔刷实现、材质文档及许可证；以下结论不只来自 README。后续实验报告继续保留完整 SHA、具体函数、算法变化及许可证原文，不能改用浮动分支链接代替来源。

**HTerrain：`7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3`。**

| 已核实的源码/文档 | 算法与 Mini3D 适配判断 |
| --- | --- |
| [`simple4.gdshader`：`get_depth_blended_weights`、`depth_blend2`](https://github.com/Zylann/godot_heightmap_plugin/blob/7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3/addons/zylann.hterrain/shaders/simple4.gdshader#L78-L117) | albedo alpha 存材质 bump，normal alpha 存 roughness。四层以 `h=bump+splat`，对近零 splat 做 smoothstep 抑制，再计算相对于其他层最高值的正差并归一。二层函数以最大高度减阈值后保留正残差。可改成三层 GLSL 数学；原实现有多层边界 TODO，不能照搬固定阈值和无保护归一。 |
| [同文件：`texture_antitile` 及调用分支](https://github.com/Zylann/godot_heightmap_plugin/blob/7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3/addons/zylann.hterrain/shaders/simple4.gdshader#L122-L151) | 原 UV 与旋转约 `0.6π`、缩放 `1.3` 的第二组 UV 双采样，以确定性的扭曲棋盘函数和材质高度混合；normal 同步旋回。不是随机更换贴图。可独立适配，但增加采样及三角函数成本，须实测。 |
| [同文件：三向投影及第四槽分支](https://github.com/Zylann/godot_heightmap_plugin/blob/7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3/addons/zylann.hterrain/shaders/simple4.gdshader#L96-L107)、[功能文档](https://github.com/Zylann/godot_heightmap_plugin/blob/7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3/addons/zylann.hterrain/doc/docs/index.md#L481-L532) | 按世界法线绝对分量归一，混合三个正交平面采样。CLASSIC4 只让第四个 cliff 材质槽启用，以限制成本；该槽开启 triplanar 时绕过去重复分支。可借鉴局部岩壁方案，不能据此宣称全层组合廉价。 |
| [`splat4.gdshader`：`apply_slope_limit`](https://github.com/Zylann/godot_heightmap_plugin/blob/7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3/addons/zylann.hterrain/tools/brush/shaders/splat4.gdshader#L33-L61) | 由地形高度邻采样估算法线，再以法线与 up 的点积、坡度区间及 smoothstep 限制笔刷 opacity，最后归一 splat。这是坡度约束绘制，不是侵蚀模拟或自动替换全部权重。 |

HTerrain 是 Godot 插件，Shader 内建变量、资源 include、GDScript 和 GPU 笔刷流程依赖 Godot；仅移植选定数学与采样逻辑。Mini3D 为 Z-up，必须重建投影、法线空间和符号约定。相关插件的 [MIT 原文](https://github.com/Zylann/godot_heightmap_plugin/blob/7f574eb47fbd74cb1a79adc2cc9fb7f0694fccc3/addons/zylann.hterrain/LICENSE.md) 为 Marc Gilleron 2016–2023，根许可证另记 2016–2020；保留适用原文。`depth_blend2` 另注明 Andrey Mishkinis 文章来源，复用时记录该归属并核对引用片段的许可范围，不把所有第三方内容一概视作项目自有代码。

**Terrain3D：`59bacc5e61aede7d0fd96ae9cd263f4cc0f09858`。**

| 已核实的源码/文档 | 算法与 Mini3D 适配判断 |
| --- | --- |
| [`src/shaders/main.glsl`：`accumulate_material`](https://github.com/TokisanGames/Terrain3D/blob/59bacc5e61aede7d0fd96ae9cd263f4cc0f09858/src/shaders/main.glsl#L272-L407)、[材质准备文档](https://github.com/TokisanGames/Terrain3D/blob/59bacc5e61aede7d0fd96ae9cd263f4cc0f09858/doc/docs/texture_prep.md) | albedo alpha 为材质高度、normal alpha 为 roughness。结合控制点插值权重 `weight`、材质权重 `id_w`、材质高度和 sharpness，以 `exp2(sharpness*log2(...))*weight` 重算权重，累计后统一归一；overlay 路径还参考底层世界法线。不是单纯的两色 alpha 混合，也不是可直接套在三通道权重上的最终公式。 |
| [同函数中的 detiling](https://github.com/TokisanGames/Terrain3D/blob/59bacc5e61aede7d0fd96ae9cd263f4cc0f09858/src/shaders/main.glsl#L313-L345) | 按世界控制网格位置与材质 scale 求 cell，hash 派生旋转/位移；围绕 cell pivot 变换 UV，并同步旋转 `textureGrad` 导数和法线。依靠多个控制点材质累积过渡；不能只复制 `floor/hash` 而丢掉过渡，否则可能出现接缝。可研究简化的世界锚定变化方案。 |
| [`auto_shader.glsl`](https://github.com/TokisanGames/Terrain3D/blob/59bacc5e61aede7d0fd96ae9cd263f4cc0f09858/src/shaders/auto_shader.glsl)、[绘制文档](https://github.com/TokisanGames/Terrain3D/blob/59bacc5e61aede7d0fd96ae9cd263f4cc0f09858/doc/docs/texture_painting.md) | 用 up 法线分量和世界高度得到 base/overlay blend，仅在 autoshader 标记区域或指定外部区域启用；手工数据仍保留。可作为将来的显式自动模式参考，Q 不用它覆盖人工权重，也不宣称模拟土壤沉积。 |
| [`terrain_3d_editor.cpp`：TEXTURE 的 REPLACE/ADD/SUBTRACT](https://github.com/TokisanGames/Terrain3D/blob/59bacc5e61aede7d0fd96ae9cd263f4cc0f09858/src/terrain_3d_editor.cpp#L325-L486) | Spray 用受限强度渐进增减 blend，必要时替换低权重材质 ID；同时可写入旋转（22.5°量化）、scale（8档）和 auto 标记。它修改 packed control map，不是几何散布。Mini3D 已有三层浮点权重和事务，借鉴交互语义，不引入其 ID/bitfield 格式或新编辑器。 |

Terrain3D 是 Godot C++ GDExtension，包含 Godot Shader 模板注入、纹理数组、分区及 packed control 数据依赖。移植范围限于经过适配的高度权重、UV 变化、导数与法线处理；去除 Godot API，检查并替换 GLSL 3.30 不兼容内建与结构。不得整体接入运行时、存储布局或重新实现其完整渲染器。[MIT 原文](https://github.com/TokisanGames/Terrain3D/blob/59bacc5e61aede7d0fd96ae9cd263f4cc0f09858/LICENSE.txt) 为 Cory Petkovsek、Roope Palmroos、Contributors 2023–2026；演示素材另有许可记录，代码许可证不自动覆盖所有素材。

### 3.2 采用原则与成本

Q恢复后的选型依据：比较HTerrain正残差与Terrain3D锐度权重思路；已有两种独立候选，后续去重复仍未实现。两者可抽离数学逻辑，**没有必要引入Godot**；最终公式及UHD 620最优组合仍需实测/审阅。当前不以完整Q通过作为SUR-00前置；外围另测低成本材质路径。Triplanar保留局部岩壁候选。

Terrain3D 的 [低端性能说明](https://github.com/TokisanGames/Terrain3D/blob/59bacc5e61aede7d0fd96ae9cd263f4cc0f09858/doc/docs/performance.md#shader) 及 `project/addons/terrain_3d/extras/shaders/lightweight.gdshader` 提供了取舍参考：保留高度混合，移除 projection、detiling 和可绘制 UV 旋转/缩放。这支持“先保住高度混合，再按收益添加效果”的候选策略；上游取舍本身不是 Mini3D 在 UHD 620 上的性能结论。

高度场网格和 Bézier 路带可使用小规模原创适配实现；[FastNoise Lite](https://github.com/Auburn/FastNoiseLite) 仍是后续可选程序地形来源，不是 Q 或高度图导入的前置。坡度笔刷、Autoshader、Spray 的调查不意味着本轮必须全部实现。

每份引入/翻译代码记录上游 URL、commit、文件/函数、版权/授权原文、算法原理、修改记录与传递依赖；纹理单独记录来源、作者、许可、原文件哈希及处理过程。源码预调查不能代替移植后的代码审查、数值回归和实机测量。

成本控制：主 Agent 负责范围、跨模块契约、最终编辑与验收；Luna Max 承担边界明确的只读调查、局部算法/测试或对照检查。独立调查可以并行，Scene/Commands/native 协议决策集中收敛；小任务直接完成，不为分工拆出无必要的模块。

### 3.3 World Surroundings 研究与取舍

已核对Epic官方HLOD/Imposter文档、Losasso/Hoppe 2004及GPU Gems 2、Bruneton/Neyret 2008与作者实现说明。远景可使用简化三维代理或图像替身，不存在通用于所有摄影机的唯一表达。当前优先测试三维外围，二维作为受限候选；clipmap、完整HLOD及物理大气均非首轮前置。原始来源、局限和不复制第三方运行时的边界见 [方案技术调查](experiments/world-surroundings/SURROUNDINGS.md#技术调查与选择依据)。本轮仅设计调查，没有新增上游算法移植。

## 4. 实施阶段、依赖与交付

状态：TODO=未开始，IN_PROGRESS=进行中，BLOCKED=有具体阻塞，PROTOTYPE=可运行实验，DONE=该阶段验收通过，HOLD=等待前置决定。**LAB-00/01/02A已按各自范围验收；LAB-02B仅功能通过，视觉关卡仍开放；道路暂缓。实验DONE不代表正式编辑器已有对应功能。**

### 当前优先：SUR｜World Surroundings

SUR编号与后文WS-00～05（Terra集成）不同，避免把外围原型和正式地形编辑器混为一谈。本轮已完成评估/设计，以下实现尚未开始；详见 [外围方案](experiments/world-surroundings/SURROUNDINGS.md)。

| 工单 | 状态 | 最小交付与前置 |
| --- | --- | --- |
| SUR-00 | PROTOTYPE · 实测完成 | 固定罗马郊外、21机位/6路线、四个光照/Haze批次、A/B/C三轮测量和镜头扫参；C为主线，阴影/导航成本存在明确缺口，见SUR-00.md |
| SUR-01 | TODO · NEXT | 先修大地表分块与近/远阴影参与/拟合，再建设连续城市—郊外—远山、全方向覆盖、地平线和正确遮挡；不以30 FPS阻断建设 |
| SUR-02 | TODO | 地理构图、田块/少量农庄树形与静态道路接续；空间组织可信，处理明显架构问题，不做通用道路/散布编辑器 |
| SUR-03 | TODO | 范围内自由摄影与视觉验收、原图/动态证据和真实性能诊断；世界构建与性能分开结论，可独立评审外围最小接入 |
| SUR-PERF | TODO · 后续 | 在实际完整场景优化并复测，P95≤33.33ms、优先≤25ms；不冒称正式编辑器帧率 |

SUR-00～03分别记录世界构建（功能/视觉）与性能的通过、未通过或未测。SUR-03若约20 FPS但可连续自由摄影、范围内世界可信且证据齐全，可记“世界构建原型通过、性能未达标”，不因此延迟全部建设；严重正确性/架构问题仍需处理。33.33ms底线与25ms优先预算属于后续SUR-PERF，不能以外围增量小宣布性能通过，也不能拿独立原型成绩代替正式Editor验收。Q未通过事实不变。

以下原Terra工单保留历史与长期交付，顺序让位于SUR：

### LAB-00｜固定同框架基线（DONE）

- 核实 CMake、`spqr-native.exe` 与 v1 Bundle 入口，建立简单几何/地表、三机位（水平、斜俯、远景）的可重复例子。
- 冻结 Z-up、单位、顶点 `position3 normal3 uv2 color4`、索引绕序、世界矩阵与材质约定；记录设备、分辨率、AA、阴影和完整帧基线。
- 建议实验目录 `experiments/world-surroundings/`，实施前检查布局；输入/输出与正式 Scene 隔离。
- **交付**：一条复现命令、真实 SPQR PNG、Bundle、环境/性能报告、LAB-01 入口设计。编译通过不能代替绘制通过。
- **证据**：[独立实验与复现入口](experiments/world-surroundings/README.md)、[实测基线与三机位图像](experiments/world-surroundings/BASELINE.md)。既有 SPQR viewer 独立构建通过，三机位各两次原生实测与图像/深度重复性通过；5项新增CPU测试和27项相关回归通过。仅此阶段 DONE，不代表 Terrain 编辑已完成。

### LAB-01｜高度场、Heightmap、网格与查询（DONE）

- 完成平地创建、8/16 位灰度 PNG、确定性网格、三角面查询和分块边界/法线；做不对称坡面和鞍形测试，揭露轴翻转与插值错误。
- **交付**：同输入输出一致的 CPU 测试、SPQR 三机位图像；查询覆盖至少 20 个顶点/边界/格线/面内/越界点，并与实际三角形射线对照。
- **依赖**：LAB-00。噪声、LOD 和三层材质不阻塞本阶段。
- **证据**：[Heightmap实验报告与图像](experiments/world-surroundings/HEIGHTMAP.md)。8/16位灰度PNG、65×65/257×257及矩形网格、分块覆盖/共享法线、三角面查询均通过；默认样例184点及自定义导入46点与实际分块网格射线对照。64项CPU回归、默认18次和自定义6次原生测量通过。数据与静态网格仅存在于实验层，未提供动态雕刻或正式AI API。

### LAB-02｜验证编辑、三层材质与道路的可行性

按 A、B、Q、C 的顺序分别验收，避免一次移植整个插件：

1. **A：雕刻与更新（DONE）**——Raise/Lower/Smooth/Flatten、区域差异历史、提交/取消/Undo/Redo；同一 SPQR 核心的持续 Renderer/VBO 更新、当前网格拾取和阴影失效已通过。证据见 [SCULPT.md](experiments/world-surroundings/SCULPT.md) 和 [隔离扩展设计](experiments/world-surroundings/DYNAMIC-DESIGN.md)。65×65、1081×662、Intel UHD 620 下130帧事件回放，完整帧P50/P95/P99为22.63/28.04/31.04ms，最大36.33ms；shader编译始终为3次。81项CPU回归、6个全量新建参考的颜色/远阴影逐字节对照、26帧真实渲染GIF、可见窗口30帧启动及常规DLL GPU回归通过。CPU仍全量派生高度场/法线，仅GPU按变化块上传；257×257动态性能、完整编辑器、人工鼠标体验与笔刷范围UI尚未验收。
2. **B：材质（PROTOTYPE：功能通过、视觉待验收）**——257×257三层权重、真实土壤/岩石/草地Base Color/Normal/Roughness、局部绘制/擦除、提交/取消/预算回滚/Undo/Redo；同一SPQR核心比较脏区CPU烘焙与分层shader。分层路线的98项相关CPU回归、GPU读回、全量新建对照、三机位和录像证明实现正确与更新成本，**不证明自然地表或摄影画质通过**。历史证据见 [PAINT.md](experiments/world-surroundings/PAINT.md)。原始近景、斜俯、远景图已保存在 [审阅资料](experiments/world-surroundings/review/README.md)，可以实际目视评审。材质交界、重复和陡坡表现须经 Q 改进；缺少实体草叶、碎石和轮廓体积作为已知限制单独保留。
3. **Q：材质真实感实验（HOLD：Q-1原型保留，整体未通过）**——SUR优先，近景续作延后；恢复后仍先于完整 C。
4. **C：Spline 与挖填（HOLD）**——SUR优先，完整道路在后续安排且Q结果经用户审阅后启动；直路/S弯/坡道、路基过渡、反复移动/删除恢复基底，不累计挖填和材质覆盖。SUR的固定示例道路不算本项完成。

**交付**：可回放输入、CPU 断言、真实 GL 图像、连续编辑录像与性能/内存数据。离线多次导出只能作为前置验证，不能单独通过交互验收。若必须扩展共享 Renderer/CMake/更新接口，先提交具体变更设计纳入实验评审范围，避免另建长期渲染分叉。

### LAB-02B-Q｜Terrain Material Quality（HOLD，Q-1原型与证据保留）

**范围与评估**：该独立材质实验继续有效，但用户当前优先SUR，Q续作后置。恢复时仍以`spqr-terra@7a4e884`为基线，先交界、再去重复、最后按陡坡图像/成本决定Triplanar。Q-1设计、复现、证据和限制见[QUALITY.md](experiments/world-surroundings/QUALITY.md)，[源码与授权记录](experiments/world-surroundings/QUALITY-SOURCES.md)保留实际适配范围。以下为Q恢复后的关卡，不表示Q-2/Q-3或整体视觉已通过，不阻塞SUR的独立低成本方案实验。

#### Q-1｜材质高度与 Height-based Blending（第一优先级）

- **Terrain Heightmap** 决定地形顶点的世界高程，关联拾取、雕刻、法线和阴影；**Material Height Map** 描述单块土壤/岩石/草地贴图内的微表面高低，用于材质混合。后者不改高度场、碰撞或网格轮廓，不能生成真正的草叶和碎石体积。
- 原 LAB-02B 三种 Poly Haven 材质只打包 Base Color、OpenGL Normal 和 Roughness；Q-1已为同一 `brown_mud_02`、`rock_face`、`leafy_grass` 补齐对应官方 displacement，保留原B素材不变。来源、位深/方向/范围与误差见 [高度素材记录](experiments/world-surroundings/assets/material-heights/NOTICE.md)。不得由 Base Color 灰度冒充真实高度，或静默换成不明贴图。
- 高度按线性数据读取，保留可取得的高位深源文件；打包/降采样记录量化误差、幅度与偏置约定。未经标定的贴图高度只作为相对微表面值，不能声称以米为物理位移。保留当前 Base Color 在线性空间混合、normal 归一及 roughness 的 PBR 语义，metallic 保持 0。
- 先用固定权重坡带与三层交界对照 HTerrain 正残差阈值和 Terrain3D 锐度重加权，再选择三层实现。目标是少量泥土优先显现在岩缝/低处，同时仍能由用户笔刷控制覆盖；不直接移植 Terrain3D 的双 ID、控制点顺序依赖或其 overlay 法线偏置。
- CPU 手绘权重及历史始终是权威数据，Shader 的有效混合权重是派生结果。提供可调强度/过渡宽度，强度为 0 时还原原权重混合；零权重层必须保持缺席，单层纯权重不得串色。覆盖全零/近零、等高、极值、分母保护、非有限输入和三层交界；无效数据在上传前拒绝，GPU 仍需防御性回退到原归一权重（原权重也全零时使用默认土壤），不允许黑洞、NaN、突然跳层或无意的层顺序偏好。
- 优先评估复用现有不透明地形 albedo atlas 的 alpha 储存高度，以减少新增采样；这只是待测方案，不能改变普通模型 alpha/opacity 语义。同步处理 RGB 与线性 height 的预滤，必要时比较独立高度纹理的精度与内存成本，不修改基线 A 的资源解释。

#### Q-2｜Tiling Reduction（第二优先级）

- 在高度混合独立通过后，对照 HTerrain 的双 UV 扭曲棋盘采样、Terrain3D 的世界锚定旋转/位移与控制点过渡，选择适合三层和 UHD 620 的最小方案。先比较单项收益与采样成本，可仅对重复最明显的层启用；大范围低幅颜色调制作为独立可关闭候选，不能靠强噪声掩盖原材质。
- 所有通道共享 UV 偏移/旋转/缩放：颜色、法线、粗糙度、高度不可错位；normal 必须旋回正确基底。变化锚定世界位置和固定种子，不随相机或时间重新随机；检查 cell/过渡边界与远景稳定性。
- 兼容现有 `MaterialMaps` 手动预滤 atlas 和导数选级：它是单 GL mip 内竖向打包的多级图像，不能假定普通 `glGenerateMipmap` 已解决采样。使用连续、变换后的 UV 导数计算 LOD，避免 `fract`/cell 边界污染导数；颜色、高度、normal 和 roughness 的各级预滤需一致且各自正确。拒绝明显噪点、闪烁、接缝和远景混叠。

#### Q-3｜陡坡映射（第三优先级，按测量取舍）

- 保留世界 XY 基线，先以相同陡坡地形验证拉伸，再测 HTerrain 风格的局部岩石/陡坡 Triplanar；不默认三种材质全部三向采样或和去重复无条件叠加。
- 为 Mini3D 的 Z-up 重建投影轴、正负面方向和法线基底，颜色/normal/roughness/height 使用一致投影与混合。检查中性法线、轴对齐面、混合坡面、旋转纹理和三平面接缝；不能直接照搬 Godot 的 Y-up 法线 swizzle。
- 若开销过大，比较局部启用或简化投影；允许暂缓，但须交付同坡面图像、采样/GPU 成本及取舍理由。缺少成本证据不能直接判定“不值得”，编译通过也不能判定“已解决拉伸”。

#### Q-4｜可复现的视觉与性能对照

固定同一地形、三套材质来源与纹理尺度、权重数据、相机路径、分辨率、光照、曝光、阴影、AA、驱动和 GPU。保留原 LAB-02B 的入口、素材与原图；记录新 runner 的基线复测，历史数字只作参考。若增加陡坡诊断地形，所有方案使用相同诊断地形，不能只给改进版换更有利的场景。

| 方案 | 独立开关与比较目的 |
| --- | --- |
| A | 原 LAB-02B 权重混合，复现 `7a4e884`；新测量框架下复测以排除环境差异 |
| B | A + Height-based Blending，关闭去重复和 Triplanar |
| C | A + Tiling Reduction，关闭高度混合和 Triplanar；与 B 分开隔离成本与收益 |
| D | Height-based Blending + Tiling Reduction，仅在组合成本允许时保留 |
| E（可选） | 在候选组合上增加局部 Triplanar；保持其余开关一致，与对应无 Triplanar 方案比较 |

- 每个已实现方案输出**近景、斜俯、远景、陡坡原始 PNG**，另给连续移动相机的真实录屏/GIF；固定材质交界观察区、重复纹理观察区与岩壁观察区，允许放大原图，不以生成示意图、后处理或调整曝光替代真实渲染证据。记录仍像贴纸、缺少体积或尺度感的区域。
- 回放相同绘制、擦除、取消、Undo/Redo，再连续移动相机；比较每一步 CPU 权重、GPU 上传/读回和全量重建参考。参数切换不应覆盖手绘数据或破坏既有事务。几何、拾取、法线、阴影保持 LAB-02A 的更新契约。
- 同设备记录完整实验帧 **P50/P95/P99**、最大值、样本数和预热；分别测静止、导航、编辑。固定预热与采样协议，建议至少预热 24 帧、采样 120 帧并重复，轮换方案顺序；着色器编译/首次上传另报，禁止混入稳态后选择性剔除慢帧。
- 增加材质所在地形绘制区间的 GPU timer query，使用异步查询避免为读计时结果强制阻塞；报告计时边界、可用性及相对 A 的增量，不能将整帧 GPU 计时称为“纯材质计算”。CPU 更新、上传、render+`glFinish`、交换与完整帧分别记账；现有 CPU `glFinish` 耗时不能改名为 GPU 时间。可采用 [OpenGL timer query](https://github.com/KhronosGroup/OpenGL-Refpages/blob/main/gl4/glQueryCounter.xml)；若实验接口须扩展，继续 opt-in 隔离，不能修改生产 DLL ABI。
- 记录每套静态纹理、预滤级、权重图和额外资源的格式/尺寸/估算驻留字节、CPU 缓存，以及初始和每帧上传量/调用数；无法取得驱动实际显存占用时明确标为分配字节估算。绘制不得逐帧重新编译 Shader 或重传不变材质。
- UHD 620 的 LAB-02B 分层历史完整帧 P95 为约 **17.49 ms**，本轮必须重新测 A。**30 FPS（33.33 ms/帧）是目标底线**；同时报告 `33.33 - P95` 的余量、相对 A 的增量和画质收益。候选组合优先争取 P95 ≤ 25 ms（建议选择预算，预留至少约 8.33 ms），超出时必须论证取舍；低于 33.33 ms 也不能自动视作后续城市场景有足够余量。独立实验结果不能宣称为正式编辑器帧率。

#### Q-5｜工程边界、回归与交付关卡

- 不修改正式 Scene 格式、Editor UI、Placement、AI API 和生产 DLL ABI；继续使用既有隔离机制复用 SPQR 核心，不维护另一套光照渲染器。不破坏 LAB-02A 雕刻、拾取、法线和阴影；保留原 LAB-02B 可复现，保护工作区已有修改。
- 新增有意义的材质混合数值回归、贴图高度/预滤/旋转一致性测试、局部纹理更新与 GPU 读回对照，以及绘制/擦除/取消/Undo/Redo 回归；覆盖关闭效果后回到 A、非法输入失败不留下半次更新。按实际影响运行既有高度场、雕刻、绘制和 native 回归，不把旧的 98 项通过当成本轮已经通过。
- 更新实验 README、PAINT/设计说明，并新增 Q 的源码对照、选型与实测报告（实施时确定实际文件名，不提前登记不存在的模块）。提供一条可运行复现命令及构建/素材前提，记录上游 SHA、采用函数、适配修改、依赖与许可原文、素材哈希、Shader/参数和硬件环境。
- 交付 A/B/C/可行 D/可选 E 的原始 PNG、必要动态画面、性能原始数据、纹理内存/上传统计、兼容性与失败记录；对未实现组合说明原因。图像必须能从报告直接定位，不能只报告“已生成截图”。
- 最终逐项回答并给出证据：**高度混合是否更自然；重复是否可见改善；陡坡是否需要 Triplanar；UHD 620 最值得保留哪种组合；是否达到正式集成评审条件。** 当前答案均待实验，不作预判。明确尚存的体积、草叶/碎石轮廓等问题及后续建议，不把材质实验宣传为完整摄影地表完成。
- 先交付测试结果供用户审阅；**实验完成前不自动提交、推送或合并，完成后也先交付结果等待审阅。** 视觉关卡由真实画面和用户审阅关闭，未关闭前 LAB-02C 保持 HOLD；Q 通过仅允许讨论后续路线，不自动启动正式 Editor 集成。

### LAB-03｜Terra Editor 集成评审（后置）

- **依赖**：SUR优先路线完成/审阅后恢复Terra；LAB-02B-Q画质/性能结果经用户审阅、LAB-02C完成。此项是完整Terra集成评审，不是SUR原型或外围最小接入评审的前置；实验成功不等于正式集成授权。
- 汇总上游来源、实际适配范围、功能/图像、更新成本、内存和已知限制；确定分块大小、材质方案与最小 native 更新契约。
- 提供将影响的 Scene/Commands/持久化/拾取/API/Shot/Renderer 文件和回归清单；说明 Python fallback 支持范围及补齐工作。
- **交付**：可运行原型与集成工单；只有真实证据才能记 PROTOTYPE。之后由用户决定进入 WS；正式合并不因实验成功自动发生。

独立阶段不修改正式 Editor/Scene/Placement/API/UI/Scene v3。共享渲染核心的必要实验扩展须明确隔离、兼容性及验证，不以实验为由重构全部生产路径。

### WS-00｜集成数据、历史和存档基础

**依赖**：LAB-03 完成且集成获授权。

建立 Scene 持有的 Terrain/Road、统一命令历史、Scene v4 和资源清单；先接入最小平地/高度图及表面查询，验证旧场景载入、失败回滚与无损往返。接入共有绘制/拾取，处理 Photographic Ground 冲突。冻结 API 错误、事务与修订语义。

**交付**：最小地形在 Arrange/Shot 一致，保存重开高度不变；旧场景、普通模型 Undo 不受损。此时尚不算完整地形编辑器。

### WS-01｜可手动使用的地形工具

**依赖**：WS-00。

提供 Terrain 模式、创建/导入预览和雕刻/平整画笔；接入统一命令与 AI 可调用的同一业务入口。完成脏块上传、交互反馈、取消、快捷键冲突与资源就绪处理。

**交付**：手动及脚本均可创建 → 雕刻山丘 → 平整建筑平台 → Undo/Redo → 保存重开 → Shot。必要 UI 在本阶段交付，不留到最后作为可选装饰。

### WS-02｜三种地表材质绘制

**依赖**：WS-01、LAB-02B 及 LAB-02B-Q 选型与视觉审阅结论。

接入选定材质方案、层选择和画笔；相同权重由 UI/API 操作，记录资源引用与材质尺度。补齐 native/Python 共用的正确视觉输出。

**交付**：土壤、岩石、草地分别及混合绘制，近远景检验、撤销、重开和 PNG 均一致；相机移动纹理稳定。

### WS-03｜可编辑 Spline 道路与路基

**依赖**：WS-01、LAB-02C；完整画面验收依赖 WS-02。

接入控制点/切线编辑、道路参数、挖填预览、选择与删除；统一道路和地形的事务，提供同等脚本/API 入口。将生成路面加入渲染与表面命中，但不作为可任意变换的普通模型。

**交付**：在坡地修建一条 S 弯道路，既有填高又有挖低；移动控制点、撤销/重做、删路、保存重开均正确，旧走廊恢复。直路演示不能代替本阶段验收。

### WS-04｜模型布置与重新贴地

**依赖**：WS-01；道路上的摆放验收依赖 WS-03。

完成 Terrain/道路/其他模型的命中策略；建筑、树木与其他模型继续使用现有导入与命令体系，提供显式批量重新贴地与失败/锁定反馈。

**交付**：平整平台摆建筑、坡面摆树、道路摆物体；改地形后模型默认不动；重新贴地可撤销，保存重开保持 ID、组和变换。大型建筑用明确平台与锚点验收，不声称自动地基求解。

### WS-05｜V1 完整工作流验收

**依赖**：WS-00～04。

使用一份可分发的演示工程完成创建/Heightmap 两种入口、山丘与平台、三层材质、S 弯路基及建筑树木布置；由真实编辑器操作与同业务入口的 API 分别复现，拍摄街道高度、斜俯和远景。

**交付**：工程及相对资源、操作说明、调用日志、撤销/重开对照、PNG/录像、实际后端与性能报告；清楚列出已知限制。Terra编辑器V1到此完成。World Surroundings按前置SUR路线单独验收；动态LOD、无限延伸、大规模植被散布与“庞贝城郊”自然语言生成仍属后续增强。

## 5. 验收与回归口径

- **数值**：高度图方向/16 位精度/异常输入；三角插值；笔刷边缘与平滑；权重和为 1；路带采样、纵坡与边界；反复挪路结果无累计变化。CPU 表面误差建议不超过 `1e-4` 世界单位，若浮点范围需调整必须记录理由。
- **道路接触**：演示以米为单位时，路面与目标地表垂直差建议在 0.02m 内；连续侧视、近景和弯道检查悬空/露底。误差预算与地形间距一同冻结，单张俯视截图不能通过。
- **事务**：一次笔画/控制点拖动/批量重新贴地一条 Undo；交错模型、地形、材质、道路操作按真实顺序恢复；Esc、失败、重复 Undo/Redo、保存中活动编辑均覆盖。
- **持久化**：旧 Scene v1/v2/v3、小型新工程、多次无损往返、移动工程目录、缺失/损坏旁文件、失败不替换当前场景；保存中断后旧工程仍能打开。
- **真实 GL**：Arrange、Camera View、Shot PNG、深度/遮挡/对焦、阴影、边界法线、地面重叠；移动相机、连续笔画、取消和重建后拍照。记录 native/python 实际后端，严格 native 不能暗中回退。
- **性能**：固定设备、输出尺寸、AA/阴影、内容与路线，记录静止/导航/编辑完整帧P50/P95/P99、更新延迟和内存。正式编辑器仍以30 FPS（33.33ms）为底线目标、画笔预览≤100ms；SUR世界构建与性能分项验收，30 FPS收敛在SUR-PERF，不作为SUR-00～03硬门槛。明显架构问题当期处理，不能拿独立viewer成绩冒充正式Editor通过；后置Q保留其自己的验收口径。
- **来源与导航**：代码/素材出处及许可可追溯；新增/拆分/改职责的生产文件同步 `docs/ai/FILE_REGISTRY.md`，只登记实际存在的文件，不提前登记本规划中的建议模块。

实施时从以下现有回归中按影响选择，再增加真正覆盖新行为的测试；各阶段已执行的项目见对应实验报告，不表示下表全部回归均已运行：

| 影响面 | 已有入口 |
| --- | --- |
| Commands / Placement / Scene 往返 | `tests/test_commands.py`、`test_surface_drag.py`、`test_placement.py`、`test_placement_v2_commands.py`、`test_editor.py`、`test_placement_v2_editor.py`、`test_shot_camera_persistence.py` |
| API / dispatcher / 同一活动场景 | `tests/test_api.py`、`test_api_dispatch.py`、`test_api_binding.py`、`unified_api_ui_smoke.py` |
| 快照 / 资源准备 / 取消 / native | `tests/test_scene_snapshot.py`、`test_native_renderer.py`、`test_native_preparation.py`、`test_editor_loading.py` |
| 真实绘制与摄影地面 | `tests/native_arrange_gpu_smoke.py`、`native_photo_gpu_smoke.py`、`native_preparation_gpu_smoke.py`、`photographic_ground_gpu_smoke.py`、`test_ground_separation.py` |

表中省略目录的文件均在 `tests/`；具体命令和资产前置条件以 `docs/ai/OPERATIONS.md` 及测试源码为准。

## 6. 当前看板与交接

| ID | 状态 | 下一动作/阻塞条件 |
| --- | --- | --- |
| SUR-00 | PROTOTYPE · 实测完成 | 已有独立入口、原PNG/GIF、完整逐帧数据和裁剪/阴影诊断；选择C主线；完整世界/画质/性能未通过，见SUR-00.md |
| SUR-01 | TODO · NEXT | 先处理普通巨大地表造成的近阴影深度范围与绘制成本，再做连续地表/全方向支撑/低Haze地平线；不要求先达到30 FPS |
| SUR-02 | TODO | 完善山谷/道路/土地分布、少量中景物体与静态道路接续，处理明显架构问题 |
| SUR-03 | TODO | 范围内自由摄影/视觉验收及性能诊断，分别记录世界构建与性能结论，提出外围最小接入评审 |
| SUR-PERF | TODO · 后续 | 用完整场景收敛到P95≤33.33ms，优先≤25ms，保留全部真实测量与未达标项 |
| LAB-00 | DONE | 独立构建、6次原生测量、三机位图像及确定性验证；证据见 BASELINE.md |
| LAB-01 | DONE | Heightmap/查询/静态分块、三机位原生重复验证；证据见 HEIGHTMAP.md |
| LAB-02A | DONE | 雕刻/平整、区域差异撤销及持续SPQR更新；65×65实验边界和证据见 SCULPT.md |
| LAB-02B | PROTOTYPE | 功能通过、视觉待验收；原功能证据见PAINT.md |
| LAB-02B-Q | HOLD | SUR优先；Q-1为PROTOTYPE，124项CPU及相关真实GPU检查通过，导航/整体视觉仍未通过；Q-2/Q-3未实施，证据见QUALITY.md |
| LAB-02C | HOLD | 完整Spline/挖填后置；SUR固定路面不算本项交付，恢复时仍需Q审阅和视觉关卡 |
| LAB-03 | HOLD | 完整Terra原型齐备后评审，不阻塞SUR及外围最小接入评审 |
| WS-00～05 | HOLD | 集成决定后按依赖实施；V1 必须覆盖全部用户流程 |

后续下一张工单：

> **SUR-01**：先读FIRST、SURROUNDINGS.md与SUR-00.md，保留SUR-00的A/B/C和原始测量。优先将共同大地表改为可裁剪静态分块，明确普通地表、远山和背景的近/远caster与拟合参与；当前近阴影深度跨度约17.4km，不能靠单纯分块或关闭城市阴影解决。沿既有台地/北山脊/南谷地布局建设连续地表，按相机范围、FOV与far推导所有方向支撑，低Haze、高空俯视和向外巡检必须有证据。固定出城道路保持贴地，完整Spline、Q续作、正式UI/API/Scene格式仍后置。世界构建与性能分项，30 FPS留给SUR-PERF；当前阴影与明显绘制架构问题先修，不把技术原型当完整世界。保护既有修改，提交/推送仅按用户当次明确授权执行，不自动合并。

每阶段交接记录：任务 ID、分支/HEAD/现有改动、输入与来源 commit、实际实现/修改文件、复现命令、运行过的 CPU/GPU 验证、图像和测量路径、已知限制、未执行项与下一最小闭环。没有证据的能力保持 TODO/PROTOTYPE，不用规划文本当完成声明。
