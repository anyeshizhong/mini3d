# Photography resources (CC0-1.0)

Sky: [Belfast Sunset (Pure Sky)](https://polyhaven.com/a/belfast_sunset_puresky),
photography by Dimitrios Savva, processing by Greg Zaal, sky edits by Jarod Guest.
Bundled 2K Radiance HDR downloaded from:
https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/belfast_sunset_puresky_2k.hdr

Ground: [Sandy Gravel 02](https://polyhaven.com/a/sandy_gravel_02), by Dario Barresi.
Bundled 1K maps, original measured tile width 2.5 metres:

- https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/sandy_gravel_02/sandy_gravel_02_diff_1k.jpg
- https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/sandy_gravel_02/sandy_gravel_02_nor_gl_1k.png
- https://dl.polyhaven.org/file/ph-assets/Textures/png/1k/sandy_gravel_02/sandy_gravel_02_arm_1k.png

All assets are CC0: https://polyhaven.com/license
The licence permits redistribution and inclusion in products. The CC0 text is
also retained in `../ibl/CC0.html`. File hashes are recorded in `manifest.json`.

Normal and ARM maps are repacked as RGB8 PNG. Their decoded RGB bytes match
exactly what the renderer decoded from the original RGB16 PNG; this reduces
repository size without changing GPU input. ARM stores AO / roughness / metal.

`sunset_ibl.npz` is a derived Lambert/GGX environment, generated with 256 samples
by `python tools/bake_photographic_sky.py --headless`. Filtering uses the pinned
Khronos shader sources and licence notices in `tools/ibl/upstream`. The small
solar disc is removed from the ambient input so that the separate shadowed sun
is not counted twice. The backdrop retains the original HDR radiance.

The filmic output is the commonly used ACES approximation from Krzysztof
Narkowicz (formula only; not a full ACES colour pipeline):
https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/
