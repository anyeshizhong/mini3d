"""Cached OpenGL glTF material renderer for Mini3D editor viewports.

Lighting uses a GGX metallic/roughness BRDF, three studio lights and a simple
analytic studio reflection approximation. It does not implement environment-map
IBL, shadows, transmission or animation. Call ``close`` before destroying GL.
"""

import ctypes
import io

import numpy as np
import pygame
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader


VERTEX_SHADER = """#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in vec3 normal;
layout(location=2) in vec2 texcoord;
layout(location=3) in vec4 color;
uniform mat4 model, view, projection;
uniform mat3 normalMatrix;
out vec3 worldPosition;
out vec3 worldNormal;
out vec2 uv;
out vec4 vertexColor;
void main() {
    vec4 p = model * vec4(position, 1.0);
    worldPosition = p.xyz;
    worldNormal = normalMatrix * normal;
    uv = texcoord;
    vertexColor = color;
    gl_Position = projection * view * p;
}
"""

FRAGMENT_SHADER = """#version 330 core
in vec3 worldPosition;
in vec3 worldNormal;
in vec2 uv;
in vec4 vertexColor;
out vec4 fragColor;
uniform sampler2D baseMap, mrMap, normalMap, aoMap, emissiveMap;
uniform sampler2D specularMap, specularColorMap;
uniform bool hasBase, hasMR, hasNormal, hasAO, hasEmissive;
uniform bool hasSpecular, hasSpecularColor;
uniform vec4 baseFactor;
uniform vec3 emissiveFactor, specularColorFactor;
uniform float metallicFactor, roughnessFactor, normalScale, aoStrength;
uniform float specularFactor, alphaCutoff;
uniform int alphaMode, shadingMode;
uniform vec3 eye, light0, light1, light2;
uniform float lightIntensity, ambientIntensity;
const float PI = 3.14159265359;

vec3 linearize(vec3 c) {
    return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)),
               step(vec3(0.04045), c));
}
vec3 srgb(vec3 c) {
    c = max(c, vec3(0.0));
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055,
               step(vec3(0.0031308), c));
}
vec3 fresnel(float cosine, vec3 f0) {
    return f0 + (1.0 - f0) * pow(1.0 - cosine, 5.0);
}
vec3 directLight(vec3 n, vec3 v, vec3 l, vec3 base, vec3 f0,
                 float metal, float rough, vec3 radiance) {
    vec3 h = normalize(v + l);
    float nl = max(dot(n, l), 0.0);
    float nv = max(dot(n, v), 0.001);
    float nh = max(dot(n, h), 0.0);
    float vh = max(dot(v, h), 0.0);
    float a = rough * rough;
    float a2 = a * a;
    float d = a2 / max(PI * pow(nh * nh * (a2 - 1.0) + 1.0, 2.0), 0.000001);
    float k = (rough + 1.0) * (rough + 1.0) / 8.0;
    float g = nv / (nv * (1.0-k)+k) * nl / (nl * (1.0-k)+k);
    vec3 f = fresnel(vh, f0);
    vec3 spec = d * g * f / max(4.0 * nv * nl, 0.0001);
    vec3 diffuse = (1.0-f) * (1.0-metal) * base / PI;
    return (diffuse + spec) * radiance * nl;
}
vec3 mappedNormal() {
    vec3 n = normalize(worldNormal);
    if (!gl_FrontFacing) n = -n;
    if (!hasNormal) return n;
    vec3 dp1 = dFdx(worldPosition), dp2 = dFdy(worldPosition);
    vec2 dt1 = dFdx(uv), dt2 = dFdy(uv);
    float determinant = dt1.x * dt2.y - dt1.y * dt2.x;
    if (abs(determinant) < 1e-10) return n;
    vec3 t = (dp1 * dt2.y - dp2 * dt1.y) / determinant;
    vec3 b = (dp2 * dt1.x - dp1 * dt2.x) / determinant;
    t -= n * dot(n, t);
    if (dot(t,t) < 1e-12) return n;
    t = normalize(t);
    b = normalize(cross(n,t)) * (dot(cross(n,t),b) < 0.0 ? -1.0 : 1.0);
    vec3 mapNormal = texture(normalMap, uv).xyz * 2.0 - 1.0;
    mapNormal.xy *= normalScale;
    return normalize(mat3(t,b,n) * mapNormal);
}
void main() {
    vec4 base = baseFactor * vertexColor;
    if (hasBase) {
        vec4 sampled = texture(baseMap, uv);
        base *= vec4(linearize(sampled.rgb), sampled.a);
    }
    if (alphaMode == 1 && base.a < alphaCutoff) discard;
    float alpha = alphaMode == 2 ? base.a : 1.0;
    if (shadingMode == 1) { fragColor = vec4(srgb(base.rgb), alpha); return; }
    if (shadingMode == 2) { fragColor = vec4(0.72,0.83,0.94,alpha); return; }
    float metal = metallicFactor;
    float rough = roughnessFactor;
    if (hasMR) {
        vec4 mr = texture(mrMap,uv);
        metal *= mr.b; rough *= mr.g;
    }
    metal = clamp(metal, 0.0, 1.0);
    rough = clamp(rough, 0.045, 1.0);
    float specWeight = specularFactor;
    vec3 specColor = specularColorFactor;
    if (hasSpecular) specWeight *= texture(specularMap,uv).a;
    if (hasSpecularColor) specColor *= linearize(texture(specularColorMap,uv).rgb);
    vec3 f0 = mix(min(vec3(1.0), 0.04 * specColor) * specWeight, base.rgb, metal);
    vec3 n = mappedNormal();
    vec3 v = normalize(eye-worldPosition);
    vec3 result = directLight(n,v,light0,base.rgb,f0,metal,rough,vec3(3.1,2.9,2.65));
    result += directLight(n,v,light1,base.rgb,f0,metal,rough,vec3(1.3,1.5,1.9));
    result += directLight(n,v,light2,base.rgb,f0,metal,rough,vec3(1.3));
    result *= lightIntensity;
    // Broad virtual studio panels keep metals legible without an HDR asset.
    vec3 reflection = reflect(-v,n);
    float panel = pow(max(dot(reflection,light0),0.0),mix(80.0,2.0,rough));
    panel += 0.65 * pow(max(dot(reflection,light1),0.0),mix(45.0,2.0,rough));
    vec3 reflected = fresnel(max(dot(n,v),0.0),f0) * (0.27 + panel * 0.9);
    float ao = hasAO ? mix(1.0,texture(aoMap,uv).r,aoStrength) : 1.0;
    result += ((1.0-metal)*base.rgb*0.32 + reflected) * ao * ambientIntensity;
    vec3 emission = emissiveFactor;
    if (hasEmissive) emission *= linearize(texture(emissiveMap,uv).rgb);
    result += emission;
    // Gentle highlight compression, with an sRGB output for the viewport FBO.
    result = result / (1.0 + result);
    fragColor = vec4(srgb(result), alpha);
}
"""


SELECTION_VERTEX_SHADER = """#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in vec3 normal;
uniform mat4 model, view, projection;
uniform mat3 normalMatrix;
uniform vec2 viewportSize;
uniform float outlinePixels;
void main() {
    vec4 clip = projection * view * model * vec4(position,1.0);
    vec3 normalWorld = normalMatrix * normal;
    vec4 normalClip = projection * view * vec4(normalWorld,0.0);
    // Derivative of clip.xy / clip.w, expressed in physical viewport pixels.
    vec2 direction = (normalClip.xy * clip.w - clip.xy * normalClip.w) * viewportSize;
    float lengthSquared = dot(direction,direction);
    if (outlinePixels > 0.0 && clip.w > 0.0 && lengthSquared > 1e-16)
        clip.xy += normalize(direction) * (2.0 * outlinePixels / viewportSize) * clip.w;
    gl_Position = clip;
}
"""

SELECTION_FRAGMENT_SHADER = """#version 330 core
out vec4 fragColor;
void main() { fragColor = vec4(1.0,0.48,0.055,1.0); }
"""


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
                                      compileShader(FRAGMENT_SHADER, gl.GL_FRAGMENT_SHADER))
        self._locations = {}
        self._meshes = {}
        self._textures = {}
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

    def render(self, entities, camera, scene, width, height, mode="Lit"):
        """Draw into the caller's framebuffer without clearing or resizing it."""
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
            self._matrix("view",camera.view_matrix)
            self._matrix("projection",camera.projection_matrix(float(width)/height))
            self._vec3("eye",camera.position)
            right, up, back = camera.rotation[:,0],camera.rotation[:,1],camera.rotation[:,2]
            for name, direction in (("light0",back+up*1.1-right*0.8),
                                    ("light1",back*0.3+right+up*0.2),
                                    ("light2",-back+up+right*0.2)):
                self._vec3(name,direction/np.linalg.norm(direction))
            self._float("lightIntensity",getattr(scene,"material_light_intensity",1.0))
            self._float("ambientIntensity",getattr(scene,"material_ambient_intensity",1.0))
            records = []
            for entity in entities:
                mesh = self._mesh(self._entity_mesh(entity))
                matrix = np.asarray(entity.world_matrix,np.float32)
                center = matrix @ np.append(mesh[5],1)
                depth = float((camera.view_matrix @ center)[2])
                transparent = mesh[0].material.get("alphaMode","OPAQUE")=="BLEND"
                records.append((transparent,depth,entity,matrix,mesh))
            # Camera looks along -Z: more negative depth is farther away.
            records.sort(key=lambda row:(row[0],row[1] if row[0] else 0))
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
                normal_matrix = np.linalg.pinv(matrix[:3,:3]).T
                gl.glUniformMatrix3fv(self._loc("normalMatrix"),1,gl.GL_TRUE,np.asarray(normal_matrix,np.float32))
                self._material(material,mode)
                gl.glBindVertexArray(mesh[1])
                gl.glDrawElements(gl.GL_TRIANGLES,mesh[4],gl.GL_UNSIGNED_INT,None)
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

    @staticmethod
    def _save_state():
        integer_names = ("CURRENT_PROGRAM","VERTEX_ARRAY_BINDING","ARRAY_BUFFER_BINDING",
                         "ACTIVE_TEXTURE","DEPTH_FUNC","CULL_FACE_MODE","FRONT_FACE",
                         "BLEND_SRC_RGB","BLEND_DST_RGB","BLEND_SRC_ALPHA","BLEND_DST_ALPHA",
                         "BLEND_EQUATION_RGB","BLEND_EQUATION_ALPHA","STENCIL_CLEAR_VALUE",
                         "STENCIL_FUNC","STENCIL_REF","STENCIL_VALUE_MASK","STENCIL_WRITEMASK",
                         "STENCIL_FAIL","STENCIL_PASS_DEPTH_FAIL","STENCIL_PASS_DEPTH_PASS",
                         "STENCIL_BACK_FUNC","STENCIL_BACK_REF","STENCIL_BACK_VALUE_MASK",
                         "STENCIL_BACK_WRITEMASK","STENCIL_BACK_FAIL","STENCIL_BACK_PASS_DEPTH_FAIL",
                         "STENCIL_BACK_PASS_DEPTH_PASS")
        state = {name:int(gl.glGetIntegerv(getattr(gl,"GL_"+name))) for name in integer_names}
        state["enabled"] = {cap:bool(gl.glIsEnabled(cap)) for cap in
                            (gl.GL_DEPTH_TEST,gl.GL_CULL_FACE,gl.GL_BLEND,gl.GL_FRAMEBUFFER_SRGB,
                             gl.GL_STENCIL_TEST,gl.GL_SCISSOR_TEST,gl.GL_POLYGON_OFFSET_FILL)}
        state["polygon_offset"] = (float(gl.glGetFloatv(gl.GL_POLYGON_OFFSET_FACTOR)),
                                   float(gl.glGetFloatv(gl.GL_POLYGON_OFFSET_UNITS)))
        state["depth_mask"] = bool(gl.glGetBooleanv(gl.GL_DEPTH_WRITEMASK))
        state["color_mask"] = np.asarray(gl.glGetBooleanv(gl.GL_COLOR_WRITEMASK)).reshape(-1)
        state["polygon"] = np.asarray(gl.glGetIntegerv(gl.GL_POLYGON_MODE)).reshape(-1)
        state["textures"] = []
        for unit in range(len(MaterialRenderer._slots)):
            gl.glActiveTexture(gl.GL_TEXTURE0+unit)
            state["textures"].append(int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D)))
        return state

    @staticmethod
    def _restore_state(state):
        for cap, enabled in state["enabled"].items():
            (gl.glEnable if enabled else gl.glDisable)(cap)
        gl.glDepthMask(state["depth_mask"])
        gl.glPolygonOffset(*state["polygon_offset"])
        gl.glColorMask(*[bool(value) for value in state["color_mask"]])
        gl.glClearStencil(state["STENCIL_CLEAR_VALUE"])
        for face, prefix in ((gl.GL_FRONT,"STENCIL_"),(gl.GL_BACK,"STENCIL_BACK_")):
            gl.glStencilMaskSeparate(face,state[prefix+"WRITEMASK"])
            gl.glStencilFuncSeparate(face,state[prefix+"FUNC"],state[prefix+"REF"],state[prefix+"VALUE_MASK"])
            gl.glStencilOpSeparate(face,state[prefix+"FAIL"],state[prefix+"PASS_DEPTH_FAIL"],state[prefix+"PASS_DEPTH_PASS"])
        gl.glDepthFunc(state["DEPTH_FUNC"])
        gl.glCullFace(state["CULL_FACE_MODE"])
        gl.glFrontFace(state["FRONT_FACE"])
        gl.glBlendFuncSeparate(state["BLEND_SRC_RGB"],state["BLEND_DST_RGB"],
                               state["BLEND_SRC_ALPHA"],state["BLEND_DST_ALPHA"])
        gl.glBlendEquationSeparate(state["BLEND_EQUATION_RGB"],state["BLEND_EQUATION_ALPHA"])
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK,int(state["polygon"][0]))
        gl.glUseProgram(state["CURRENT_PROGRAM"])
        gl.glBindVertexArray(state["VERTEX_ARRAY_BINDING"])
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,state["ARRAY_BUFFER_BINDING"])
        for unit, texture in enumerate(state["textures"]):
            gl.glActiveTexture(gl.GL_TEXTURE0+unit)
            gl.glBindTexture(gl.GL_TEXTURE_2D,texture)
        gl.glActiveTexture(state["ACTIVE_TEXTURE"])

    def release(self):
        """Release cached geometry/images with the owning GL context current."""
        for _, vao, vbo, ebo, _, _ in self._meshes.values():
            gl.glDeleteVertexArrays(1,[vao])
            gl.glDeleteBuffers(2,[vbo,ebo])
        for _, texture in self._textures.values():
            gl.glDeleteTextures([texture])
        self._meshes.clear()
        self._textures.clear()

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
