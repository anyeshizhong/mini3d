# Mini3D UI: task workspaces

This UI change is about **a person being able to complete a scene and take a photograph**, not maximizing the number of buttons, scripts, or unit tests.

## Reference products / design rationale

The interaction model borrows established patterns, but not their source code, assets, or visual branding:

| Product | Public reference | Adopted pattern | Deliberately not copied |
| --- | --- | --- | --- |
| Blender | https://docs.blender.org/manual/en/latest/interface/window_system/workspaces.html | Task-specific workspaces; big 3D viewport; separate outliner and properties | Modeling/timeline/editor multiplicity |
| Unity | https://docs.unity.com/en-us/engine/7000.0/manual/unity-editor/editor-windows-views-reference | Asset / Hierarchy / Scene / Inspector responsibility split | Game-object component system |
| Godot | https://docs.godotengine.org/en/stable/getting_started/introduction/first_look_at_the_editor.html | Scene tree selection drives Inspector; file/assets in independent dock | Node editor and full docking system |

The current UI is built on **pyimgui 2.0**, which has no ImGui docking extension in this project. This proposal keeps the existing deterministic panels rather than creating fragile fake docking logic. It does **not** claim Blender-level window dragging and docking.

Current layout, Gemini collaboration and actual acceptance: [UI refactor review](editor-ui-review.md). Startup presentation: [startup analysis](editor-startup.md).

## Current workflow

- Primary workflow in the full-width header: **Arrange / Lighting / Shot**.
- Arrange: selection, G/R/S, Surface Move, Place on Surface, World/Local, placement anchor, focus/frame, grid.
- Lighting: the Inspector displays actual world-space directional-light vector, direct/ambient strength and shadows. This is sunlight **direction**, not a movable lamp entity. Shot Camera always uses Scene lighting.
- Shot: create from Editor View, switch to Camera View, set focal length and aspect ratio, capture PNG. The Inspector displays camera state and next-step hints.
- Optional asset library: automatically visible in Arrange and hidden in Lighting/Shot to reclaim viewport area. **Show library** toggles it back without losing selection.
- Assets: fixed **Add to scene**, a separately scrolling model list, and **Quick add → Ground Mesh**, preserving model import and drag/drop.
- Scene Outliner: search by root entity name; selection/group/lock controls remain.
- Object Inspector: Name and Transform come first; Formation remains available below Placement. Sidebar widths and the Outliner/Inspector divider can be dragged.
- Help includes the three-step workflow. Existing keyboard shortcuts and top menus remain.
- Renderer, scene data, API, command history, transforms and persistence have **not** been rewritten.

## Quick start

1. Run `python editor.py --empty` from the project root using the existing environment.
2. **Arrange:** use `Quick add → Ground Mesh`; import or drag a Roman legionnaire onto it. Select the object; drag the gizmo or edit Inspector X/Y/Z. Ground Mesh starts as 10 x 10; Inspector Scale X/Y increases area. Lock the ground when finished.
3. **Lighting:** set Preview to **Scene Lighting**, adjust the **direction toward light**, Direct strength, Ambient strength, and Scene shadows in the right Inspector.
4. **Shot:** frame the scene with the editor camera, click **Create Camera From View** in the right Inspector, switch to **Camera View**, set lens/ratio, and click **Capture**. PNG files are written to `captures/`.
5. Save with `Ctrl+S`, reopen with `Ctrl+O`. Scene JSON saves only when requested; simply changing workspace does not save.
6. If the scene seems lost, switch to Arrange and use **Frame all** or `Home`.

## Manual user acceptance (required before merging)

This is not satisfied merely by source checks. Test on a real desktop OpenGL context, including a 1440x900 editor window and a smaller resized window:

- [ ] Launch editor from the branch; no pyimgui assertion, no white/blank viewport.
- [ ] In Arrange, add a Ground Mesh and move/rotate/scale it. Drag a model from Assets, then select it in Scene Outliner.
- [ ] Verify left shelf hidden in Lighting and Shot; **Show library** restores shelf; resize and ensure no buttons overlap the working image.
- [ ] Scene search filters model roots without deleting any models.
- [ ] World/local gizmos, Surface Move, Place on Surface, Undo/Redo and Formation still operate, including after switching back from Shot.
- [ ] Lighting Inspector updates the actual scene and shadow preview. An invalid zero direction reports an error instead of crashing.
- [ ] Shot Camera is created from the editor view, camera preview locks the view, lens/ratio work, Capture saves a clean PNG.
- [ ] Switching from Camera View to Arrange returns to Editor View and restores object manipulation.
- [ ] Save scene / relaunch / load scene and verify object transforms, light state and Shot Camera.
- [ ] Codex/API connection on this branch still references the same Scene; UI changes do not create a duplicate editor.
- [ ] Have an actual user who has not read the code try this without prompts. Record where they get stuck and revise accordingly.

## Limits and planned follow-up

The later [editor quality improvements](editor-quality-improvements.md) share
the clean Scene-lit photo preview between both views in Shot, retain its aspect
in Editor View, and display the actual copied focal length. That follow-up also
adds value-based viewport/depth caching without replacing Scene or Commands.

This first iteration is **not yet a production UX certification**. It improves information architecture while retaining the proven pyimgui 2.0 panel system. True docking, localization, visual icons, keyboard-accessible tooltips and a proper Undo/history view remain follow-up work and should be driven by a manual usability run, not added speculatively. Do not merge purely because unit tests pass.
