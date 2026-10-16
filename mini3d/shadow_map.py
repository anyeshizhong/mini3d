"""Directional depth pass, adapted from iamyoukou/shadowMapping (MIT).

Copyright (c) 2021, Jiang Ye. See third_party/shadowMapping/LICENSE and
docs/shadow-mapping-v1.md for the pinned source and adaptation mapping.
Both editor and Shot Camera fit conservative receiver/caster bounds.
"""
from itertools import product

import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader

from .lighting import scene_light_direction


# Adapted light-space divide/remap, depth comparison and 3x3 PCF from
# shader/fsScene.glsl. Visibility multiplies direct radiance, never scene color.
SHADOW_GLSL = """
uniform bool shadowEnabled, shadowPCF;
uniform sampler2DShadow shadowDepth;
uniform sampler2D shadowRaw;
uniform float sunRadius;
uniform vec3 shadowWorldScale;
uniform mat4 shadowMatrix;
uniform float shadowBias;
float shadowVisibility(vec3 world, vec3 normal, vec3 light) {
    if (!shadowEnabled) return 1.0;
    vec4 p = shadowMatrix * vec4(world, 1.0);
    vec3 q = p.xyz / p.w * 0.5 + 0.5;
    if (any(lessThan(q, vec3(0.0))) || any(greaterThan(q, vec3(1.0)))) return 1.0;
    float bias = shadowBias * (1.0 + 4.0 * (1.0 - max(dot(normal, light), 0.0)));
    vec2 texel = 1.0 / vec2(textureSize(shadowDepth, 0));
    // Orthographic PCSS: search raw blocker depths, then filter comparisons.
    // Sun radius is angular; blocker distance sets the penumbra in world units.
    if (shadowPCF && sunRadius>0.0) {
        const vec2 disk[16]=vec2[16](vec2(0,0),vec2(-.63,-.47),vec2(.67,.48),
            vec2(.44,-.77),vec2(-.49,.73),vec2(-.89,.14),vec2(.87,-.16),
            vec2(.15,.93),vec2(-.13,-.94),vec2(.29,.26),vec2(-.28,-.23),
            vec2(-.37,.31),vec2(.32,-.34),vec2(.73,-.61),vec2(-.76,-.60),vec2(-.70,.60));
        vec2 search=max(texel,shadowWorldScale.xy*sunRadius*q.z*shadowWorldScale.z);
        search=min(search,vec2(.03));
        float sum=0.0, count=0.0;
        for (int i=0;i<16;++i) {
            float depth=texture(shadowRaw,q.xy+disk[i]*search).r;
            if (depth<q.z-bias) {sum+=depth;count+=1.0;}
        }
        if (count==0.0) return 1.0;
        float separation=max(0.0,(q.z-sum/count)*shadowWorldScale.z);
        vec2 width=max(texel*.65,shadowWorldScale.xy*sunRadius*separation);
        width=min(width,vec2(.03));
        float soft=0.0;
        for (int i=0;i<16;++i)
            soft+=texture(shadowDepth,vec3(q.xy+disk[i]*width,q.z-bias));
        return soft/16.0;
    }
    float visibility = 0.0;
    int radius = shadowPCF ? 1 : 0;
    // Filtering the comparison results (hardware PCF) keeps fractional texel
    // motion smooth. Interpolating raw depths would create false blockers.
    vec2 center = shadowPCF ? q.xy : (floor(q.xy / texel) + 0.5) * texel;
    for (int x = -radius; x <= radius; ++x)
        for (int y = -radius; y <= radius; ++y) {
            visibility += texture(shadowDepth, vec3(center + vec2(x,y)*texel, q.z - bias));
        }
    return visibility / (shadowPCF ? 9.0 : 1.0);
}
"""

DEPTH_VERTEX = """#version 330 core
layout(location=0) in vec3 position;
layout(location=2) in vec2 texcoord;
layout(location=3) in vec4 color;
layout(location=4) in mat4 instanceModel;
uniform mat4 model, lightMatrix;
uniform bool useInstances;
out vec2 uv;
out float alpha;
void main() {
    uv = texcoord; alpha = color.a;
    gl_Position = lightMatrix * (useInstances ? instanceModel : model) * vec4(position, 1.0);
}
"""
DEPTH_FRAGMENT = """#version 330 core
in vec2 uv;
in float alpha;
uniform bool alphaMask, hasBase;
uniform float baseAlpha, cutoff;
uniform sampler2D baseMap;
void main() {
    if (alphaMask) {
        float a = baseAlpha * alpha;
        if (hasBase) a *= texture(baseMap, uv).a;
        if (a < cutoff) discard;
    }
}
"""


def light_matrix(entities, direction, camera=None, resolution=1024, aspect=None, geometry_cache=None,
                 prepared=None):
    """Cached AABBs; optional Shot receiver fit with whole-scene fallback."""
    if camera is not None:
        from .shadow_fit import receiver_matrix
        if not isinstance(entities, list):
            entities = list(entities)
        fitted = receiver_matrix(entities, direction, camera, resolution, aspect=aspect,
                                 geometry_cache=geometry_cache, prepared=prepared)
        if fitted is not None:
            return fitted
    light = np.array(direction, dtype=np.float64, copy=True)
    light /= np.max(np.abs(light))
    light /= np.linalg.norm(light)
    up = np.eye(3)[np.argmin(np.abs(light))]
    right = np.cross(up, light)
    right /= np.linalg.norm(right)
    rotation = np.stack((right, np.cross(light, right), light))
    boxes = []
    for entity in entities:
        record = None if prepared is None else prepared.records.get(id(entity))
        geometry = None if record is None else record['geometry']
        if geometry is not None:
            boxes.append(geometry[2] @ rotation.T)
            continue
        bounds = getattr(entity.model, 'bounds', None)
        if bounds is None:
            continue
        corners = np.array(list(product(*zip(*bounds))), dtype=np.float64)
        world = np.asarray(entity.world_matrix, dtype=np.float64)
        boxes.append((corners @ world[:3,:3].T + world[:3,3]) @ rotation.T)
    if not boxes:
        return None
    points = np.concatenate(boxes)
    lo, hi = points.min(axis=0), points.max(axis=0)
    extent = hi-lo
    margin = max(float(extent.max()) * .02, 1e-12)
    lo -= margin
    hi += margin
    # Light camera looks down -Z: points towards +light are closer (depth 0).
    scale = 2 / (hi-lo)
    scale[2] *= -1
    matrix = np.eye(4)
    matrix[:3,:3] = scale[:,None] * rotation
    matrix[:3,3] = -scale * ((lo+hi)*.5)
    return matrix


def _shadow_input_key(entities, geometry=None):
    """Small shared-material signatures plus already checked instance tokens."""
    if geometry is not None and entities is geometry.entities:
        return id(geometry), geometry.revision
    materials, records = {}, []
    for entity in entities:
        mesh = entity.model
        mid = id(mesh)
        if mid not in materials:
            material = getattr(mesh, 'material', None) or {}
            tex = material.get('textures', {}).get('baseColor') or {}
            materials[mid] = (material.get('alphaMode', 'OPAQUE'),
                material.get('alphaCutoff', .5),
                tuple(material.get('pbrMetallicRoughness', {}).get('baseColorFactor', [1]*4)),
                id(tex.get('image')), tuple(sorted(tex.get('sampler', {}).items())),
                bool(material.get('extras', {}).get('photographicGround')))
        source = None if geometry is None else geometry.records.get(id(entity))
        if source is None:
            stamp = (np.asarray(entity.world_matrix).tobytes(),
                     np.asarray(getattr(mesh, 'bounds', None)).tobytes())
        else:
            stamp = source.get('token', source['key'])
        records.append((mid, stamp, materials[mid]))
    return tuple(records)


class ShadowMap:
    """One lazy depth texture/FBO. GPU geometry is owned by existing renderers."""
    UNIT = 7  # MaterialRenderer uses units 0..6.

    def __init__(self):
        self.fbo = self.texture = self.program = self.size = self.raw_sampler = 0
        self.matrix = None
        self._cache_key = None
        self.cache_hit = False
        self.gpu_instancing = True
        self._locations = {}
        self._geometry_cache = {}
        self._instance_payloads = {}

    def _allocate(self, size):
        if self.size == size:
            return
        if size > int(gl.glGetIntegerv(gl.GL_MAX_TEXTURE_SIZE)):
            raise ValueError('Shadow resolution exceeds GL_MAX_TEXTURE_SIZE')
        self.close()
        try:
            self.program = compileProgram(compileShader(DEPTH_VERTEX, gl.GL_VERTEX_SHADER),
                                          compileShader(DEPTH_FRAGMENT, gl.GL_FRAGMENT_SHADER))
            self.texture = int(gl.glGenTextures(1))
            self.raw_sampler=int(gl.glGenSamplers(1))
            gl.glSamplerParameteri(self.raw_sampler,gl.GL_TEXTURE_COMPARE_MODE,gl.GL_NONE)
            for p in (gl.GL_TEXTURE_MIN_FILTER,gl.GL_TEXTURE_MAG_FILTER):
                gl.glSamplerParameteri(self.raw_sampler,p,gl.GL_NEAREST)
            for p in (gl.GL_TEXTURE_WRAP_S,gl.GL_TEXTURE_WRAP_T):
                gl.glSamplerParameteri(self.raw_sampler,p,gl.GL_CLAMP_TO_BORDER)
            gl.glSamplerParameterfv(self.raw_sampler,gl.GL_TEXTURE_BORDER_COLOR,np.ones(4,np.float32))
            gl.glActiveTexture(gl.GL_TEXTURE0+self.UNIT)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
            # Port of src/main.cpp depth attachment setup; depth-only FBO.
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_DEPTH_COMPONENT24, size, size,
                            0, gl.GL_DEPTH_COMPONENT, gl.GL_FLOAT, None)
            for param in (gl.GL_TEXTURE_MIN_FILTER, gl.GL_TEXTURE_MAG_FILTER):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, param, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_COMPARE_MODE, gl.GL_COMPARE_REF_TO_TEXTURE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_COMPARE_FUNC, gl.GL_LEQUAL)
            for param in (gl.GL_TEXTURE_WRAP_S, gl.GL_TEXTURE_WRAP_T):
                gl.glTexParameteri(gl.GL_TEXTURE_2D, param, gl.GL_CLAMP_TO_BORDER)
            gl.glTexParameterfv(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_BORDER_COLOR, np.ones(4,np.float32))
            self.fbo = int(gl.glGenFramebuffers(1))
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.fbo)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                      gl.GL_TEXTURE_2D, self.texture, 0)
            gl.glDrawBuffer(gl.GL_NONE)
            gl.glReadBuffer(gl.GL_NONE)
            if gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER) != gl.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError('Incomplete shadow depth framebuffer')
            self.size = size
        except Exception:
            self.close()
            raise

    def render(self, entities, scene, renderer, camera=None, aspect=None, geometry=None):
        self.draw_calls = self.triangles = 0
        self.cache_hit = False
        from .gl_state import save_state, restore_state
        if not isinstance(entities, list):
            entities = list(entities)
        # Mesh/texture payloads are immutable GPU resources; small mutable
        # transform, bound and cutout inputs are compared on every call.
        direction = scene_light_direction(scene)
        records = _shadow_input_key(entities, geometry)
        camera_key = None if camera is None else (
            np.asarray(camera.view_matrix).tobytes(),
            np.asarray(camera.projection_matrix(camera.aspect if aspect is None else aspect)).tobytes())
        key = (scene.shadow_resolution, np.asarray(direction).tobytes(), camera_key, records)
        if self.matrix is not None and key == self._cache_key:
            self.cache_hit = True
            return
        self._cache_key = None
        matrix = light_matrix(entities, direction, camera, scene.shadow_resolution,
                              aspect=aspect, geometry_cache=self._geometry_cache, prepared=geometry)
        if matrix is None:
            self.matrix = None
            return
        state = save_state()
        draw = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
        read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
        viewport = gl.glGetIntegerv(gl.GL_VIEWPORT)
        clear = float(gl.glGetDoublev(gl.GL_DEPTH_CLEAR_VALUE))
        depth_range = gl.glGetDoublev(gl.GL_DEPTH_RANGE)
        try:
            self._allocate(scene.shadow_resolution)
            self.matrix = matrix
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.fbo)
            gl.glViewport(0, 0, self.size, self.size)
            for cap in (gl.GL_SCISSOR_TEST, gl.GL_STENCIL_TEST, gl.GL_BLEND,
                        gl.GL_CULL_FACE, gl.GL_POLYGON_OFFSET_FILL, gl.GL_RASTERIZER_DISCARD):
                gl.glDisable(cap)
            # Upstream slope-scale raster bias; no model displacement or front-face culling.
            gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
            gl.glPolygonOffset(2.0, 4.0)
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthFunc(gl.GL_LESS)
            gl.glDepthMask(True)
            gl.glDepthRange(0, 1)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
            gl.glClearDepth(1)
            gl.glClear(gl.GL_DEPTH_BUFFER_BIT)
            gl.glUseProgram(self.program)
            if not self._locations:
                self._locations = {name: gl.glGetUniformLocation(self.program, name) for name in
                    ('lightMatrix', 'baseMap', 'alphaMask', 'hasBase', 'baseAlpha', 'cutoff', 'model', 'useInstances')}
            loc = self._locations.__getitem__
            gl.glUniformMatrix4fv(loc('lightMatrix'),1,gl.GL_TRUE,np.asarray(matrix,np.float32))
            gl.glUniform1i(loc('baseMap'),0)
            # Only reject geometry outside the actual light clip volume.
            # Color-camera visibility must never remove offscreen casters.
            from .render_plan import batch_world_bounds, aabb_visible, frustum_planes
            if geometry is not None and entities is geometry.entities:
                bounds = geometry.bounds
            elif geometry is not None:
                bounds = []
                for entity in entities:
                    source = geometry.records.get(id(entity))
                    if source is None:
                        bounds.extend(batch_world_bounds([entity]))
                    else:
                        bound = source['geometry']
                        bounds.append(None if bound is None else bound[3])
            else:
                bounds = batch_world_bounds(entities)
            tested = [i for i, bound in enumerate(bounds) if bound is not None]
            visible = np.ones(len(entities), dtype=bool)
            if tested:
                visible[tested] = aabb_visible([bounds[i] for i in tested],
                                              frustum_planes(np.eye(4), matrix))
            self.culled_casters = int((~visible).sum())
            groups, individual = {}, []
            for entity, keep in zip(entities, visible):
                if not keep:
                    continue
                material = getattr(entity.model, 'material', None)
                if (material or {}).get('extras',{}).get('photographicGround'):
                    continue  # Receives shadows, never occludes geometry above.
                if material is not None and material.get('alphaMode') == 'BLEND':
                    continue
                if (self.gpu_instancing and material is not None and
                        material.get('alphaMode', 'OPAQUE') == 'OPAQUE'):
                    groups.setdefault(id(entity.model), []).append(entity)
                else:
                    individual.append(entity)
            gl.glUniform1i(loc('alphaMask'),False)
            used_payloads = {}
            for batch in groups.values():
                if len(batch) < 2:
                    individual.extend(batch)
                    continue
                mesh = renderer.material_renderer._mesh(batch[0].model)
                gl.glUniform1i(loc('useInstances'),True)
                if geometry is None:
                    renderer.material_renderer.draw_instances(mesh, [e.world_matrix for e in batch])
                else:
                    sources = [geometry.records.get(id(entity)) for entity in batch]
                    stamp = tuple(source.get('token', source['key']) if source is not None
                                  else np.asarray(entity.world_matrix).tobytes()
                                  for entity, source in zip(batch, sources))
                    mid = id(batch[0].model)
                    payload = self._instance_payloads.get(mid)
                    if payload is None or payload[0] != stamp:
                        matrices = [entity.world_matrix if source is None else source['matrix']
                                    for entity, source in zip(batch, sources)]
                        payload = (stamp, renderer.material_renderer.instance_payload(matrices))
                    used_payloads[mid] = payload
                    renderer.material_renderer.draw_instances(mesh, payload=payload[1],
                                                               cache_key=('shadow', id(self)))
                self.draw_calls += 1
                self.triangles += mesh[4] // 3 * len(batch)
            self._instance_payloads = used_payloads
            gl.glUniform1i(loc('useInstances'),False)
            for entity in individual:
                material = getattr(entity.model, 'material', None)
                masked = material is not None and material.get('alphaMode') == 'MASK'
                gl.glUniform1i(loc('alphaMask'),masked)
                if material is not None:
                    mr = renderer.material_renderer
                    mesh = mr._mesh(entity.model)
                    vao, count = mesh[1], mesh[4]
                    if masked:
                        tex = material.get('textures',{}).get('baseColor')
                        gl.glUniform1i(loc('hasBase'),tex is not None)
                        gl.glUniform1f(loc('baseAlpha'),material.get('pbrMetallicRoughness',{}).get('baseColorFactor',[1,1,1,1])[3])
                        gl.glUniform1f(loc('cutoff'),material.get('alphaCutoff',.5))
                        gl.glActiveTexture(gl.GL_TEXTURE0)
                        gl.glBindTexture(gl.GL_TEXTURE_2D,mr._texture(tex) if tex else 0)
                else:
                    gpu = renderer._get_gpu(entity.model)
                    vao, count = gpu.vao, gpu.count
                source = None if geometry is None else geometry.records.get(id(entity))
                model = np.asarray(entity.world_matrix,np.float32) if source is None else source['matrix']
                gl.glUniformMatrix4fv(loc('model'),1,gl.GL_TRUE,model)
                gl.glBindVertexArray(vao)
                gl.glDrawElements(gl.GL_TRIANGLES,count,gl.GL_UNSIGNED_INT,None)
                self.draw_calls += 1
                self.triangles += count // 3
            self._cache_key = key
        finally:
            gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER,draw)
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,read)
            gl.glViewport(*viewport)
            gl.glClearDepth(clear)
            gl.glDepthRange(*depth_range)
            restore_state(state)

    @staticmethod
    def bind(program, shadow, scene):
        """Caller saves/restores unit 7; an absent map always means full light."""
        loc = lambda name: gl.glGetUniformLocation(program, name)
        active = shadow is not None and shadow.matrix is not None
        gl.glUniform1i(loc('shadowEnabled'),active)
        gl.glUniform1i(loc('shadowDepth'),ShadowMap.UNIT)
        gl.glUniform1i(loc('shadowRaw'),12)
        from .atmosphere import atmosphere_state
        gl.glUniform1f(loc('sunRadius'),np.tan(np.radians(atmosphere_state(scene)['sun_size']*.5)))
        if active:
            gl.glUniformMatrix4fv(loc('shadowMatrix'),1,gl.GL_TRUE,np.asarray(shadow.matrix,np.float32))
            gl.glUniform1f(loc('shadowBias'),scene.shadow_bias)
            gl.glUniform1i(loc('shadowPCF'),scene.shadow_pcf)
            gl.glActiveTexture(gl.GL_TEXTURE0+ShadowMap.UNIT)
            gl.glBindTexture(gl.GL_TEXTURE_2D,shadow.texture)
            gl.glBindSampler(ShadowMap.UNIT,0)
            gl.glActiveTexture(gl.GL_TEXTURE12)
            gl.glBindTexture(gl.GL_TEXTURE_2D,shadow.texture)
            gl.glBindSampler(12,shadow.raw_sampler)
            rows=np.linalg.norm(shadow.matrix[:3,:3],axis=1)
            gl.glUniform3fv(loc('shadowWorldScale'),1,np.asarray([rows[0]*.5,rows[1]*.5,2/rows[2]],np.float32))

    def save_depth_png(self, path):
        """Raw orthographic depth [0,1] as grayscale, white = empty/far."""
        import pygame
        if not self.fbo:
            raise RuntimeError('Render a shadow map first')
        read = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
        names = (gl.GL_PACK_ALIGNMENT,gl.GL_PACK_ROW_LENGTH,gl.GL_PACK_SKIP_ROWS,gl.GL_PACK_SKIP_PIXELS)
        previous = [int(gl.glGetIntegerv(n)) for n in names]
        try:
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,self.fbo)
            for name, value in zip(names,(1,0,0,0)):
                gl.glPixelStorei(name,value)
            depth = np.asarray(gl.glReadPixels(0,0,self.size,self.size,gl.GL_DEPTH_COMPONENT,gl.GL_FLOAT),np.float32).reshape(self.size,self.size)
            rgb = np.repeat(np.round(np.clip(depth,0,1)*255).astype(np.uint8)[:,:,None],3,axis=2)
            pygame.image.save(pygame.image.fromstring(rgb.tobytes(),(self.size,self.size),'RGB',True),str(path))
            return depth.copy()
        finally:
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER,read)
            for name,value in zip(names,previous):
                gl.glPixelStorei(name,value)

    def close(self):
        if self.fbo:
            gl.glDeleteFramebuffers(1,[self.fbo])
        if self.texture:
            gl.glDeleteTextures([self.texture])
        if self.raw_sampler:
            gl.glDeleteSamplers(1,[self.raw_sampler])
        if self.program:
            gl.glDeleteProgram(self.program)
        self.fbo = self.texture = self.program = self.size = self.raw_sampler = 0
        self.matrix = None
        self._cache_key = None
        self._locations.clear()
        self._geometry_cache.clear()
        self._instance_payloads.clear()
