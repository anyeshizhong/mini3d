# Scene bundle contract (offline v1 / live v2)

All numbers little endian. `u32`, `f32`, `f64`; matrices row major, act on column vectors. Strings = u32 UTF-8 byte length + bytes. Arrays have counts stated below. No Python objects or GL handles serialized. Bundles can be exported offline or rebuilt from the live editor after resource edits; camera frames and lighting globals update separately.

`scene.bin`:
1. 8 bytes `SPQRN001`; u32 version=1.
2. u32 texture count. Each texture: u32 target (GL_TEXTURE_2D or GL_TEXTURE_CUBE_MAP), u32 original internal format, u32 min_filter, mag_filter, wrap_s, wrap_t, wrap_r; u32 mip count. For each mip: u32 width,height; then face data (1 face for 2D, 6 positive-X onwards for cube), width*height*4 f32 values obtained by GL_RGBA/GL_FLOAT readback. Native uploads using original internal format, external GL_RGBA/GL_FLOAT. No mip generation; all original levels exported. Texture index 0xffffffff = none. Exclude live shadow depth.
3. UniformBlock material globals; UniformBlock sky globals. Block = u32 count then for each: string name, u32 GL uniform type, u32 scalar component count, raw values: i32 for GL_INT/GL_BOOL/samplers, f32 otherwise. Matrices row-major; native uploads transpose=true. Uniform array names retained. Locations not serialized.
4. u32 material count. Each: UniformBlock material parameters; u32 flags (bit0 doubleSided); 13 u32 texture indices, one per texture unit (7/12 always none, bound at runtime). Texture IDs refer to texture list, target included there.
5. u32 mesh count. Each: u32 material index, u32 vertex count,index count; f64 local bounds[6] (lo xyz, hi xyz); f32 vertices[vertex_count*12] (pos3 normal3 uv2 color4); u32 indices[index_count].
6. u32 entity count. Each: string stable entity ID/name; u32 mesh index; u32 flags (bit0 photographicGround, bit1 mirrored); f64 world[16]; f32 normal[9]. Entities in original flat scene order; editable root IDs may repeat across primitives, stable string contains root ID plus primitive name/index.
7. u32 opaque order count; that many u32 entity indices, opaque order obtained from OpaqueOrder on full photographic scene. Preserve coplanar ordering. MASK/BLEND retain original constraints.
8. f64 light direction[3] (scene_light_direction), u32 shadow resolution, f32 shadow bias,normal_bias,strength; u32 shadow enabled; f64 ground_z.

`frames.bin`: 8 bytes `SPQRF001`; u32 count. Each frame: string route; f64 t; f64 position[3],rotation[9],view[16],projection[16]; f64 near,far. Camera path data only, no fitted shadow matrices or precomputed visible membership. Native computes culling and shadow fit per frame and updates following ground world transform (scale 2*far; xy=position.xy; z=ground_z).

`shadow_cases.bin`: optional numeric verification fixture, format separately documented by exporter, contains Python reference light matrices for camera fixtures. Not read during native benchmarks.

`shaders/`: material.vert/.frag, sky.vert/.frag, shadow.vert/.frag copied exactly from existing Python GLSL constants (no reimplemented lighting). Other shader exports optional. `metadata.json`: source hashes, counts, quality, route/capture mapping and limitations. Native must reject unsupported legacy material entities, malformed bundles, texture/uniform types or HDR assets rather than silently simplify.

Material, mesh and entity counts may be zero for an empty editor scene; globals
still describe its background. Every existing index must remain in range.

## Live v2 and shared-context extensions

The Python editor writes the same `SPQRN001` magic with version=2. After the
texture count, each texture is exactly `u32 GL target, u32 borrowed GL handle`.
No internal format, sampler parameters, mip count, dimensions or pixels follow.
The remainder of the file (UniformBlocks, materials, meshes, entities, opaque
order and lighting settings) is identical to v1. Handles must be nonzero 2D or
cube textures in the caller's current WGL context. They are process-local
references, not portable assets. `loadBundle` rejects v2 by default;
`spqr_photo_create_shared` explicitly enables it. The old `spqr_photo_create`
and standalone viewer continue to accept v1 and reject v2.

Native validates borrowed texture existence/target, borrows their storage and
sampling parameters, and never uploads, modifies or deletes them. Python's
MaterialRenderer / Environment owners must outlive the native renderer, including
failed construction and rebuilds. The current context/thread restrictions also
apply to the additional C exports; the numeric ABI version remains 1.

`spqr_photo_transforms(instance, indices, worlds16, normals9, mirrored, count)`
updates existing bundle entities by u32 index. Worlds are row-major f64[16],
normals are row-major f32[9], and mirrored is u32 0/1 per row. The C++ renderer
validates count, pointers, every index, finite normals and finite affine worlds
before committing any row. It preserves photographic-ground flags and updates
mirrored winding, then invalidates shadow fitting/depth caches once per batch.
Normals are supplied by the same Python pseudoinverse calculation as a complete
export, so imported mirrored/singular transforms keep the same semantics.
Pure transforms do not export resources; topology, visibility or material
changes still rebuild the bundle. Invalid batches leave the old scene intact.

The renderer is shared by the editor's Arrange and Shot scene passes. UI,
editing commands, overlays and Python API remain in Python. The `spqr_photo`
DLL name and ABI v1 remain compatible with existing Shot integrations.

The native stable-shadow mode additionally requires `shaders/shadow_cascade.glsl`.
Original base shader files and scene bundle settings remain reference inputs.
At runtime the viewer replaces only the material shadow function with this native
extension, retains the bundle's far shadow map, and adds a 4096 stable near map
(camera split .02–18 world units, blend 12–16). `--legacy-shadows` skips the
extension and second map. Benchmark JSON records the effective mode; metadata
quality describes the exported Python reference, not all runtime overrides.
