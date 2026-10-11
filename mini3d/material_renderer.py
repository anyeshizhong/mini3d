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
        self._meshes = {}
        self._textures = {}
        self.environment = None
        self._selection_program = 0
        self._selection_locations = {}

    def _loc(self, name):
        if name not in self._locations:
            self._locations[name] = gl.glGetUniformLocation(self.program, name)
        return self._locations[name]

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

    def _texture(self, texture):
        encoded = texture["image"]
        sampler = texture.get("sampler", {})
        settings = tuple(int(sampler.get(name, default)) for name, default in (
            ("magFilter", gl.GL_LINEAR), ("minFilter", gl.GL_LINEAR_MIPMAP_LINEAR),
            ("wrapS", gl.GL_REPEAT), ("wrapT", gl.GL_REPEAT)))
        key = (id(encoded), settings)
        if key in self._textures:
            return self._textures[key][1]
        surface = pygame.image.load(io.BytesIO(encoded))
        pixels = pygame.image.tostring(surface, "RGBA", False)
        handle = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D,handle)
        pixel_parameters = (gl.GL_UNPACK_ALIGNMENT,gl.GL_UNPACK_ROW_LENGTH,
                            gl.GL_UNPACK_SKIP_ROWS,gl.GL_UNPACK_SKIP_PIXELS)
        previous = [int(gl.glGetIntegerv(parameter)) for parameter in pixel_parameters]
        try:
            for parameter, value in zip(pixel_parameters,(1,0,0,0)):
                gl.glPixelStorei(parameter,value)
            gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGBA8,surface.get_width(),surface.get_height(),
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
            self._int(present,texture is not None)
            self._int(sampler,unit)
            gl.glActiveTexture(gl.GL_TEXTURE0+unit)
            gl.glBindTexture(gl.GL_TEXTURE_2D,self._texture(texture) if texture is not None else 0)

    def _lighting(self, scene, camera):
        from .atmosphere import atmosphere_state, sun_color
        atmosphere = atmosphere_state(scene)
        self._int('atmosphereEnabled', atmosphere['enabled'])
        self._vec3('sunColor', sun_color(atmosphere['sun_temperature']))
        self._vec3('sunDirection', scene_light_direction(scene))
        self._float('exposureEV', atmosphere['exposure_ev'])
        self._float('hazeDensity', atmosphere['haze'])
        self._float('groundScale', atmosphere['ground_scale'])
        self._float('photoFar', getattr(camera, 'far', 1000.))
        enabled = getattr(scene, 'environment_enabled', False)
        self._int('environmentEnabled', enabled)
        self._float('environmentIntensity', getattr(scene, 'environment_intensity', .35))
        # Assign distinct sampler types even when disabled: GL validates all samplers.
        self._int('diffuseEnv', 8)
        self._int('specularEnv', 9)
        self._int('brdfLut', 10)
        if enabled:
            if self.environment is None:
                self.environment = EnvironmentMap()
            self.environment.bind()
        mode = getattr(scene, 'lighting_mode', 'Studio')
        if mode not in ('Scene', 'Studio'):
            raise ValueError('Unknown lighting mode: ' + str(mode))
        self._int('sceneLighting', mode == 'Scene')
        if mode == 'Scene':
            self._vec3('light0', scene_light_direction(scene))
            self._float('lightIntensity', scene.diffuse)
            self._float('ambientIntensity', scene.ambient)
        else:
            right, up, back = camera.rotation[:,0],camera.rotation[:,1],camera.rotation[:,2]
            for name, direction in (("light0",back+up*1.1-right*0.8),
                                    ("light1",back*0.3+right+up*0.2),
                                    ("light2",-back+up+right*0.2)):
                self._vec3(name,direction/np.linalg.norm(direction))
            self._float("lightIntensity",getattr(scene,"material_light_intensity",1.0))
            self._float("ambientIntensity",getattr(scene,"material_ambient_intensity",1.0))

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
            gl.glUseProgram(self.program)
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDepthFunc(gl.GL_LESS)
            gl.glDisable(gl.GL_FRAMEBUFFER_SRGB)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK,gl.GL_LINE if mode.lower()=="wireframe" else gl.GL_FILL)
            view = camera.view_matrix
            self._matrix("view", plan.view if plan is not None else view)
            self._matrix("projection", plan.projection if plan is not None else
                         camera.projection_matrix(float(width)/height))
            self._vec3("eye",camera.position)
            self._lighting(scene, camera)
            ShadowMap.bind(self.program, shadow, scene)
            records = []
            prepared = ([(False, item) for item in plan.opaque if item.material is not None] +
                        [(True, item) for item in plan.transparent]) if plan is not None else [
                            (self._entity_mesh(entity).material.get("alphaMode", "OPAQUE") == "BLEND", entity)
                            for entity in entities]
            for transparent, entity in prepared:
                mesh = self._mesh(self._entity_mesh(entity))
                matrix = np.asarray(entity.world_matrix,np.float32)
                center = matrix @ np.append(mesh[5],1)
                depth = float((view @ center)[2])
                records.append((transparent,depth,entity,matrix,mesh))
            # Camera looks along -Z: more negative depth is farther away.
            records.sort(key=lambda row:(row[0],row[1] if row[0] else id(row[4][0].material)))
            last_material = None
            normal_matrices = {}
            for transparent, _, entity, matrix, mesh in records:
                material = mesh[0].material
                if transparent:
                    gl.glEnable(gl.GL_BLEND)
                    gl.glBlendEquation(gl.GL_FUNC_ADD)
                    gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA,gl.GL_ONE_MINUS_SRC_ALPHA,
                                           gl.GL_ONE,gl.GL_ONE_MINUS_SRC_ALPHA)
                else:
                    gl.glDisable(gl.GL_BLEND)
                gl.glDepthMask(not transparent)
                if material.get("doubleSided",False):
                    gl.glDisable(gl.GL_CULL_FACE)
                else:
                    gl.glEnable(gl.GL_CULL_FACE)
                    gl.glCullFace(gl.GL_BACK)
                gl.glFrontFace(gl.GL_CW if np.linalg.det(matrix[:3,:3])<0 else gl.GL_CCW)
                self._matrix("model",matrix)
                # Pseudoinverse handles intentionally flattened editor objects.
                linear_key = matrix[:3,:3].tobytes()
                normal_matrix = normal_matrices.get(linear_key)
                if normal_matrix is None:
                    normal_matrix = np.linalg.pinv(matrix[:3,:3]).T
                    normal_matrices[linear_key] = normal_matrix
                gl.glUniformMatrix3fv(self._loc("normalMatrix"),1,gl.GL_TRUE,np.asarray(normal_matrix,np.float32))
                if material is not last_material:
                    self._material(material,mode)
                    last_material = material
                gl.glBindVertexArray(mesh[1])
                gl.glDrawElements(gl.GL_TRIANGLES,mesh[4],gl.GL_UNSIGNED_INT,None)
                self.draw_calls += 1
                self.triangles += mesh[4] // 3
        finally:
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
        for _, vao, vbo, ebo, _, _ in self._meshes.values():
            gl.glDeleteVertexArrays(1,[vao])
            gl.glDeleteBuffers(2,[vbo,ebo])
        for _, texture in self._textures.values():
            gl.glDeleteTextures([texture])
        self._meshes.clear()
        self._textures.clear()
        if self.environment is not None:
            self.environment.close()
            self.environment = None

    def close(self):
        """Release all GPU resources; safe to call more than once."""
        self.release()
        if self.program:
            gl.glDeleteProgram(self.program)
            self.program = 0
        if self._selection_program:
            gl.glDeleteProgram(self._selection_program)
            self._selection_program = 0
            self._selection_locations.clear()
