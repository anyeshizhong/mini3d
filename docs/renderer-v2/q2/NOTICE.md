# Q2 reference assets and renders

Lantern and Avocado `.blend` files contain the original imported meshes and
packed original texture pixels. The photographs are genuine Eevee/Mini3D 3D
renders. Contact sheets, absolute difference images and nearest-neighbor crops
are explicitly labeled derived comparisons; they do not replace raw PNGs.

Asset/license audit and downloaded GLB content are pinned to Khronos glTF
Sample Assets `edc7c9e67c639d230715049ee31f9a96a6babbbe`:

- **Lantern**: © 2017 Microsoft, initial version by **sbtron**, CC0;
  © 2018 **Frank Galligan**, Draco compression, CC0.
  [Original attribution](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/edc7c9e67c639d230715049ee31f9a96a6babbbe/Models/Lantern/README.md).
  [Original GLB](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/edc7c9e67c639d230715049ee31f9a96a6babbbe/Models/Lantern/glTF-Binary/Lantern.glb),
  SHA-256 `a79458c4b02d695187a952f23a63b8bf278e7bc3d316a3c2a314f2d6974181f1`.
- **Avocado**: © 2017 Public, **Microsoft**, CC0.
  [Original attribution](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/edc7c9e67c639d230715049ee31f9a96a6babbbe/Models/Avocado/README.md).
  [Original GLB](https://github.com/KhronosGroup/glTF-Sample-Assets/blob/edc7c9e67c639d230715049ee31f9a96a6babbbe/Models/Avocado/glTF-Binary/Avocado.glb),
  SHA-256 `ccc9c3ce56423720b09399c2351537207cd5a65f859f9e6e2f30922762f3abd4`.
- **Studio Small 02**: **Greg Zaal**, CC0; independently verified at
  [Poly Haven's asset page](https://polyhaven.com/a/studio_small_02) and
  [asset license](https://polyhaven.com/license).
  The unchanged HDR in `assets/studio_small_02_2k.hdr` comes from
  [Filament commit 764fe6cac9bdb4ba24d3d852344dfa04a5f70f75](https://github.com/google/filament/blob/764fe6cac9bdb4ba24d3d852344dfa04a5f70f75/third_party/environments/studio_small_02_2k.hdr).
  SHA-256 `8dee8bd1f47b6e723284a58bd0a2db12e3cd3bc70283e17707d06b6b142065e0`.
  Full [CC0 text already distributed in Mini3D](../../../mini3d/resources/ibl/CC0.html).
  Q1's prefiltered maps are unchanged; see [Q1 resource notice](../../../mini3d/resources/ibl/NOTICE.md).
- Spheres, stage and scripts: original Mini3D procedural fixtures/code;
  Q1 sphere geometry and authored normals are retained in the main comparison.

**Blender**: Blender Foundation and contributors, GPL-3.0-or-later.
Used as a separate unmodified offline executable, **3.6.23**, build `e467db79ca8c`.
[Official license](https://www.blender.org/about/license/),
[fixed source release](https://github.com/blender/blender/tree/v3.6.23).
The executable is not redistributed in this repository. No Blender GPL source
or Shader implementation is copied into Mini3D. The custom compositor and
alignment scripts are original code calling Blender's public Python API.

The `.blend` files reference the one shared relative HDR; all imported glTF
texture images are packed. Geometry is transformed/normalized to Q1 scene
units, not remodeled. Lighting/color management are documented in
[quality-q2.md](../quality-q2.md). Diagnostic sphere photos deliberately change
shadow enablement or normals and are not part of the equal-input A/B matrix.
