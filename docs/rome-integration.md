# Issue #4: Rome 3+1 integration acceptance

Baseline: `feature/shadow-mapping-v1`, `52ee1ee3baeb924d1ed6e2f4d9f0c108f1a217b0`.
Delivery branch: `test/rome-integration-v1`. Date: 2026-10-09.

**Partial acceptance.** API, scene persistence, rendering invariants and regression checks pass. The 40-soldier photographic layout is **not approved**: the formation intersects a fountain, statue and market stalls. This report preserves those failures instead of treating numeric assertions as visual acceptance. Findings were reported in [Issue #4](https://github.com/anyeshizhong/mini3d/issues/4#issuecomment-6076881135); further material/architecture work awaits review.

Only test scripts, reports, scene recipes and actual GPU evidence were added. Renderer, Camera clipping, materials, Placement and AI API implementation remain at the baseline. No new dependency, mesh simplification, texture replacement or model binary is included. No merge to main.

## Reproduction and files

Use the existing Python environment with pygame, PyOpenGL and project dependencies, and an actual OpenGL GPU. The following commands require the original local GLBs identified in [assets.json](rome-integration/assets.json). The committed placement probe is an experimental input, not an approved staging layout.

```powershell
F:/gymenv/python.exe -B tests/rome_integration_smoke.py docs/rome-integration
F:/gymenv/python.exe -B tests/rome_integration_ui_smoke.py docs/rome-integration
F:/gymenv/python.exe -B tests/rome_added_models_smoke.py docs/rome-integration
```

Run sequentially; later scripts consume the first script's scene/camera recipes. Assets 09 and 10 are loaded by explicit path because they are not yet registered in the local manifest. The user's manifest and model files are not part of this commit.

- [Main experiment](../tests/rome_integration_smoke.py): Python and JSON API workflow, 1 / 3 / 40 soldiers, real mesh placement, transactions, cameras, PNG, persistence and timing.
- [Editor experiment](../tests/rome_integration_ui_smoke.py): captures actual Editor View and Camera View UI after settled frames.
- [Additional assets](../tests/rome_added_models_smoke.py): supplied PBR T-pose soldier, original Unlit Pantheon and existing 2048 shadow setting.
- [Results](rome-integration/results.json), [regressions](rome-integration/regression.json), [JSON calls](rome-integration/json-api-commands.json), [scene](rome-integration/rome-scene.json), [Shot poses](rome-integration/views.json). JSON calls are an audit transcript spanning fresh API instances; the script is the reproducible workflow.
- [Earlier complex library supplement](shadow-assets.md): real soldier/table/bottle/Fox/Rome, independent triangle-ray evidence and eight-soldier timings.

## 3+1 results

| Area | Evidence and outcome |
| --- | --- |
| Scene editing / placement | API spawn, transforms, duplicate, group rotation, transaction undo/redo, 5x8 formation and saved groups exercised. All 40 anchors re-raycast against actual Rome triangles; bounds bottoms match hits and soldiers stay upright. Layout quality fails as described below. |
| Lighting / shadows | Scene Lighting; direction `[1,-1,1.6]`, diffuse 2.5, ambient 0.22; shadows 1024, bias 0.0005, PCF enabled. Two Shot positions, off/on, depth images. City Unlit materials preserved. |
| Photography | Two 1920x1080, 35 mm, 16:9 city shots and two 50 mm PBR-stage shots. Off/on Camera depth arrays are equal; API PNG equals the Camera View render path exactly. Editor View and Camera View UI screenshots also captured. |
| AI API closure | Python plus JSON dispatcher create/control/capture/save/load workflow passes. v3 entities, groups, lighting and shadows round-trip. Recreating the separately recorded Shot Camera after load gives an identical PNG. |

Rome is scaled by 100; the original Roman scan by 0.07 (height 1.8174 world units). The formation uses 1.5 x 1.8 spacing. Actual scene: **41 roots, 257 draw primitives, 23,948,895 triangles, 23 unique meshes**. No placeholder soldiers or reduced meshes. Scales are presentation choices, not a claim about original asset units.

Focus, Frame All and orbit/pan/zoom clipping checks pass with the existing implementation. The focused view's bounding box can cross behind the camera; its positive-depth visible part remains inside the far plane. Exact near/far and bounds depths are in results.json. Shadow toggling changes no Camera depth values.

Original Rome is entirely `KHR_materials_unlit` (including a BLEND fire material). In two views, 2,030,830 / 1,926,180 visible city pixels remain exactly unchanged when shadows toggle. This is expected Unlit behavior, **not proof of city shadow reception**. Visible soldier pixels change by 9,448 / 14,834. A separate, explicitly created PBR ground receives 45,942 / 49,934 changed shadow pixels in two close views; it is not substituted for the city's materials.

## Actual GPU captures

All images are renderer/framebuffer output. Off/on pairs use the same camera and scene. The UI images include genuine editor chrome. Depth PNGs visualize the light's shadow depth buffer, not Camera depth.

| Scene / view | Shadows off | Shadows on | Light depth |
| --- | --- | --- | --- |
| Rome, overhead | [PNG](rome-integration/rome-view0-off.png) | [PNG](rome-integration/rome-view0-on.png) | [PNG](rome-integration/rome-view0-depth.png) |
| Rome, market | [PNG](rome-integration/rome-view1-off.png) | [PNG](rome-integration/rome-view1-on.png) | [PNG](rome-integration/rome-view0-depth.png) |
| PBR stage, view 0 | [PNG](rome-integration/stage-view0-off.png) | [1024 PNG](rome-integration/stage-view0-on.png) / [2048 PNG](rome-integration/stage-view0-2048.png) | [PNG](rome-integration/stage-view0-depth.png) |
| PBR stage, view 1 | [PNG](rome-integration/stage-view1-off.png) | [PNG](rome-integration/stage-view1-on.png) | [PNG](rome-integration/stage-view0-depth.png) |
| Added T-pose soldier / Pantheon | Local only | [PNG](rome-integration/added-models-on.png) | [PNG](rome-integration/added-models-depth.png) |

Representative actual UI: [Editor View, shadows on](rome-integration/editor-view1-on.png) and [Camera View, shadows on](rome-integration/camera-ui-view1-on.png).

At the user's request, only the review selection is committed. One/three-soldier process captures, reload duplicates, the obstructed trial camera, most UI permutations and added-models Off remain local and can be regenerated with the scripts. Identical depth maps from different camera positions share one committed PNG. The full test results remain in JSON/logs. Directory ignore rules prevent omitted generated PNGs from being accidentally committed again.

## Performance and regressions

Hardware: **Intel UHD Graphics 620**, Windows, Python 3.8.20. Full city plus 40 original 589,879-triangle soldiers, 1920x1080 Shot render. Median of five samples after warming; GPU timer query and synchronous CPU wall time including GPU completion. Readback/PNG encoding and ImGui are outside the timing interval. These are render timings, not full Editor FPS or peak VRAM measurements.

| Metric | Shadows off | Shadows on |
| --- | ---: | ---: |
| GPU time | 55.90 ms | 116.12 ms |
| Synchronous render wall time (CPU + GPU) | 135.09 ms | 223.66 ms |

229 existing unit tests pass. Ground, Placement V1/V2, Photography, AI API, Lighting, Lighting API/UI, Scene Clipping, Shadow and Shadow UI GPU regression scripts all exit 0. Raw logs are the corresponding `.txt` files in [rome-integration](rome-integration/); `unit.txt` records the test count. Main integration, real Editor capture and added-model experiments also exit 0. No renderer crash or GL error was observed in these runs. Existing Shadow regression measurements from this run are preserved separately in `shadow-regression-results.json`.

## Findings requiring review

1. **Placement/photographic quality fails.** A triangle hit establishes a geometric anchor, not a walkable road or a clear footprint. The selected 40 points span z=2.6586 to 4.5633 and intersect the fountain/market. Upright bounds-bottom placement cannot infer stairs, water or stalls. Review a manually authored clear formation using existing placement tools before calling the scene accepted. Automatic semantic placement/obstacle avoidance would need a separate approved task.
2. **Original city surfaces do not receive dynamic shadows.** Unlit rendering is preserved intentionally. Keep the explicit PBR-stage experiment for shadow validation. Converting the city to lit materials or replacing authored/baked lighting requires material review; no conversion was attempted.
3. **Shadow resolution is visibly limited.** A single 1024 map covering the scene produces coarse edges in close views. The same stage at the existing 2048 setting is included, and still shows sampling limits. No CSM, adaptive bounds, renderer refactor or silent bias tuning was added.
4. **Occlusion is not a Camera clipping regression.** The first low Shot position was blocked by a building; the rejected output is retained locally as `rejected-obstructed-camera.png`. The final first view moves above it. Model detail absent from both off/on images is not attributable to shadow toggling; source geometry/material completeness was not certified here.
5. **Scene v3 does not persist Shot Camera.** Scene content and light/shadow settings round-trip; `views.json` / `stage-views.json` hold Shot parameters and the scripts recreate them. Automatic persistence requires a separately reviewed change.
6. **Additional model coverage is only a smoke test.** Original PBR T-pose soldier and original Unlit Pantheon load and render together; off/on depth is equal. The Pantheon scan dominates and occludes part of the soldiers. This is not an approved composition or an isolated material validation of every primitive. Full original mesh counts are 280,624 and 668,640 triangles respectively.

These limits have been reported in Issue #4. Stop after this evidence delivery; no architecture, material or further migration work is authorized by this acceptance result.

## Asset attribution and license

Local GLB metadata, original source URLs, SHA-256, material extensions and counts are recorded in [assets.json](rome-integration/assets.json). GLBs/textures are not redistributed in this branch.

- [Roman legionnaire](https://sketchfab.com/3d-models/roman-legionnaire-40b87797180148e4bace023b6da0c45a), Geoffrey Marchal: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
- [Rome River Side](https://sketchfab.com/3d-models/rome-river-side-8521d86dcd9043eba0b518ccab430d0f), Shahriar Shahrabi: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- [Roman Soldier - T pose](https://sketchfab.com/3d-models/roman-soldier-t-pose-free-download-61cd5cae148042c38048bff2bd206af3), Andy woodhead: CC BY 4.0.
- [Agrippa Pantheon](https://sketchfab.com/3d-models/agrippa-pantheon-074e9fe9154f41169cb2e79f5330e58f), Fovea: CC BY 4.0.

Screenshots containing the Geoffrey Marchal model are distributed as adapted renders under CC BY-NC-SA 4.0 with the above attribution; they are not relicensed as MIT code. Changes shown are entity scaling/placement, duplication, camera composition and lighting/shadow rendering; original mesh/texture/material data is preserved. Other asset attribution remains applicable to composite images. New scripts are project test code; no additional external renderer source was copied. Existing Shadow V1 source/license attribution remains in [the baseline report](shadow-mapping-v1.md).
