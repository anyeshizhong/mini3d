# Terrain material fixtures — CC0-1.0

These are real photographed PBR textures from Poly Haven, not generated colour
swatches. The original asset pages, authors and measured tile widths are:

| Experiment layer | Asset | Author | Tile width |
| --- | --- | --- | --- |
| Soil | [Brown Mud 02](https://polyhaven.com/a/brown_mud_02) | Rob Tuytel | 1.3 m |
| Rock | [Rock Face](https://polyhaven.com/a/rock_face) | Dario Barresi (processing), Greg Zaal (photography) | 2.4 m |
| Grass | [Leafy Grass](https://polyhaven.com/a/leafy_grass) | Charlotte Baglioni | 2 m |

[Poly Haven's asset license is CC0](https://polyhaven.com/license).
The retained license text is [CC0.html](../../../../mini3d/resources/ibl/CC0.html).
Asset metadata and license were checked on 2026-10-19. No upstream code was
copied, and no additional engine dependency was introduced.

Each layer contains `diff.png` (sRGB base colour), `nor_gl.png` (OpenGL +Y
tangent-space normal, linear data) and `rough.png` (linear roughness, read from
the first channel). Original 1K JPG/PNG download URLs, upstream byte counts and
SHA256 hashes, bundled hashes and dimensions are recorded in `manifest.json`.
The original maps remain in the ignored `captures/world-surroundings/material-source`.

The bundled maps are 256×256 RGB8 PNGs. Preparation decodes to RGB8 with Pillow,
resizes with Lanczos, and renormalizes the decoded normal vectors after resizing.
The colour resize is performed on the encoded sRGB fixture; runtime material
mixing separately decodes sRGB to linear light. This downsample is an experiment
size choice, not a claim of full source fidelity. No displacement or geometry
is derived from these maps.

Reproduce with `prepare_material_assets.py` from the experiment root. The script
verifies upstream hashes against the existing manifest and refuses changed
upstream content. Runtime painting is offline and does not fetch assets.
