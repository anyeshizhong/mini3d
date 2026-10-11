# V2 Bug、质量限制与验证状态

核查日期2026-10-11。GitHub Issue状态与代码完成状态分别记录，不自动关闭Issue或发表评论。
本轮已读取仓库全部6个Issue与评论，并核对代码及Git祖先；下面是初始清单，修复/最终验证追加记录。

| 编号 / 优先级 | 分类与现状 | 来源与验证 |
| --- | --- | --- |
| #1 Lighting / 已包含 | 功能已实现；Issue open不等于缺失 | [Issue1](https://github.com/anyeshizhong/mini3d/issues/1)，efb3852；原子参数、UI/API/Shot与存档回归保留 |
| #2 Shadow / 已包含 | 功能已验收，Issue closed；单图质量限制仍在 | [Issue2](https://github.com/anyeshizhong/mini3d/issues/2)，52ee1ee；depth/bias/PCF/状态与真实GPU回归 |
| #3 Focus裁剪 / 已修复 | framing bounds误作clip bounds，1033e5e已包含，Issue closed | [Issue3](https://github.com/anyeshizhong/mini3d/issues/3)；保留失败→成功图片与scene_clipping测试 |
| #4 Rome集成 / 部分通过 | Unlit不受影是材料语义；40人碰撞是布局与点锚定范围，不是裁剪Bug | [Issue4](https://github.com/anyeshizhong/mini3d/issues/4)，476a799合入；原资产/真实UI/性能复测；不改材料或增加避障 |
| #4 Shot不存档 / 已修复 | 旧Rome报告的限制已被7cb7719修复并包含Q2 | shot_camera_persistence及跨进程PNG；保留历史报告但不再列为当前缺功能 |
| #5 Gizmo跨面板 / 已修复 | 406d697已包含；Issue仍open | [Issue5](https://github.com/anyeshizhong/mini3d/issues/5)，65与81条实际UI轨迹/单测回归保留并复跑 |
| #6 阴影运动 / P2遗留 | 确认质量限制：逐帧fit中心/尺度/Z改变，缺稳定化；不能只看普通照片移动 | [Issue6](https://github.com/anyeshizhong/mini3d/issues/6)；固定世界区域/固定观察机位与重复控制复测，批量CPU优化dfcca0d已包含但未消除抖动 |
| 阴影接触、自阴影 / P2遗留 | 单图分辨率/bias/PCF质量限制，薄几何/掠射角；不预设全为程序Bug | Q2 Blender对齐与shadow zoom、不同分辨率，保留原参数，不重写算法 |
| Q2参考球极点 / 资产缺陷 | 2/2560零长度法线、退化极点三角；不能为整理改正式几何 | 原spheres诊断no-shadow/radial normals与Q2报告保留 |
| PNG readback状态 / P1待复现 | capture未隔离PACK_ROW_LENGTH/SKIP等caller状态，潜在真实Bug | 先新增可复现GPU故障，再局部修复并保留前后证据 |
| Shot legacy实体axes / P2待复现 | show_axes=False未直接限制实体isaxes辅助循环 | 先测试干净Shot输出与Editor差别；若确认仅消除摄影辅助元素，不移除legacy axes能力 |
| Editor初始化失败释放 / P2待验证 | target/renderer等创建在try之前，异常可能绕过finally | 控制构造失败、验证资源与backend/context释放，单独提交 |
| 共享Mesh直接修改 / 契约限制 | bounds/picking/GPU缓存假设导入mesh不变；无编辑几何功能 | 文档明确，不新增mutable mesh失效框架 |
| 透明mesh中心排序 / 质量限制 | BLEND不是逐三角排序；BLEND不投透射阴影 | alpha模式回归保留；禁止把排序算法扩展伪装成重构 |

需要大型算法的遗留项方案：阴影稳定化需稳定尺度/迟滞、texel中心对齐和Z/bias世界尺度分析，
同时保留画外caster和fallback；只做中心snapping不足。另立任务后使用本机固定观察运动路径验收。
本次整合只报告此方案，不未经审查引入新的时间历史状态、CSM或渲染管线。
