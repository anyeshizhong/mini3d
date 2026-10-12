import numpy as np
from OpenGL.GL import *
from OpenGL.GL.shaders import compileShader, compileProgram
import ctypes
from .shadow_map import ShadowMap, SHADOW_GLSL
from .render_plan import build_render_plan


DTYPE = np.float32

# ==================== Rendering Modes ====================
# Set render_mode to control rendering style:
# - "REALISTIC" : Standard PBR-like shading
# - "TOON" : Cel-shaded anime/cartoon style (3D to 2D look)
# - "OUTLINE" : Toon + black outlines

RENDER_MODE = "OUTLINE"  # Change this to: "REALISTIC", "TOON", or "OUTLINE"

# ==================== Shaders ====================

SCREEN_LINE_VERT = """
#version 330 core
layout(location=0) in vec2 aPosNdc;
layout(location=1) in vec3 aColor;

out vec3 vColor;
void main(){
    vColor = aColor;
    gl_Position = vec4(aPosNdc, 0.0, 1.0);
}
"""

SCREEN_LINE_FRAG = """
#version 330 core
in vec3 vColor;
out vec4 FragColor;
void main(){
    FragColor = vec4(vColor, 1.0);
}
"""

LINE_VERT = """
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aColor;

uniform mat4 uView;
uniform mat4 uProj;

out vec3 vColor;

void main(){
    vColor = aColor;
    gl_Position = uProj * uView * vec4(aPos, 1.0);
}
"""

LINE_FRAG = """
#version 330 core
in vec3 vColor;
out vec4 FragColor;
void main(){
    FragColor = vec4(vColor, 1.0);
}
"""

VERT_SRC = """
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;

out vec3 vNormalW;
out vec3 vPosW;

void main(){
    vec4 posW = uModel * vec4(aPos, 1.0);
    vPosW = posW.xyz;
    
    // Normal transform: use normal matrix (inverse transpose of model matrix's upper-left 3x3)
    mat3 normalMatrix = mat3(transpose(inverse(uModel)));
    vNormalW = normalize(normalMatrix * aNormal);
    
    gl_Position = uProj * uView * posW;
}
"""

FRAG_SRC = """
#version 330 core
in vec3 vNormalW;
in vec3 vPosW;

uniform vec3 uBaseColor;
uniform vec3 uLightDirW;
uniform float uAmbient;
uniform float uDiffuse;

out vec4 FragColor;

""" + SHADOW_GLSL + """
void main(){
    vec3 N = normalize(vNormalW);
    vec3 L = normalize(uLightDirW);
    
    // Diffuse lighting
    float ndl = max(dot(N, L), 0.0);
    
    // Combined lighting
    float intensity = uAmbient + uDiffuse * ndl * shadowVisibility(vPosW, N, L);
    intensity = clamp(intensity, 0.0, 1.0);
    
    vec3 col = uBaseColor * intensity;
    FragColor = vec4(col, 1.0);
}
"""

# ==================== NPR (Toon/Cel Shading) Shaders ====================

TOON_FRAG = """
#version 330 core
in vec3 vNormalW;
in vec3 vPosW;

uniform vec3 uBaseColor;
uniform vec3 uLightDirW;
uniform float uAmbient;
uniform float uDiffuse;
uniform vec3 uCameraPos;

out vec4 FragColor;

""" + SHADOW_GLSL + """
void main(){
    vec3 N = normalize(vNormalW);
    vec3 L = normalize(uLightDirW);
    
    // Diffuse lighting
    float ndl = max(dot(N, L), 0.0);
    
    // Cel shading: quantize lighting into discrete levels
    float toonLevels = 4.0; // Number of shading levels
    float toonIntensity = floor(ndl * toonLevels) / toonLevels;
    
    // Add ambient
    float intensity = uAmbient + uDiffuse * toonIntensity * shadowVisibility(vPosW, N, L);
    intensity = clamp(intensity, 0.0, 1.0);
    
    // Specular highlight (toon style)
    vec3 V = normalize(uCameraPos - vPosW);
    vec3 H = normalize(L + V);
    float specAngle = max(dot(N, H), 0.0);
    float specular = pow(specAngle, 32.0);
    
    // Quantize specular
    if (specular > 0.8) {
        specular = 1.0;
    } else {
        specular = 0.0;
    }
    
    // Rim lighting (Fresnel-like edge glow)
    float rimDot = 1.0 - max(dot(V, N), 0.0);
    float rimIntensity = rimDot * rimDot;
    rimIntensity = smoothstep(0.6, 1.0, rimIntensity);
    
    // Combine
    vec3 col = uBaseColor * intensity;
    col += vec3(0.3) * specular * shadowVisibility(vPosW, N, L); // White specular highlight
    col += uBaseColor * 0.5 * rimIntensity; // Rim light
    
    FragColor = vec4(col, 1.0);
}
"""

# Outline pass shader (for OUTLINE mode)
OUTLINE_VERT = """
#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;

uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;
uniform float uOutlineWidth;

void main(){
    // Transform to view space
    mat4 modelView = uView * uModel;
    vec4 viewPos = modelView * vec4(aPos, 1.0);
    
    // Transform normal to view space
    mat3 normalMatrix = mat3(transpose(inverse(modelView)));
    vec3 viewNormal = normalize(normalMatrix * aNormal);
    
    // Expand in view space (screen-consistent outline width)
    viewPos.xyz += viewNormal * uOutlineWidth;
    
    // Project to clip space
    gl_Position = uProj * viewPos;
}
"""

OUTLINE_FRAG = """
#version 330 core
out vec4 FragColor;

uniform vec3 uOutlineColor;

void main(){
    FragColor = vec4(uOutlineColor, 1.0);
}
"""


# ==================== Helper Functions ====================

def perspective_matrix(fov_y_deg, aspect, near, far):
    """
    Standard OpenGL perspective projection matrix
    """
    fov_rad = np.radians(fov_y_deg)
    f = 1.0 / np.tan(fov_rad / 2.0)
    
    P = np.zeros((4, 4), dtype=DTYPE)
    P[0, 0] = f / aspect
    P[1, 1] = f
    P[2, 2] = (far + near) / (near - far)
    P[2, 3] = (2.0 * far * near) / (near - far)
    P[3, 2] = -1.0
    
    return P


def perspective_from_focal(focal_px, w, h, near=0.1, far=5000.0):
    """
    Convert pixel focal length to OpenGL perspective matrix
    Improved calculation to match your existing projection
    """
    f = float(focal_px)
    width = float(w)
    height = float(h)
    
    # Calculate field of view from focal length
    # For pixel coordinates: x_screen = f * (X/Z) + width/2
    # This means: tan(fov_x/2) = (width/2) / f
    fov_x = 2.0 * np.arctan(width / (2.0 * f))
    fov_y = 2.0 * np.arctan(height / (2.0 * f))
    
    # Use fov_y for standard perspective matrix
    aspect = width / height
    
    P = np.zeros((4, 4), dtype=DTYPE)
    
    # Standard perspective matrix
    tan_half_fov_y = np.tan(fov_y / 2.0)
    
    P[0, 0] = 1.0 / (aspect * tan_half_fov_y)
    P[1, 1] = 1.0 / tan_half_fov_y
    P[2, 2] = -(far + near) / (far - near)
    P[2, 3] = -(2.0 * far * near) / (far - near)
    P[3, 2] = -1.0
    
    return P


def add_axis_with_arrow(p0, p1, col, scale=50.0, head_len_ratio=0.18, head_w_ratio=0.08):
    """
    Create axis line with arrow head
    """
    head_len = float(scale) * float(head_len_ratio)
    head_w = float(scale) * float(head_w_ratio)
    seg_verts = []
    seg_cols = []

    # Main axis line
    seg_verts += [p0, p1]
    seg_cols += [col, col]

    # Arrow head
    d = p1 - p0
    dn = d / (np.linalg.norm(d) + 1e-9)

    # Choose perpendicular vector
    up = np.array([0, 0, 1], dtype=np.float32)
    if abs(float(np.dot(dn, up))) > 0.9:
        up = np.array([0, 1, 0], dtype=np.float32)

    s = np.cross(dn, up)
    s = s / (np.linalg.norm(s) + 1e-9)

    base = p1 - dn * head_len
    a = base + s * head_w
    b = base - s * head_w

    seg_verts += [p1, a, p1, b]
    seg_cols += [col, col, col, col]

    return seg_verts, seg_cols


# ==================== OpenGL Objects ====================

class GLGrid:
    def __init__(self, grid_size=200, step=20, z0=0.0):
        base = np.array([90, 90, 90], dtype=np.float32) / 255.0
        xcol = np.array([180, 80, 80], dtype=np.float32) / 255.0
        ycol = np.array([80, 180, 80], dtype=np.float32) / 255.0

        verts = []
        colors = []

        for i in range(-grid_size, grid_size + 1, step):
            # Parallel to Y axis (X=i)
            a1 = [i, -grid_size, z0]
            b1 = [i, grid_size, z0]
            # Parallel to X axis (Y=i)
            a2 = [-grid_size, i, z0]
            b2 = [grid_size, i, z0]

            if i == 0:
                # X=0 is Y-axis (green)
                verts += [a1, b1]
                colors += [ycol, ycol]
                # Y=0 is X-axis (red)
                verts += [a2, b2]
                colors += [xcol, xcol]
            else:
                verts += [a1, b1, a2, b2]
                colors += [base, base, base, base]

        inter = np.hstack([
            np.asarray(verts, np.float32),
            np.asarray(colors, np.float32)
        ])

        self.count = inter.shape[0]
        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)

        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_STATIC_DRAW)

        stride = 6 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
        
        glBindVertexArray(0)


class GLMeshGPU:
    def __init__(self, mesh):
        """
        Upload mesh data to GPU
        """
        # Vertices
        v = np.asarray(mesh.vertices, dtype=DTYPE)
        if v.shape[1] >= 3:
            pos = v[:, :3].astype(DTYPE)
        else:
            raise ValueError("mesh.vertices dimension incorrect")

        # Normals
        nrm = np.asarray(mesh.vertex_normals, dtype=DTYPE)
        if nrm.shape[0] != pos.shape[0]:
            raise ValueError("vertex_normals count must match vertices")

        # Indices
        idx = np.asarray(mesh.indices, dtype=np.uint32).reshape(-1)

        # Interleave: pos(3) + normal(3)
        inter = np.concatenate([pos, nrm], axis=1).astype(DTYPE)

        self.count = idx.size

        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)
        self.ebo = glGenBuffers(1)

        glBindVertexArray(self.vao)

        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_STATIC_DRAW)

        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, GL_STATIC_DRAW)

        stride = 6 * 4

        # Position attribute
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))

        # Normal attribute
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

        glBindVertexArray(0)


# ==================== Main Renderer ====================

class GLRenderer:
    def __init__(self, width, height):
        self.w = width
        self.h = height
        
        # Render mode setting
        self.render_mode = RENDER_MODE  # "REALISTIC", "TOON", or "OUTLINE"

        # Shadow comparison and raw-depth samplers start on unit zero after
        # linking. bind_shadow assigns separate units before drawing, as in
        # MaterialRenderer; pre-assignment validation fails on strict drivers.
        # Main mesh shader (realistic)
        self.program = compileProgram(
            compileShader(VERT_SRC, GL_VERTEX_SHADER),
            compileShader(FRAG_SRC, GL_FRAGMENT_SHADER),
            validate=False,
        )

        # Get uniform locations
        self.locModel = glGetUniformLocation(self.program, "uModel")
        self.locView = glGetUniformLocation(self.program, "uView")
        self.locProj = glGetUniformLocation(self.program, "uProj")
        self.locBase = glGetUniformLocation(self.program, "uBaseColor")
        self.locLdir = glGetUniformLocation(self.program, "uLightDirW")
        self.locAmb = glGetUniformLocation(self.program, "uAmbient")
        self.locDif = glGetUniformLocation(self.program, "uDiffuse")
        
        # Toon shader
        self.toon_program = compileProgram(
            compileShader(VERT_SRC, GL_VERTEX_SHADER),
            compileShader(TOON_FRAG, GL_FRAGMENT_SHADER),
            validate=False,
        )
        self.toon_locModel = glGetUniformLocation(self.toon_program, "uModel")
        self.toon_locView = glGetUniformLocation(self.toon_program, "uView")
        self.toon_locProj = glGetUniformLocation(self.toon_program, "uProj")
        self.toon_locBase = glGetUniformLocation(self.toon_program, "uBaseColor")
        self.toon_locLdir = glGetUniformLocation(self.toon_program, "uLightDirW")
        self.toon_locAmb = glGetUniformLocation(self.toon_program, "uAmbient")
        self.toon_locDif = glGetUniformLocation(self.toon_program, "uDiffuse")
        self.toon_locCamPos = glGetUniformLocation(self.toon_program, "uCameraPos")
        
        # Outline shader
        self.outline_program = compileProgram(
            compileShader(OUTLINE_VERT, GL_VERTEX_SHADER),
            compileShader(OUTLINE_FRAG, GL_FRAGMENT_SHADER),
        )
        self.outline_locModel = glGetUniformLocation(self.outline_program, "uModel")
        self.outline_locView = glGetUniformLocation(self.outline_program, "uView")
        self.outline_locProj = glGetUniformLocation(self.outline_program, "uProj")
        self.outline_locWidth = glGetUniformLocation(self.outline_program, "uOutlineWidth")
        self.outline_locColor = glGetUniformLocation(self.outline_program, "uOutlineColor")

        # Line shader
        self.line_program = compileProgram(
            compileShader(LINE_VERT, GL_VERTEX_SHADER),
            compileShader(LINE_FRAG, GL_FRAGMENT_SHADER),
        )
        self.line_locView = glGetUniformLocation(self.line_program, "uView")
        self.line_locProj = glGetUniformLocation(self.line_program, "uProj")

        # Screen line shader
        self.screen_line_program = compileProgram(
            compileShader(SCREEN_LINE_VERT, GL_VERTEX_SHADER),
            compileShader(SCREEN_LINE_FRAG, GL_FRAGMENT_SHADER),
        )

        # OpenGL state
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)
        glFrontFace(GL_CCW)  # Counter-clockwise winding
        
        # Enable MSAA if available
        glEnable(GL_MULTISAMPLE)

        # GPU cache
        self.gpu_cache = {}
        self.shadow_map = ShadowMap()
        self.frustum_culling = True
        self.last_render_plan = None
        self.render_stats = {}
        self._active_shadow = None
        self._photo_ground = None

        # Grid
        self.grid = GLGrid(grid_size=200, step=20, z0=0.0)

        # Dynamic buffers
        self.screen_line_vao = glGenVertexArrays(1)
        self.screen_line_vbo = glGenBuffers(1)
        self.axes_vao = glGenVertexArrays(1)
        self.axes_vbo = glGenBuffers(1)

        self.resize(width, height)
        
        print(f"Renderer initialized in {self.render_mode} mode")

    def resize(self, width, height):
        self.w = max(1, int(width))
        self.h = max(1, int(height))
        glViewport(0, 0, self.w, self.h)

    def _get_gpu(self, mesh):
        key = id(mesh)
        if key not in self.gpu_cache:
            self.gpu_cache[key] = GLMeshGPU(mesh)
        return self.gpu_cache[key]

    def render(self, scene, camera):
        from .atmosphere import prepare_photographic_scene
        scene, self._photo_ground = prepare_photographic_scene(scene, camera, getattr(self, '_photo_ground', None))
        active = int(glGetIntegerv(GL_ACTIVE_TEXTURE))
        glActiveTexture(GL_TEXTURE0+ShadowMap.UNIT)
        binding = int(glGetIntegerv(GL_TEXTURE_BINDING_2D))
        sampler = int(glGetIntegerv(GL_SAMPLER_BINDING))
        glActiveTexture(GL_TEXTURE12)
        raw_binding=int(glGetIntegerv(GL_TEXTURE_BINDING_2D))
        raw_sampler=int(glGetIntegerv(GL_SAMPLER_BINDING))
        glActiveTexture(active)
        plan = build_render_plan(scene, camera, self.w, self.h,
                                 self.frustum_culling, self.render_mode)
        self.last_render_plan = plan
        self.render_stats = plan.stats
        try:
            self._active_shadow = None
            if getattr(scene, 'shadows_enabled', False) and getattr(scene, 'lighting_mode', 'Studio') == 'Scene' and getattr(scene, 'render_mode', 'Lit').lower() == 'lit':
                entities = plan.shadow_candidates
                if any(getattr(e.model, 'material', None) is not None for e in entities) and not hasattr(self, 'material_renderer'):
                    from .material_renderer import MaterialRenderer
                    self.material_renderer = MaterialRenderer()
                self.shadow_map.render(entities, scene, self,
                                       camera=camera, aspect=float(self.w)/self.h)
                self._active_shadow = self.shadow_map
                self.render_stats.update(shadow_draw_calls=self.shadow_map.draw_calls,
                                         shadow_triangles=self.shadow_map.triangles,
                                         shadow_cache_hit=self.shadow_map.cache_hit)
            self._render_scene(scene, camera, plan)
            self.render_stats["draw_calls"] = (self.render_stats["color_draw_calls"] +
                                               self.render_stats["shadow_draw_calls"])
            self.render_stats["submitted_triangles"] = (self.render_stats["color_triangles"] +
                                                        self.render_stats["shadow_triangles"])
        finally:
            glActiveTexture(GL_TEXTURE0+ShadowMap.UNIT)
            glBindTexture(GL_TEXTURE_2D,binding)
            glBindSampler(ShadowMap.UNIT,sampler)
            glActiveTexture(GL_TEXTURE12)
            glBindTexture(GL_TEXTURE_2D,raw_binding)
            glBindSampler(12,raw_sampler)
            glActiveTexture(active)

    def close(self):
        if hasattr(self, 'depth_of_field'):
            self.depth_of_field.close()
        self.last_render_plan = None
        self.shadow_map.close()
        if hasattr(self, 'sky_renderer'):
            self.sky_renderer.close()
        if hasattr(self, 'material_renderer'):
            self.material_renderer.close()
        for gpu in self.gpu_cache.values():
            glDeleteVertexArrays(1,[gpu.vao])
            glDeleteBuffers(2,[gpu.vbo,gpu.ebo])
        self.gpu_cache.clear()
        for name in ('program','toon_program','outline_program','line_program','screen_line_program'):
            program = getattr(self,name,0)
            if program:
                glDeleteProgram(program)
                setattr(self,name,0)
        for name in ('screen_line_vao','axes_vao'):
            value = getattr(self,name,0)
            if value:
                glDeleteVertexArrays(1,[value])
                setattr(self,name,0)
        for name in ('screen_line_vbo','axes_vbo'):
            value = getattr(self,name,0)
            if value:
                glDeleteBuffers(1,[value])
                setattr(self,name,0)
        if self.grid.vao:
            glDeleteVertexArrays(1,[self.grid.vao])
            glDeleteBuffers(1,[self.grid.vbo])
            self.grid.vao = 0

    def _render_scene(self, scene, camera, plan=None):
        # Clear
        glClearColor(30/255, 30/255, 35/255, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        from .atmosphere import atmosphere_state
        if atmosphere_state(scene)['enabled']:
            if not hasattr(self, 'sky_renderer'):
                from .sky_renderer import SkyRenderer
                self.sky_renderer = SkyRenderer()
            self.sky_renderer.render(scene, camera, float(self.w)/self.h)

        # Camera owns a standard OpenGL view/projection (Y-up, -Z forward).
        # Read viewport aspect every frame, including after a window resize.
        if plan is None:
            plan = build_render_plan(scene, camera, self.w, self.h,
                                     self.frustum_culling, self.render_mode)
            self.render_stats = plan.stats
        V, P = plan.view, plan.projection
        cam_pos = camera.position

        # ==================== Render Based on Mode ====================
        entities, imported = plan.legacy, plan.imported
        
        if self.render_mode == "OUTLINE":
            # Two-pass rendering: outline + toon shading
            self._render_outline_pass(entities, V, P, scene)
            self._render_toon_pass(entities, V, P, scene, cam_pos)
        elif self.render_mode == "TOON":
            # Single-pass toon shading
            self._render_toon_pass(entities, V, P, scene, cam_pos)
        else:  # REALISTIC
            # Standard realistic rendering
            self._render_realistic_pass(entities, V, P, scene)

        if imported:
            if not hasattr(self, "material_renderer"):
                from .material_renderer import MaterialRenderer
                self.material_renderer = MaterialRenderer()
            self.material_renderer.render(imported, camera, scene, self.w, self.h,
                                          mode=getattr(scene, "render_mode", "Lit"), shadow=self._active_shadow,
                                          plan=plan)
            self.render_stats["color_draw_calls"] += self.material_renderer.draw_calls
            self.render_stats["color_triangles"] += self.material_renderer.triangles

        self.render_editor_grid(scene, camera)

        # ==================== Render Axes ====================
        glDisable(GL_DEPTH_TEST)
        
        # World axes
        if getattr(scene, "show_axes", True):
            self.draw_axes_world(V, P, origin=(0, 0, 0), scale=60.0)
        
        # Entity axes
        for ent in entities:
            if getattr(ent, "isaxes", False) and not getattr(scene, "_hide_entity_axes", False):
                self.draw_axes_at_matrix(V, P, ent.world_matrix, scale=30.0)
        
        glEnable(GL_DEPTH_TEST)
    
    def render_editor_grid(self, scene, camera):
        """Finite editor guide lines: read scene depth, never write it."""
        if not getattr(scene, "show_grid", True):
            return
        depth_mask = bool(glGetBooleanv(GL_DEPTH_WRITEMASK))
        depth_test = bool(glIsEnabled(GL_DEPTH_TEST))
        depth_func = int(glGetIntegerv(GL_DEPTH_FUNC))
        program = int(glGetIntegerv(GL_CURRENT_PROGRAM))
        vao = int(glGetIntegerv(GL_VERTEX_ARRAY_BINDING))
        line_width = float(glGetFloatv(GL_LINE_WIDTH))
        try:
            glDepthMask(False)
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LEQUAL)
            glUseProgram(self.line_program)
            scale = getattr(scene, "grid_scale", 1.0)
            transform = np.diag([scale, scale, 1., 1.])
            transform[2, 3] = getattr(getattr(scene, "placement_plane", None), "z", 0.)
            glUniformMatrix4fv(self.line_locView, 1, GL_TRUE,
                               (camera.view_matrix @ transform).astype(DTYPE))
            glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE,
                               camera.projection_matrix(self.w / self.h).astype(DTYPE))
            glBindVertexArray(self.grid.vao)
            glLineWidth(1.0)
            glDrawArrays(GL_LINES, 0, self.grid.count)
        finally:
            glDepthMask(depth_mask)
            (glEnable if depth_test else glDisable)(GL_DEPTH_TEST)
            glDepthFunc(depth_func)
            glUseProgram(program)
            glBindVertexArray(vao)
            glLineWidth(line_width)

    def _render_realistic_pass(self, entities, V, P, scene):
        """Standard realistic rendering"""
        glUseProgram(self.program)
        if hasattr(self, "_active_shadow"):
            ShadowMap.bind(self.program, self._active_shadow, scene)
        
        # Set view and projection
        glUniformMatrix4fv(self.locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.locProj, 1, GL_TRUE, P)

        # Set lighting
        from .lighting import scene_light_direction
        ldir = scene_light_direction(scene)
        glUniform3f(self.locLdir, float(ldir[0]), float(ldir[1]), float(ldir[2]))
        glUniform1f(self.locAmb, float(scene.ambient))
        glUniform1f(self.locDif, float(scene.diffuse))

        # Render entities
        for ent in entities:
            if not ent.model:
                continue

            gpu = self._get_gpu(ent.model)

            # Set model matrix
            M = ent.world_matrix.astype(DTYPE)
            glUniformMatrix4fv(self.locModel, 1, GL_TRUE, M)

            # Set base color
            if hasattr(ent.model, "base_color"):
                bc = np.asarray(ent.model.base_color, dtype=np.float32) / 255.0
            else:
                bc = np.asarray(ent.model.colors[0], dtype=np.float32) / 255.0

            glUniform3f(self.locBase, float(bc[0]), float(bc[1]), float(bc[2]))

            # Draw
            glBindVertexArray(gpu.vao)
            glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, None)
            self.render_stats["color_draw_calls"] += 1
            self.render_stats["color_triangles"] += gpu.count // 3
            glBindVertexArray(0)
    
    def _render_toon_pass(self, entities, V, P, scene, cam_pos):
        """Toon/cel-shading rendering"""
        glUseProgram(self.toon_program)
        if hasattr(self, "_active_shadow"):
            ShadowMap.bind(self.toon_program, self._active_shadow, scene)
        
        # Set view and projection
        glUniformMatrix4fv(self.toon_locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.toon_locProj, 1, GL_TRUE, P)

        # Set lighting
        from .lighting import scene_light_direction
        ldir = scene_light_direction(scene)
        glUniform3f(self.toon_locLdir, float(ldir[0]), float(ldir[1]), float(ldir[2]))
        glUniform1f(self.toon_locAmb, float(scene.ambient))
        glUniform1f(self.toon_locDif, float(scene.diffuse))
        
        # Set camera position
        glUniform3f(self.toon_locCamPos, float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2]))

        # Render entities
        for ent in entities:
            if not ent.model:
                continue

            gpu = self._get_gpu(ent.model)

            # Set model matrix
            M = ent.world_matrix.astype(DTYPE)
            glUniformMatrix4fv(self.toon_locModel, 1, GL_TRUE, M)

            # Set base color
            if hasattr(ent.model, "base_color"):
                bc = np.asarray(ent.model.base_color, dtype=np.float32) / 255.0
            else:
                bc = np.asarray(ent.model.colors[0], dtype=np.float32) / 255.0

            glUniform3f(self.toon_locBase, float(bc[0]), float(bc[1]), float(bc[2]))

            # Draw
            glBindVertexArray(gpu.vao)
            glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, None)
            self.render_stats["color_draw_calls"] += 1
            self.render_stats["color_triangles"] += gpu.count // 3
            glBindVertexArray(0)
    
    def _render_outline_pass(self, entities, V, P, scene):
        """Render black outlines (first pass for outline mode)"""
        glUseProgram(self.outline_program)
        
        # Set view and projection
        glUniformMatrix4fv(self.outline_locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.outline_locProj, 1, GL_TRUE, P)
        
        # Outline settings - REDUCED for better visibility
        outline_width = 0.15  # Much thinner! (was 0.5)
        outline_color = np.array([0.0, 0.0, 0.0], dtype=DTYPE)  # Black outlines
        
        glUniform1f(self.outline_locWidth, outline_width)
        glUniform3f(self.outline_locColor, outline_color[0], outline_color[1], outline_color[2])
        
        # AGGRESSIVE FIX for spheres: Much stronger depth offset
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(10.0, 10.0)  # Even stronger offset
        
        # Also disable depth write for outline pass
        glDepthMask(GL_FALSE)  # Don't write to depth buffer
        
        # Render front faces as outlines (inverted culling)
        glCullFace(GL_FRONT)

        # Render entities
        for ent in entities:
            if not ent.model:
                continue

            gpu = self._get_gpu(ent.model)

            # Set model matrix
            M = ent.world_matrix.astype(DTYPE)
            glUniformMatrix4fv(self.outline_locModel, 1, GL_TRUE, M)

            # Draw
            glBindVertexArray(gpu.vao)
            glDrawElements(GL_TRIANGLES, gpu.count, GL_UNSIGNED_INT, None)
            self.render_stats["color_draw_calls"] += 1
            self.render_stats["color_triangles"] += gpu.count // 3
            glBindVertexArray(0)
        
        # Restore normal state
        glCullFace(GL_BACK)
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDepthMask(GL_TRUE)  # Re-enable depth writes

    def draw_axes_world(self, V, P, origin=(0.0, 0.0, 0.0), scale=50.0,
                        head_len_ratio=0.18, head_w_ratio=0.08):
        """
        Draw world coordinate axes: X(red), Y(green), Z(blue)
        """
        o = np.array(origin, dtype=np.float32)

        # Axis endpoints
        x = o + np.array([scale, 0, 0], dtype=np.float32)
        y = o + np.array([0, scale, 0], dtype=np.float32)
        z = o + np.array([0, 0, scale], dtype=np.float32)

        # Colors
        R = np.array([1.0, 0.2, 0.2], dtype=np.float32)
        G = np.array([0.2, 1.0, 0.2], dtype=np.float32)
        B = np.array([0.2, 0.2, 1.0], dtype=np.float32)

        verts = []
        cols = []

        v, c = add_axis_with_arrow(o, x, R, scale)
        verts += v
        cols += c
        v, c = add_axis_with_arrow(o, y, G, scale)
        verts += v
        cols += c
        v, c = add_axis_with_arrow(o, z, B, scale)
        verts += v
        cols += c

        verts = np.asarray(verts, dtype=np.float32)
        cols = np.asarray(cols, dtype=np.float32)

        inter = np.hstack([verts, cols]).astype(np.float32)

        prev_prog = glGetIntegerv(GL_CURRENT_PROGRAM)

        glUseProgram(self.line_program)
        glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

        glBindVertexArray(self.axes_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.axes_vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

        stride = 6 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

        glLineWidth(2.0)
        glDrawArrays(GL_LINES, 0, verts.shape[0])

        glBindVertexArray(0)
        glUseProgram(prev_prog)

    def draw_axes_at_matrix(self, V, P, T_w, scale=30.0):
        """
        Draw local coordinate axes at given transform matrix
        """
        T = np.asarray(T_w, dtype=np.float32)

        o = T[:3, 3]
        ex = T[:3, 0]
        ex = ex / (np.linalg.norm(ex) + 1e-9)
        ey = T[:3, 1]
        ey = ey / (np.linalg.norm(ey) + 1e-9)
        ez = T[:3, 2]
        ez = ez / (np.linalg.norm(ez) + 1e-9)

        x = o + ex * scale
        y = o + ey * scale
        z = o + ez * scale

        R = np.array([1.0, 0.2, 0.2], dtype=np.float32)
        G = np.array([0.2, 1.0, 0.2], dtype=np.float32)
        B = np.array([0.2, 0.2, 1.0], dtype=np.float32)

        verts = []
        cols = []

        v, c = add_axis_with_arrow(o, x, R, scale)
        verts += v
        cols += c
        v, c = add_axis_with_arrow(o, y, G, scale)
        verts += v
        cols += c
        v, c = add_axis_with_arrow(o, z, B, scale)
        verts += v
        cols += c

        verts = np.asarray(verts, dtype=np.float32)
        cols = np.asarray(cols, dtype=np.float32)

        inter = np.hstack([verts, cols]).astype(np.float32)

        prev_prog = glGetIntegerv(GL_CURRENT_PROGRAM)

        glUseProgram(self.line_program)
        glUniformMatrix4fv(self.line_locView, 1, GL_TRUE, V)
        glUniformMatrix4fv(self.line_locProj, 1, GL_TRUE, P)

        glBindVertexArray(self.axes_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.axes_vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

        stride = 6 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))

        glLineWidth(2.0)
        glDrawArrays(GL_LINES, 0, verts.shape[0])

        glBindVertexArray(0)
        glUseProgram(prev_prog)

    def draw_screen_lines(self, segments_px, colors_rgb, widths=None):
        """
        Draw 2D lines in screen space (pixel coordinates)
        """
        if len(segments_px) == 0:
            return

        seg = np.asarray(segments_px, np.float32)
        col = np.asarray(colors_rgb, np.float32) / 255.0

        W, H = float(self.w), float(self.h)

        # Convert pixel coords to NDC
        x = seg[..., 0]
        y = seg[..., 1]
        x_ndc = 2.0 * (x / (W + 1e-9)) - 1.0
        y_ndc = 1.0 - 2.0 * (y / (H + 1e-9))

        # Flatten to vertex stream
        pos = np.stack([x_ndc, y_ndc], axis=-1).reshape(-1, 2)

        # Repeat colors
        col2 = np.repeat(col, 2, axis=0)

        inter = np.hstack([pos, col2]).astype(np.float32)

        glUseProgram(self.screen_line_program)
        glBindVertexArray(self.screen_line_vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.screen_line_vbo)
        glBufferData(GL_ARRAY_BUFFER, inter.nbytes, inter, GL_DYNAMIC_DRAW)

        stride = 5 * 4
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(8))

        if widths is not None:
            glLineWidth(float(np.max(widths)))
        else:
            glLineWidth(1.0)

        glDrawArrays(GL_LINES, 0, inter.shape[0])
        glBindVertexArray(0)

    def draw_grid_cpu_like(self, camera, grid_size=200, step=20, z0=0.0, near=None):
        """
        Fallback: CPU-side grid rendering (for compatibility)
        """
        near = camera.near if near is None else near
        focal = self.h / (2 * np.tan(np.deg2rad(camera.fov_y) / 2))
        base_color = (90, 90, 90)
        x_axis_color = (180, 80, 80)
        y_axis_color = (80, 180, 80)

        lines = []
        colors = []
        widths = []

        for i in range(-grid_size, grid_size + 1, step):
            a1 = [i, -grid_size, z0, 1]
            b1 = [i, grid_size, z0, 1]
            a2 = [-grid_size, i, z0, 1]
            b2 = [grid_size, i, z0, 1]

            if i == 0:
                lines.append([a1, b1])
                colors.append(y_axis_color)
                widths.append(2)
                lines.append([a2, b2])
                colors.append(x_axis_color)
                widths.append(2)
            else:
                lines.append([a1, b1])
                colors.append(base_color)
                widths.append(1)
                lines.append([a2, b2])
                colors.append(base_color)
                widths.append(1)

        lines = np.asarray(lines, dtype=np.float32)

        # Transform to camera space
        flat = lines.reshape(-1, 4)
        flat_cam = flat @ camera.T_w_to_c.T
        lines_cam = flat_cam.reshape(-1, 2, 4)

        # Project
        seg2d = []
        segcol = []
        segw = []

        for seg, col, w in zip(lines_cam, colors, widths):
            p0 = seg[0]
            p1 = seg[1]

            if p0[2] <= near or p1[2] <= near:
                continue

            x0 = focal * (p0[0] / p0[2]) + self.w / 2.0
            y0 = focal * (p0[1] / p0[2]) + self.h / 2.0
            x1 = focal * (p1[0] / p1[2]) + self.w / 2.0
            y1 = focal * (p1[1] / p1[2]) + self.h / 2.0

            seg2d.append([[x0, y0], [x1, y1]])
            segcol.append(col)
            segw.append(w)

        self.draw_screen_lines(seg2d, segcol, segw)
