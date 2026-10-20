# LAB-02B · 三层材质实验设计

本设计先于纹理更新扩展实施。边界仍是独立实验，不接入正式Editor/Scene/API。

LAB-02B 原方案保留为 A。后续 [Q-1 设计与验收](QUALITY.md) 通过独立 `quality_materials.py` 扩展 Shader 副本：不透明地形 baseColor alpha 可存线性材质高度，手绘权重和事务仍由原 `PaintSession` 管理。高度权重仅为派生值，不改地形高程或用户绘制数据；原 `MaterialMaps`、PBR 素材与生产 Shader 不变。[上游及适配记录](QUALITY-SOURCES.md) 明确算法来源和实验 GPU 计时边界。

权威数据为独立于65×65高度网格的257×257三层非负归一化float32权重，列向+X、行向+Y，映射同一36×26米区域。默认土壤层为1；绘制/擦除按时间与圆形衰减累计，提交/取消和预算限制的矩形差异Undo/Redo独立验证。

使用来源明确的真实PBR图片，记录原始下载、SHA256、作者、许可和缩放；Base Color按sRGB解码为线性再混合，Normal按OpenGL切线空间解码、加权后归一，Roughness为线性。各层世界纹理尺度明确给出，不把三种纯色或顶点颜色当作材质。

比较两个同SPQR核心的实验Bundle：

1. 烘焙：按权重脏矩形重新计算有限分辨率Base Color/Normal/Roughness，再批量上传三个纹理脏区。
2. 分层：静态三层贴图atlas加动态权重图，shader在世界XY采样三层后混合。只修改导出Bundle中的材质shader副本，沿用同一SPQR光照/阴影/色彩代码。最小fixture中仅Terrain带AO槽，以hasAO识别专用材质，普通标记物保留原采样路径；不是正式通用材质类型。

GL存储固定为单级RGBA8、线性过滤。初测无预滤波的atlas在近/远景出现高频混叠；因此静态atlas改为768×511，三层各占256宽列，垂直隔离打包256至1像素的9级预滤图，shader按世界UV导数选择两级并手工三线性混合。颜色在linear空间滤波、法线解码平均后归一化、粗糙度线性滤波；每级仅在自身纹素中心内采样，避免相邻层/级串色。CPU烘焙按烘焙纹素的世界足迹选取同一预滤链。权重图与烘焙图按采样点端点映射到纹素中心；各向异性过滤及正式Texture Array方案仍待集成评审。

实验bridge扩展仅在已有宏隔离friend中增加固定尺寸、独占2D RGBA8纹理的整批脏区上传及GPU读回。整批先校验纹理ID、边界、payload、重复目标与格式；非法批次CPU/GPU和统计不变。实际GL失败标fatal并要求重建。CPU Bundle mip0同步更新，不改索引/纹理句柄或正式ABI。保持调用线程/context及GL像素传输状态；无mipmap的实验输入必须明确设定maxlevel=0，不允许更新level0却采样过时mips。

同一持久Renderer连续回放绘制/擦除/取消/撤销重做，与最终状态全量新建结果对照，读取GPU纹理，确认shader编译与地形几何不变。计时包含事件、CPU计算、上传、绘制/glFinish/swap，录像另行采样。两方案相同相机/权重/输入，输出近景、斜俯、远景及更新成本/内存数据，依证据选择后续集成方向。
