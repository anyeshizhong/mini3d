# Fixed studio environment

Environment: **Studio Small 02**, author **Greg Zaal** (HDRI Haven / Poly Haven).
The HDR image itself is **CC0-1.0**, independently confirmed on its
[asset page](https://polyhaven.com/a/studio_small_02) and
[asset license page](https://polyhaven.com/license).
Filament distributes it alongside [CC0.html](CC0.html).

Pinned source mirror:
[Filament `studio_small_02_2k.hdr`](https://github.com/google/filament/blob/764fe6cac9bdb4ba24d3d852344dfa04a5f70f75/third_party/environments/studio_small_02_2k.hdr).
Source SHA-256: `8dee8bd1f47b6e723284a58bd0a2db12e3cd3bc70283e17707d06b6b142065e0`.

`neutral.npz` contains CC0-derived Lambertian and GGX environment pixels and a
numerically integrated BRDF LUT. It is generated offline by the pinned Khronos
shaders; their license/attribution is recorded in
[tools/ibl/upstream/NOTICE.md](../../../tools/ibl/upstream/NOTICE.md).
No third-party BRDF PNG is included. The original HDR need not be shipped at
runtime. No exposure, intensity scale, white balance or saturation transformation
was applied during baking (`1.0` exposure / scale). This is a studio with neutral
light sources, not a perfectly achromatic synthetic environment.

The bake changes only projection, Lambertian/GGX convolution, resolution and
FP16 storage. `neutral.json` records bake settings, source/output SHA-256,
hardware, time and nominal texture bytes. No runtime download or convolution.
