# Terrain material height fixtures — CC0-1.0

These are displacement maps from the same Poly Haven materials used by the
LAB-02B material experiment. Poly Haven publishes these assets under CC0.
The asset pages, creators, display tile widths, and source PNG bit depths are:

| Experiment layer | Asset | Author | Tile width | Source PNG |
| --- | --- | --- | ---: | ---: |
| Soil | [Brown Mud 02](https://polyhaven.com/a/brown_mud_02) | Rob Tuytel | 1.3 m | 8-bit |
| Rock | [Rock Face](https://polyhaven.com/a/rock_face) | Dario Barresi (processing), Greg Zaal (photography) | 2.4 m | 16-bit |
| Grass | [Leafy Grass](https://polyhaven.com/a/leafy_grass) | Charlotte Baglioni | 2 m | 16-bit |

[Poly Haven asset license](https://polyhaven.com/license) · CC0-1.0.
The retained CC0 legal text is [CC0.html](../../../../mini3d/resources/ibl/CC0.html).
Source URLs, API-reported sizes and MD5 values, downloaded SHA-256 values,
output hashes, dimensions, ranges, and measured resampling errors are recorded
in `manifest.json`. The 1K source PNGs stay in the ignored
`captures/world-surroundings/material-height-source` cache.

The bundled inputs are 256×256 single-channel uint16 PNGs. A source 8-bit
sample is mapped to the same 16-bit code space as `sample * 257`; 16-bit source
samples are kept unchanged. Each output pixel is the arithmetic mean of its
corresponding 4×4 source block, rounded half-up to the nearest uint16 code.
This is linear scalar processing: source PNG gAMA/sRGB/color-profile chunks are
ignored and omitted from the output, and each image keeps its original numeric
range. No per-image contrast stretch or normalization is performed. Row zero
and column zero retain the source orientation. Interpret an output sample as
`sample / 65535.0` for normalized displacement.

Reproduce from the repository root with:

```powershell
F:/gymenv/python.exe -B experiments/world-surroundings/prepare_quality_assets.py
```

The preparation script checks the live official API metadata before accepting
cached or downloaded files. Runtime rendering reads the bundled maps offline.
