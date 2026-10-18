# 程序化拱门几何完整性修复（2026-10-17）

对应 `SPQR-VISUAL-INTEGRITY.md` 第 1 项。旧代码基线为 `d1e449d`，本地分支
`feature/spqr-phase1`。检查范围为 `builtin:roman-arch`、
`builtin:roman-house` / `builtin:roman-shop` 及其 ochre/rose 配色、road/sidewalk。
用户随后确认使用 `examples/roman_street/street.json`，其中包含该程序化拱门。
未提供原始失效相机 pose 或外部 glTF，不能据此声称所有外部资产漏天已解决。

## 复现与根因

原分支增加的 mortar 内衬可以遮住 17 条拱圈石块接缝，但拱肩仍有两处实际缺面：

- 拱圈使用等角度圆弧分段；拱肩使用等距 X 分段。两条不同的圆弧折线不重合，
  在拱圈外缘与拱肩之间留下细长裂隙，正反面都能透出天空。
- 拱肩只有正反两面，没有封闭厚度。相机沿 X 方向观察 `z=6.75` 的墙体时，
  视线没有击中任何面。

新增背面剔除射线回归在旧版出现 86 条断言失败：80 条边界光线和 6 条侧视光线。
Python 实际 GL 深度缓冲也复现了 4 处天空孔洞：一个侧视探针和三个外缘特写探针。
精确相机 position/rotation/near/far 及场景保存于下述审计产物。

## 修改

拱肩下缘与拱圈采用同一等角度轮廓，并封闭每条拱肩棱柱的厚度。
沿用原石材与顶盖；真实拱洞保持开放，没有使用全局 `doubleSided` 或额外背景板。
house/shop 的闭合主体、门窗装饰面板、屋顶及 paving 的 CPU 检查未发现同类缺面，
因此没有改动这些资产。

arch 从 696 增至 840 个三角形（增加 144），仍为 3 个材质 mesh，未增加材质批次。
`test_spqr.py` 的全街几何预算检查通过。这不是完整帧时间性能验收；实时性能应参照
同场景、同后端的统一测量，不能从本脚本截图保存时间推算 FPS。

## 验证和产物

- `test_roman_arch_integrity.py` 与 `test_roman_masonry_integrity.py`：7 项通过。
  覆盖 17 条 mortar 接缝、181 个外缘角度的正反视、侧视、保留拱洞、各建筑和道路，
  以及 Scene v3 fresh-cache 重载后的实际三角形一致性。
- `test_spqr.py`：11 项通过，包含全街几何预算和 Scene v3 保存/重载。
- Python GPU：47 个静态视角完成。7 种拱门/建筑资产分别拍摄正反、左右、低高视角，
  另含拱洞与 4 处缺面探针。4 个原天空探针修后全部命中几何，开放拱洞仍未命中。
  7 份 Scene v3 用新 API / 新资产缓存重载，末视角的 color/depth 逐位相等。
- Native GPU：同样完成 47 个视角，实际全部为 `native-photo`，无 fallback。
  4 个缺面探针与开放拱洞符合预期，建筑 36 个中心视线全部命中；7 份 Scene v3
  fresh-cache 重载 color/depth 逐位相等，全部视角 GL error 为 0。

实际 GPU：`Intel(R) UHD Graphics 620`。截图使用 512 × 512，关闭阴影与摄影地面，
`haze=0`、相机 `near=.05` / `far=100`、35 mm / 1:1。结果 JSON 留存逐视角相机矩阵参数、
depth 探针、实际后端和 GL error；每种资产同时保存 Scene v3。未进行动态摄影性能基准。

产物目录（`captures/` 不提交）：

- `captures/spqr-masonry-before/cpu-baseline.txt`
- `captures/spqr-masonry-before/python/`
- `captures/spqr-masonry-after/python/`
- `captures/spqr-masonry-after/native/`

```powershell
& F:/gymenv/python.exe -B -m unittest discover -s tests -p "test_roman*integrity.py"
& F:/gymenv/python.exe -B -m unittest discover -s tests -p "test_spqr.py"
& F:/gymenv/python.exe -B tests/roman_masonry_gpu_audit.py --output captures/spqr-masonry-after/python --backend python
& F:/gymenv/python.exe -B tests/roman_masonry_gpu_audit.py --output captures/spqr-masonry-after/native --backend native
```

`--backend native` 强制实际使用 `native-photo`，禁止以 Python fallback 代替验收。
旧代码复现时可添加 `--baseline`，只记录缺面而不因预期命中失败退出；该参数不会恢复旧几何。

## 2026-10-18 补充：建筑底面共面冲突

用户仰视单体建筑时看到淡红/灰色条纹。原先的正面、侧面、高位和贴地验收没有覆盖从地下仰视底面的角度。
`_building` 的 plaster 主体、terracotta 墙脚、stone 底座和门槛都保留了 Z=0 的朝下底面，
不同材质的共面三角形产生 Z-fighting。三个主体底面并非缺面或阴影故障。

这次省去嵌入实体的重复底盖，用一张朝下的 terracotta 底板覆盖 3.94×4.88m 底座，
另用相同材质封住门槛突出底座的 0.06m 前唇。颜色/tint 与红色墙脚一致（tint .83）。
保留原尺寸、放置高度、石质侧边及屋顶，不采用深度偏移或全局双面渲染；每栋少 4 个三角形，材质绘制批次不增加。

验证：

- 8 项 Roman 几何完整性测试、24 项 SPQR 回归通过。新增检查覆盖全部 6 个 house/shop 变体：
  底面朝下、面积与原轮廓吻合、底座及门槛采样点都只有一个红色底面，没有共面叠盖。
- `tests/roman_building_underside_gpu.py`：Python/native 分别渲染 6 变体、左右仰视/正面/高位共 24 个视角，均无 GL 错误。
  每个仰视图的 20,410 个底面内部像素，RGB 通道范围从旧版最多 81 色阶变为 0；native 确认运行 native-photo。
- Python 6 变体的正面/高位共 12 张图与修改前逐像素一致。
- 本地证据：`captures/roman-underside-20261018/{before-python,after-python,after-native}/`，
  及 `front-roof-control.json`。这是几何和图像正确性检查，不是新增实时 FPS 测量。

运行中的编辑器已缓存旧的程序化 Mesh，需要先保存当前编辑内容，再重启编辑器并重新加载场景才会生成新几何。
场景存档使用 builtin 资产引用，旧存档也会自动使用新底面；不需要手改场景 JSON 或重建原生 DLL。

用户第三张图的网格是另一项：`GLGrid` 生成每个方向 21 条有限网格线，`editor_runtime` 随相机距离调整间距/覆盖范围。
它当前并非无限地面，缩远后看到方形边界属于实现限制，不是资源没加载完。本次不修改网格。
