"""Cached OpenGL glTF material renderer for Mini3D editor viewports.

Lighting uses the existing GGX metallic/roughness BRDF with either one world
directional light or three studio lights and analytic studio reflections.
Optional fixed split-sum IBL uses offline-filtered resources; no transmission or animation.
Call ``close`` before destroying GL.
"""

import ctypes
import io

import numpy as np
import pygame
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
from .lighting import scene_light_direction
from .shadow_map import SHADOW_GLSL, ShadowMap
from .environment import EnvironmentMap


from .material_shaders import (VERTEX_SHADER, FRAGMENT_SHADER,
                               analytic_ground_shader,
                               SELECTION_VERTEX_SHADER, SELECTION_FRAGMENT_SHADER)
from .gl_state import save_state, restore_state


class MaterialRenderer:
    """Render entities whose mesh has a glTF ``material`` dictionary.

    Mesh buffers and decoded textures are retained until ``release``/``close``.
    Mesh geometry is immutable after upload; call ``release`` after editing it.
    Texture coordinates are glTF coordinates: image row zero maps to v=0.
    """

    _slots = (
        ("baseColor", "baseMap", "hasBase"),
        ("metallicRoughness", "mrMap", "hasMR"),
        ("normal", "normalMap", "hasNormal"),
        ("occlusion", "aoMap", "hasAO"),
        ("emissive", "emissiveMap", "hasEmissive"),
        ("specular", "specularMap", "hasSpecular"),
        ("specularColor", "specularColorMap", "hasSpecularColor"),
    )

    def __init__(self):
        self.program = compileProgram(compileShader(VERTEX_SHADER, gl.GL_VERTEX_SHADER),
                                      compileShader(FRAGMENT_SHADER, gl.GL_FRAGMENT_SHADER), validate=False)
        # Default sampler uniforms all point to unit zero after linking. Assign
        # cube/2D units before any draw; pre-assignment validation would fail.
        self._locations = {}
        self._active_program = self.program
        self._ground_program = 0
        self._meshes = {}
        self._instances = {}
        self._opaque_groups = {}
        self._normal_cache = {}
        from .draw_order import OpaqueOrder
        self._opaque_order = OpaqueOrder()
        self.gpu_instancing = True
        self._textures = {}
        self.environment = None
        from .photo_environment import PhotoEnvironment
        self.photo_environment = PhotoEnvironment()
        self._selection_program = 0
        self._selection_locations = {}

    def _loc(self, name):
        key = (self._active_program, name)
        if key not in self._locations:
            self._locations[key] = gl.glGetUniformLocation(self._active_program, name)
        return self._locations[key]

    def _bind_color_program(self, program, camera, scene, projection, view, shadow):
        self._active_program = program
        gl.glUseProgram(program)
        self._matrix('view', view)
        self._matrix('projection', projection)
        if program == self._ground_program:
            self._matrix('groundInverseViewProjection', np.linalg.inv(
                np.asarray(projection, np.float64) @ np.asarray(view, np.float64)))
        self._vec3('eye', camera.position)
        self._lighting(scene, camera)
        from .sky_renderer import bind_photo_sky
        bind_photo_sky(program, scene, self.photo_environment, lighting=True)
        ShadowMap.bind(program, shadow, scene)
        self._material_texture_state = {}

    def _float(self, name, value):
        gl.glUniform1f(self._loc(name), float(value))

    def _int(self, name, value):
        gl.glUniform1i(self._loc(name), int(value))

    def _vec3(self, name, value):
        gl.glUniform3fv(self._loc(name), 1, np.asarray(value, dtype=np.float32))

    def _matrix(self, name, matrix):
        gl.glUniformMatrix4fv(self._loc(name), 1, gl.GL_TRUE,
                              np.asarray(matrix, dtype=np.float32))

    @staticmethod
    def _entity_mesh(entity):
        mesh = getattr(entity,"mesh",None)
        return mesh if mesh is not None else getattr(entity,"model",None)

    def _mesh(self, mesh):
        key = id(mesh)
        if key in self._meshes:
            return self._meshes[key]
        vertices = np.asarray(mesh.vertices, dtype=np.float32)[:, :3]
        normals = np.asarray(mesh.vertex_normals, dtype=np.float32)
        uv = getattr(mesh, "texcoords", None)
        uv = np.zeros((len(vertices), 2), np.float32) if uv is None else np.asarray(uv, np.float32)
        colors = getattr(mesh, "vertex_colors", None)
        if colors is None:
            colors = np.ones((len(vertices), 4), np.float32)
        else:
            colors = np.asarray(colors, np.float32)
            if colors.shape[1] == 3:
                colors = np.column_stack((colors, np.ones(len(vertices), np.float32)))
        data = np.ascontiguousarray(np.column_stack((vertices, normals, uv, colors)), dtype=np.float32)
        indices = np.ascontiguousarray(mesh.indices, dtype=np.uint32)
        vao = int(gl.glGenVertexArrays(1))
        vbo, ebo = [int(value) for value in gl.glGenBuffers(2)]
        gl.glBindVertexArray(vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data, gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, ebo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, gl.GL_STATIC_DRAW)
        for location, size, offset in ((0,3,0), (1,3,12), (2,2,24), (3,4,32)):
            gl.glEnableVertexAttribArray(location)
            gl.glVertexAttribPointer(location,size,gl.GL_FLOAT,gl.GL_FALSE,48,ctypes.c_void_p(offset))
        record = (mesh, vao, vbo, ebo, int(indices.size), (vertices.min(axis=0)+vertices.max(axis=0))*0.5)
        self._meshes[key] = record
        return record

    @staticmethod
    def instance_payload(matrices, normals=None):
        """Pack immutable instance data once when a batch actually changes."""
        data = np.zeros((len(matrices), 25), np.float32)
        data[:, :16] = np.asarray(matrices, np.float32).transpose(0,2,1).reshape(-1,16)
        if normals is not None:
            data[:, 16:] = np.asarray(normals, np.float32).transpose(0,2,1).reshape(-1,9)
        data.flags.writeable = False
        return data

    def draw_instances(self, mesh, matrices=None, normals=None, payload=None, cache_key=None):
        """Borrow mesh buffers; own the instance VAO/VBO until release().

        Matrix columns occupy attributes 4..10 (GL 3.3 guarantees at least 16).
        Separate VAOs keep divisors off the selection and individual paths.
        Orphaning the stream buffer avoids waiting on a previous GPU reader.
        A supplied payload must remain immutable; retaining its object avoids
        repacking and byte comparisons on unchanged frames. Explicit batch keys
        keep separated runs of the same mesh from overwriting one another.
        """
        key = ((id(mesh[0]), normals is not None) if cache_key is None else
               (id(mesh[0]), cache_key))
        if key not in self._instances:
            vao = int(gl.glGenVertexArrays(1))
            buffer = int(gl.glGenBuffers(1))
            self._instances[key] = [vao, buffer, None]
            gl.glBindVertexArray(vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, mesh[2])
            gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, mesh[3])
            for location, size, offset in ((0,3,0), (1,3,12), (2,2,24), (3,4,32)):
                gl.glEnableVertexAttribArray(location)
                gl.glVertexAttribPointer(location,size,gl.GL_FLOAT,False,48,ctypes.c_void_p(offset))
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, buffer)
            for location, size, offset in ([(4+i,4,16*i) for i in range(4)] +
                                           [(8+i,3,64+12*i) for i in range(3)]):
                gl.glEnableVertexAttribArray(location)
                gl.glVertexAttribPointer(location,size,gl.GL_FLOAT,False,100,ctypes.c_void_p(offset))
                gl.glVertexAttribDivisor(location,1)
        resource = self._instances[key]
        vao, buffer = resource[:2]
        data = self.instance_payload(matrices, normals) if payload is None else payload
        gl.glBindVertexArray(vao)
        stamp = data.tobytes() if payload is None else data
        unchanged = (stamp is resource[2] if payload is not None else
                     isinstance(resource[2], bytes) and stamp == resource[2])
        if not unchanged:
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER,buffer)
            gl.glBufferData(gl.GL_ARRAY_BUFFER,data.nbytes,data,gl.GL_STREAM_DRAW)
            resource[2] = stamp
        gl.glDrawElementsInstanced(gl.GL_TRIANGLES,mesh[4],gl.GL_UNSIGNED_INT,None,len(data))

    def _prune_color_instances(self, active, state=None):
        """Keep only this pass's batch buffers, never evict shadow resources."""
        for key in list(self._instances):
            tag = key[1]
            if isinstance(tag, tuple) and tag and tag[0] == 'color_batch' and key not in active:
                vao, buffer, _ = self._instances[key]
                # A caller may have left one of our public helper buffers bound;
                # preserve the saved bindings and retire it on a later pass.
                if state is not None and (vao == state['VERTEX_ARRAY_BINDING'] or
                                          buffer == state['ARRAY_BUFFER_BINDING']):
                    continue
                self._instances.pop(key)
                gl.glDeleteVertexArrays(1, [vao])
                gl.glDeleteBuffers(1, [buffer])

    def _persistent_batches(self, plan, view):
        """Retain opaque work per material; the moving photo floor is separate.

        Scene synchronization validates source changes before this call. Only
        visible membership and immutable record tokens are inspected here.
        Transparent depth ordering remains camera-dependent and is rebuilt.
        """
        from .geometry_cache import normal_transform
        ranks = self._opaque_order.ranks_for(plan.shadow_candidates, plan.geometry)
        groups = {}
        for item in plan.opaque:
            if item.material is not None:
                groups.setdefault(id(item.material), []).append(item)
        retained, result = {}, []
        ordered_groups = sorted(groups.items(), key=lambda pair: ranks[id(pair[1][0].entity)])
        for material_id, items in ordered_groups:
            key = tuple((id(item.entity), item.prepared.get('token', id(item.prepared)),
                         ranks[id(item.entity)]) for item in items)
            cached_group = self._opaque_groups.get(material_id)
            if cached_group is not None and cached_group[0] == key:
                batches = cached_group[1]
            else:
                batches = []
                for item in sorted(items, key=lambda value: ranks[id(value.entity)]):
                    mesh = self._mesh(item.model)
                    matrix = item.world_matrix
                    cached = item.prepared
                    normal, mirrored = ((cached['normal'], cached['mirrored']) if cached['normal'] is not None else
                                        normal_transform(matrix, self._normal_cache))
                    row = (False, 0., item, matrix, mesh)
                    compatible = item.material.get('alphaMode', 'OPAQUE') == 'OPAQUE'
                    batch_key = (id(item.model), mirrored) if compatible else None
                    if batch_key is not None and batches and batches[-1][0] == batch_key:
                        batches[-1][1].append((row, normal, mirrored))
                    else:
                        batches.append([batch_key, [(row, normal, mirrored)], None, None])
                for batch_number, batch in enumerate(batches):
                    if len(batch[1]) > 1:
                        batch[2] = self.instance_payload([entry[0][3] for entry in batch[1]],
                                                         [entry[1] for entry in batch[1]])
                        batch[3] = ('color_batch', material_id, batch_number, batch[0][1])
            retained[material_id] = (key, batches)
            result.extend(batches)
        self._opaque_groups = retained
        transparent = []
        for item in plan.transparent:
            mesh = self._mesh(item.model)
            matrix = item.world_matrix
            depth = float((view @ (matrix @ np.append(mesh[5],1)))[2])
            cached = item.prepared
            normal, mirrored = ((cached['normal'], cached['mirrored']) if cached['normal'] is not None else
                                normal_transform(matrix, self._normal_cache))
            row = (True, depth, item, matrix, mesh)
            transparent.append((depth, [None, [(row, normal, mirrored)], None, None]))
        transparent.sort(key=lambda entry: entry[0])
        result.extend(entry[1] for entry in transparent)
        return result

    def _texture(self, texture):
        encoded = texture["image"]
        sampler = texture.get("sampler", {})
        settings = tuple(int(sampler.get(name, default)) for name, default in (
            ("magFilter", gl.GL_LINEAR), ("minFilter", gl.GL_LINEAR_MIPMAP_LINEAR),
            ("wrapS", gl.GL_REPEAT), ("wrapT", gl.GL_REPEAT)))
        key = (id(encoded), settings)
        if key in self._textures:
            return self._textures[key][1]
        decoded = texture.get('_decoded_image') if texture.get('_decoded_source') is encoded else None
        if decoded is None:
            surface = pygame.image.load(io.BytesIO(encoded))
            width, height = surface.get_size()
            pixels = pygame.image.tostring(surface, "RGBA", False)
        else:
            width, height, pixels = decoded
        handle = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D,handle)
        pixel_parameters = (gl.GL_UNPACK_ALIGNMENT,gl.GL_UNPACK_ROW_LENGTH,
                            gl.GL_UNPACK_SKIP_ROWS,gl.GL_UNPACK_SKIP_PIXELS)
        previous = [int(gl.glGetIntegerv(parameter)) for parameter in pixel_parameters]
        try:
            for parameter, value in zip(pixel_parameters,(1,0,0,0)):
                gl.glPixelStorei(parameter,value)
            gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGBA8,width,height,
                            0,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE,pixels)
        finally:
            for parameter, value in zip(pixel_parameters,previous):
                gl.glPixelStorei(parameter,value)
        for pname, value in zip((gl.GL_TEXTURE_MAG_FILTER,gl.GL_TEXTURE_MIN_FILTER,
                                gl.GL_TEXTURE_WRAP_S,gl.GL_TEXTURE_WRAP_T), settings):
            gl.glTexParameteri(gl.GL_TEXTURE_2D,pname,value)
        gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        self._textures[key] = (encoded,handle)
        return handle

    def _material(self, material, mode):
        self._int("photographicGround", material.get("extras", {}).get("photographicGround", False))
        pbr = material.get("pbrMetallicRoughness", {})
        extensions = material.get("extensions", {})
        specular = extensions.get("KHR_materials_specular", {})
        gl.glUniform4fv(self._loc("baseFactor"),1,np.asarray(pbr.get("baseColorFactor",[1,1,1,1]),np.float32))
        self._float("metallicFactor",pbr.get("metallicFactor",1))
        self._float("roughnessFactor",pbr.get("roughnessFactor",1))
        self._float("normalScale",material.get("normalTexture",{}).get("scale",1))
        self._float("aoStrength",material.get("occlusionTexture",{}).get("strength",1))
        strength = extensions.get("KHR_materials_emissive_strength",{}).get("emissiveStrength",1)
        self._vec3("emissiveFactor",np.asarray(material.get("emissiveFactor",[0,0,0]))*strength)
        self._vec3("specularColorFactor",specular.get("specularColorFactor",[1,1,1]))
        self._float("specularFactor",specular.get("specularFactor",1))
        self._float("alphaCutoff",material.get("alphaCutoff",0.5))
        self._int("alphaMode",{"OPAQUE":0,"MASK":1,"BLEND":2}.get(material.get("alphaMode","OPAQUE"),0))
        shading = {"unlit":1,"wireframe":2}.get(mode.lower(),0)
        if shading == 0 and "KHR_materials_unlit" in extensions:
            shading = 1
        self._int("shadingMode",shading)
        textures = material.get("textures", {})
        for unit, (slot, sampler, present) in enumerate(self._slots):
            texture = textures.get(slot)
            # Bind lazily on the correct unit: _texture may upload a new image.
            key = None if texture is None else (id(texture['image']), tuple(sorted(texture.get('sampler', {}).items())))
            cache = getattr(self, '_material_texture_state', None)
            if cache is None or unit not in cache or cache[unit] != key:
                self._int(present,texture is not None)
                self._int(sampler,unit)
                gl.glActiveTexture(gl.GL_TEXTURE0+unit)
                gl.glBindTexture(gl.GL_TEXTURE_2D,self._texture(texture) if texture is not None else 0)
                if cache is not None:
                    cache[unit] = key

    def _lighting(self, scene, camera):
        from .atmosphere import atmosphere_state, sun_color, direct_light_strength, PROCEDURAL_SKIES
        atmosphere = atmosphere_state(scene)
        self._int('atmosphereEnabled', atmosphere['enabled'])
        self._vec3('sunColor', sun_color(atmosphere['sun_temperature']))
        self._vec3('sunDirection', scene_light_direction(scene))
        self._float('exposureEV', atmosphere['exposure_ev'])
        self._float('hazeDensity', atmosphere['haze'])
        self._float('groundScale', atmosphere['ground_scale'])
        self._float('photoFar', getattr(camera, 'far', 1000.))
        photo_hdr=atmosphere['enabled'] and atmosphere['sky_texture'] not in PROCEDURAL_SKIES
        enabled = getattr(scene, 'environment_enabled', False) or photo_hdr
        self._int('environmentEnabled', enabled)
        self._float('environmentIntensity', atmosphere['sky_intensity'] if photo_hdr else getattr(scene, 'environment_intensity', .35))
        # Assign distinct sampler types even when disabled: GL validates all samplers.
        self._int('diffuseEnv', 8)
        self._int('specularEnv', 9)
        self._int('brdfLut', 10)
        # The procedural sky also uses the bundled GGX BRDF integration LUT.
        # Binding it does not enable the neutral studio's lighting contribution.
        if not photo_hdr and (enabled or atmosphere['enabled']):
            if self.environment is None:
                self.environment = EnvironmentMap()
            self.environment.bind()
        mode = getattr(scene, 'lighting_mode', 'Studio')
        if mode not in ('Scene', 'Studio'):
            raise ValueError('Unknown lighting mode: ' + str(mode))
        self._int('sceneLighting', mode == 'Scene')
        if mode == 'Scene':
            self._vec3('light0', scene_light_direction(scene))
            self._float('lightIntensity', direct_light_strength(scene))
            self._float('ambientIntensity', scene.ambient)
        else:
            right, up, back = camera.rotation[:,0],camera.rotation[:,1],camera.rotation[:,2]
            for name, direction in (("light0",back+up*1.1-right*0.8),
                                    ("light1",back*0.3+right+up*0.2),
                                    ("light2",-back+up+right*0.2)):
                self._vec3(name,direction/np.linalg.norm(direction))
            self._float("lightIntensity",getattr(scene,"material_light_intensity",1.0))
            self._float("ambientIntensity",getattr(scene,"material_ambient_intensity",1.0))

    def _transient_batches(self, entities, view, plan, mode):
        """Compatibility path for callers without synchronized scene records."""
        records = []
        prepared = ([(False, item) for item in plan.opaque if item.material is not None] +
                    [(True, item) for item in plan.transparent]) if plan is not None else [
                        (self._entity_mesh(entity).material.get("alphaMode", "OPAQUE") == "BLEND", entity)
                        for entity in entities]
        for transparent, entity in prepared:
            mesh = self._mesh(self._entity_mesh(entity))
            matrix = np.asarray(entity.world_matrix,np.float32)
            # Only transparent records need camera-depth sorting.
            depth = float((view @ (matrix @ np.append(mesh[5],1)))[2]) if transparent else 0.
            records.append((transparent,depth,entity,matrix,mesh))
        # Camera looks along -Z: more negative depth is farther away.
        # Memory addresses change on reload and can change which coplanar
        # facade wins the depth test. Group materials by stable scene order.
        order = {}
        for entity in (plan.shadow_candidates if plan is not None else entities):
            model = self._entity_mesh(entity)
            if model is not None and getattr(model, 'material', None) is not None:
                order.setdefault(id(model.material), len(order))
        if self.gpu_instancing and mode.lower() != 'wireframe':
            ranks = self._opaque_order.ranks_for(plan.shadow_candidates if plan is not None else entities,
                                                getattr(plan,'geometry',None))
            records.sort(key=lambda row: (row[0], row[1] if row[0] else
                ranks[id(getattr(row[2], 'entity', row[2]))]))
        else:
            records.sort(key=lambda row:(row[0],row[1] if row[0] else order[id(row[4][0].material)]))
        from .geometry_cache import normal_transform
        batches = []
        for row in records:
            transparent, _, entity, matrix, mesh = row
            cached = getattr(entity, 'prepared', None)
            normal, mirrored = ((cached['normal'], cached['mirrored']) if cached is not None and cached['normal'] is not None else
                                normal_transform(matrix, self._normal_cache))
            # Preserve stable draw order, including coplanar ties. Never
            # regroup across another mesh, winding or special alpha path.
            compatible = (self.gpu_instancing and not transparent and
                          mesh[0].material.get('alphaMode', 'OPAQUE') == 'OPAQUE')
            key = (id(mesh[0]), mirrored) if compatible else None
            if key is not None and batches and batches[-1][0] == key:
                batches[-1][1].append((row, normal, mirrored))
            else:
                batches.append((key, [(row, normal, mirrored)]))
        return [[key, rows, None, None] for key, rows in batches]

    def render(self, entities, camera, scene, width, height, mode="Lit", shadow=None, plan=None):
        """Draw into the caller's FBO; optionally consume this frame's RenderPlan.

        The standalone entity entry remains supported. Plan partitions already
        classify alpha; transparent depth ordering still belongs to this pass.
        """
        self.draw_calls = self.triangles = 0
        entities = [entity for entity in entities if self._entity_mesh(entity) is not None]
        if not entities or width <= 0 or height <= 0:
            return
        if not self.program:
            raise RuntimeError("MaterialRenderer has been closed")
        state = self._save_state()
        try:
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthFunc(gl.GL_LESS)
            gl.glDisable(gl.GL_FRAMEBUFFER_SRGB)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK,gl.GL_LINE if mode.lower()=="wireframe" else gl.GL_FILL)
            view = camera.view_matrix
            draw_view = plan.view if plan is not None else view
            projection = (plan.projection if plan is not None else
                          camera.projection_matrix(float(width)/height))
            self._bind_color_program(self.program, camera, scene, projection, draw_view, shadow)
            persistent = (plan is not None and getattr(plan, 'geometry', None) is not None
                          and self.gpu_instancing and mode.lower() != 'wireframe')
            batches = (self._persistent_batches(plan, view) if persistent else
                       self._transient_batches(entities, view, plan, mode))
            # Other passes may have changed bindings, so GL state is cached only
            # within this pass. CPU batches and owned instance buffers persist.
            self._material_texture_state = {}
            last_material = None
            active_instances = set()
            last_transparent = last_cull = last_mirrored = last_instanced = None
            for _, batch, payload, instance_key in batches:
                (transparent, _, entity, matrix, mesh), normal_matrix, mirrored = batch[0]
                material = mesh[0].material
                ground = material.get('extras', {}).get('photographicGround', False)
                if ground and not self._ground_program:
                    self._ground_program = compileProgram(
                        compileShader(analytic_ground_shader(VERTEX_SHADER), gl.GL_VERTEX_SHADER),
                        compileShader(analytic_ground_shader(FRAGMENT_SHADER), gl.GL_FRAGMENT_SHADER),
                        validate=False)
                program = self._ground_program if ground else self.program
                if program != self._active_program:
                    self._bind_color_program(program, camera, scene, projection, draw_view, shadow)
                    last_material = None
                    last_instanced = None
                if transparent != last_transparent:
                    if transparent:
                        gl.glEnable(gl.GL_BLEND)
                        gl.glBlendEquation(gl.GL_FUNC_ADD)
                        gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA,gl.GL_ONE_MINUS_SRC_ALPHA,
                                               gl.GL_ONE,gl.GL_ONE_MINUS_SRC_ALPHA)
                    else:
                        gl.glDisable(gl.GL_BLEND)
                    gl.glDepthMask(not transparent)
                    last_transparent = transparent
                cull = not material.get("doubleSided",False)
                if cull != last_cull:
                    if cull:
                        gl.glEnable(gl.GL_CULL_FACE)
                        gl.glCullFace(gl.GL_BACK)
                    else:
                        gl.glDisable(gl.GL_CULL_FACE)
                    last_cull = cull
                if mirrored != last_mirrored:
                    gl.glFrontFace(gl.GL_CW if mirrored else gl.GL_CCW)
                    last_mirrored = mirrored
                if material is not last_material:
                    self._material(material,mode)
                    last_material = material
                instanced = len(batch) > 1
                if instanced != last_instanced:
                    self._int('useInstances', instanced)
                    last_instanced = instanced
                if instanced:
                    if payload is not None:
                        self.draw_instances(mesh, payload=payload, cache_key=instance_key)
                        active_instances.add((id(mesh[0]), instance_key))
                    else:
                        self.draw_instances(mesh, [row[0][3] for row in batch], [row[1] for row in batch])
                else:
                    self._matrix("model",matrix)
                    gl.glUniformMatrix3fv(self._loc("normalMatrix"),1,gl.GL_TRUE,normal_matrix)
                    gl.glBindVertexArray(mesh[1])
                    gl.glDrawElements(gl.GL_TRIANGLES,mesh[4],gl.GL_UNSIGNED_INT,None)
                self.draw_calls += 1
                self.triangles += mesh[4] // 3 * len(batch)
            self._prune_color_instances(active_instances, state)
        finally:
            self._active_program = self.program
            self._material_texture_state = None
            self._restore_state(state)

    def render_selection(self, entities, camera, width, height):
        """Draw an orange 3-pixel selection shell using the FBO stencil buffer.

        The caller supplies a depth/stencil attachment; its stencil contents are
        scratch space and are cleared here. Color/depth are preserved. Selected
        geometry shares one mask, so overlapping parts produce an outer contour.
        Depth testing is disabled for an intentional selection x-ray effect.
        """
        entities = [entity for entity in entities if self._entity_mesh(entity) is not None]
        if not entities or width <= 0 or height <= 0:
            return
        if not self.program:
            raise RuntimeError("MaterialRenderer has been closed")
        state = self._save_state()
        try:
            if not self._selection_program:
                self._selection_program = compileProgram(
                    compileShader(SELECTION_VERTEX_SHADER,gl.GL_VERTEX_SHADER),
                    compileShader(SELECTION_FRAGMENT_SHADER,gl.GL_FRAGMENT_SHADER))
                self._selection_locations = {name:gl.glGetUniformLocation(self._selection_program,name)
                    for name in ("model","view","projection","normalMatrix","viewportSize","outlinePixels")}
            loc = self._selection_locations
            gl.glUseProgram(self._selection_program)
            gl.glUniformMatrix4fv(loc["view"],1,gl.GL_TRUE,np.asarray(camera.view_matrix,np.float32))
            gl.glUniformMatrix4fv(loc["projection"],1,gl.GL_TRUE,
                                  np.asarray(camera.projection_matrix(float(width)/height),np.float32))
            gl.glUniform2f(loc["viewportSize"],float(width),float(height))
            gl.glDisable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_CULL_FACE)
            gl.glDisable(gl.GL_BLEND)
            gl.glDisable(gl.GL_FRAMEBUFFER_SRGB)
            gl.glDisable(gl.GL_SCISSOR_TEST)
            gl.glDepthMask(False)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK,gl.GL_FILL)
            gl.glEnable(gl.GL_STENCIL_TEST)
            gl.glStencilMask(0xff)
            gl.glClearStencil(0)
            gl.glClear(gl.GL_STENCIL_BUFFER_BIT)
            records = []
            for entity in entities:
                matrix = np.asarray(entity.world_matrix,np.float32)
                normal_matrix = np.asarray(np.linalg.pinv(matrix[:3,:3]).T,np.float32)
                records.append((self._mesh(self._entity_mesh(entity)),matrix,normal_matrix))
            # Original silhouettes form the union mask, without touching color.
            gl.glColorMask(False,False,False,False)
            gl.glStencilFunc(gl.GL_ALWAYS,1,0xff)
            gl.glStencilOp(gl.GL_KEEP,gl.GL_KEEP,gl.GL_REPLACE)
            for pixels in (0.0,3.0):
                if pixels:
                    gl.glColorMask(True,True,True,True)
                    gl.glStencilMask(0)
                    gl.glStencilFunc(gl.GL_NOTEQUAL,1,0xff)
                    gl.glStencilOp(gl.GL_KEEP,gl.GL_KEEP,gl.GL_KEEP)
                gl.glUniform1f(loc["outlinePixels"],pixels)
                for mesh, matrix, normal_matrix in records:
                    gl.glUniformMatrix4fv(loc["model"],1,gl.GL_TRUE,matrix)
                    gl.glUniformMatrix3fv(loc["normalMatrix"],1,gl.GL_TRUE,normal_matrix)
                    gl.glBindVertexArray(mesh[1])
                    gl.glDrawElements(gl.GL_TRIANGLES,mesh[4],gl.GL_UNSIGNED_INT,None)
        finally:
            self._restore_state(state)

    # Compatibility aliases for callers of the original renderer helpers.
    _save_state = staticmethod(save_state)
    _restore_state = staticmethod(restore_state)

    def release(self):
        """Release cached geometry/images with the owning GL context current."""
        for vao, buffer, _ in self._instances.values():
            gl.glDeleteVertexArrays(1,[vao])
            gl.glDeleteBuffers(1,[buffer])
        self._instances.clear()
        self._opaque_groups.clear()
        self._normal_cache.clear()
        self._opaque_order.key = None
        self._opaque_order.ranks.clear()
        self._opaque_order.groups.clear()
        for _, vao, vbo, ebo, _, _ in self._meshes.values():
            gl.glDeleteVertexArrays(1,[vao])
            gl.glDeleteBuffers(2,[vbo,ebo])
        for _, texture in self._textures.values():
            gl.glDeleteTextures([texture])
        self._meshes.clear()
        self._textures.clear()
        self.photo_environment.close()
        if self.environment is not None:
            self.environment.close()
            self.environment = None

    def close(self):
        """Release all GPU resources; safe to call more than once."""
        self.release()
        if self.program:
            gl.glDeleteProgram(self.program)
            self.program = 0
        if self._ground_program:
            gl.glDeleteProgram(self._ground_program)
            self._ground_program = 0
        if self._selection_program:
            gl.glDeleteProgram(self._selection_program)
            self._selection_program = 0
            self._selection_locations.clear()
