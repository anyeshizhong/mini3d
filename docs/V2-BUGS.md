# V2 Bug、质量限制与验证状态

已读取仓库全部六个Issue和评论并核对代码/Git祖先；Issue状态与实际修复分别记录，没有自动关闭Issue或发表评论。

| 问题 / 状态 | 结论与验证 |
| --- | --- |
| [#1 Lighting](https://github.com/anyeshizhong/mini3d/issues/1) 已包含 | Issue open；efb3852在Q2，原子参数、UI/API/Shot/存档回归通过 |
| [#2 Shadow](https://github.com/anyeshizhong/mini3d/issues/2) 已包含 | Issue closed；52ee1ee在Q2，depth/bias/PCF/MASK/Unlit/状态/真实资产通过，质量限制保留 |
| [#3 Focus clip](https://github.com/anyeshizhong/mini3d/issues/3) 已修复 | 1033e5e修复framing bounds错作clip bounds；当前GPU回归通过，原失败/成功图保留 |
| [#4 Rome](https://github.com/anyeshizhong/mini3d/issues/4) 部分验收 | 476a799历史合入；原Unlit不受影是语义，40人点锚定与fountain/stall重叠是布局限制；原GLB/UI/Shot/深度/重载/性能通过，不增加避障或修改模型 |
| #4旧Shot不存档 已修复 | 后续7cb7719已在Q2；新进程及Editor导航后PNG exact，旧报告原样保留 |
| [#5 Gizmo跨面板](https://github.com/anyeshizhong/mini3d/issues/5) 已修复 | Issue open；406d697已在Q2，81条实际UI检查全部通过 |
| [#6 摄影机移动阴影](https://github.com/anyeshizhong/mini3d/issues/6) P2遗留 | 实际GL深度、固定世界点PCF重放确认边界变化；CPU batch不是稳定化修复，locked-union control深度恒定 |
| 接触/自阴影 P2质量限制 | 单图resolution、bias/PCF、薄几何/掠射角限制；Q2原图和Blender对齐保持，未宣称全部解决 |
| 球极点 资产缺陷 | 2/2560零长度法线和退化极点三角形；原no-shadow/radial-normal诊断保留，不改正式几何 |
| 透明度 质量限制 | BLEND按mesh中心排序，非逐三角形/OIT，不投透射影；alpha/doubleSided/负scale实际GPU通过 |
| 共享Mesh直接修改 契约限制 | bounds/picking/GPU cache依赖导入Mesh不可变；未新增几何编辑或失效框架 |
| Rome manifest遗漏 已修复 | 原Q2缺登记、测试KeyError；c606682补核实元数据，原模型不改，真实资产回归成功 |
| PNG PACK/PBO P1已修复 | 调用者PBO导致CPU readback误作offset、GL error1282；e6ff83b隔离/恢复pack与PBO，也涵盖纹理分配对ALIGNMENT影响；与正常PNG byte exact |
| Shot实体axes P2已修复 | 原isaxes绕过clean Shot world axes关闭；e6ff83b只隐藏clean副本entity axes，Editor能力保留 |
| Editor构造失败 P2已修复 | app创建在try前绕过释放；25da77f用ExitStack登记资源，renderer/target close从0次变1次，SDL关闭 |
| runtime摄影hook 已修复 | 4829395保持Editor摄影替换/子类hook；原81条实际UI轨迹通过 |
| 统一窗口/API 已整合 | a3bb19b允许绑定现有Editor，正式app.api共享Scene/Commands/Shot/renderer；同窗口JSON、Undo/Redo、4x/IBL/shadow/PNG/save-load通过，旧独立构造保留 |
| 示例flatten边界 已修复 | 共享适配曾扩大geometry对axes-only的保留；99144e7恢复geometry仅mesh、URDF保留link axes；新增测试失败→成功、277单测及六原入口PNG exact |

本轮 [修复前](v2-consolidation/bugs-before.json)、[修复后](v2-consolidation/bugs-after.json) 和真实图片保留；未删除失败测试。
回归工具的参数/输入目录错误已纠正并补跑，原失败日志留存；这些不计作程序Bug。

## 阴影稳定化后续方案

1024横移有2230/73728点变化（3.02%），4096有613点（0.83%）；最大单步visibility变化仍达0.4444。
lateral各121帧，dolly/low-sun各61帧，1024/4096共486帧；固定观察点与locked control用于区分相机运动和实际影子变化。
CPU caster进入探针的Z extent跳变19.7035，仅是几何诊断，不能直接声称可见闪烁。
只有中心texel snapping不足以解决尺度和Z/bias逐帧变化。建议另立任务：稳定尺度/必要迟滞、中心texel对齐、Z/bias世界尺度策略，同时保持画外caster/fallback。
验收使用当前固定点、locked control、原Rome及Q2画质/性能证据。CSM、时间历史等大型算法须先审查方案，本整合未引入，也未将#6标为已修复。
单测/GPU成功不证明所有模型、驱动或人工操作都无缺陷；遗留边界随候选交付。
