"""Procedural Z-up sunset sky. The visible sun and illumination share one vector.

The fullscreen pass owns only its program/VAO and preserves the caller's state.
The same linear radiance function supplies PBR reflections and distance haze.
"""
import numpy as np
from OpenGL import GL as gl
from OpenGL.GL.shaders import compileShader, compileProgram
from .gl_state import save_state, restore_state
from .atmosphere import atmosphere_state, sun_color
from .lighting import scene_light_direction
from .photo_color import PHOTO_COLOR_GLSL, bind_photo_color

ATMOSPHERE_GLSL = PHOTO_COLOR_GLSL + r'''
uniform bool atmosphereEnabled, photoHDREnabled, filmicTone;
uniform sampler2D photoSky;
uniform mat3 photoEnvRotation;
uniform float skyIntensity;
uniform vec3 sunColor, sunDirection;
uniform float exposureEV, hazeDensity, groundScale, photoFar;
// Integer lattice hashing avoids magnifying driver-dependent sin rounding.
float skyHash(vec3 p) {
    uvec3 q=uvec3(ivec3(p));
    uint h=q.x*1597334677u ^ q.y*3812015801u ^ q.z*2798796415u;
    h=(h ^ (h >> 16u))*2246822519u;
    h=(h ^ (h >> 13u))*3266489917u;
    h=h ^ (h >> 16u);
    return float(h >> 8u)/16777216.0;
}
float skyNoise(vec3 p) {
    vec3 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
    return mix(mix(mix(skyHash(i),skyHash(i+vec3(1,0,0)),f.x),
                   mix(skyHash(i+vec3(0,1,0)),skyHash(i+vec3(1,1,0)),f.x),f.y),
               mix(mix(skyHash(i+vec3(0,0,1)),skyHash(i+vec3(1,0,1)),f.x),
                   mix(skyHash(i+vec3(0,1,1)),skyHash(i+vec3(1,1,1)),f.x),f.y),f.z);
}
vec3 skyRadiance(vec3 ray, vec3 sun, float blur) {
    if (photoHDREnabled) {
        vec3 r=photoEnvRotation*normalize(ray);
        vec2 coords=vec2(.5+atan(-r.y,r.x)/6.28318530718,acos(clamp(r.z,-1.0,1.0))/3.14159265359);
        return textureLod(photoSky,coords,blur*7.0).rgb*skyIntensity;
    }
    float altitude=max(ray.z,0.0);
    float daylight=smoothstep(-.08,.5,sun.z);
    vec3 zenith=mix(vec3(.03,.065,.18),vec3(.075,.16,.32),daylight);
    vec3 horizon=mix(vec3(.9,.26,.12),vec3(.64,.48,.30),daylight);
    vec3 sky=mix(horizon,zenith,(1.0-exp(-altitude*22.0)));
    float angle=acos(clamp(dot(ray,sun),-1.0,1.0));
    sky+=sunColor*.6*exp(-angle*4.5)*exp(-altitude*1.3);
    float disc=1.0-smoothstep(.00465+blur,.0058+blur,angle);
    sky+=sunColor*8.0*disc/(1.0+blur*150.0);
    // Small wispy cloud layer; no separate sun or sky mesh is needed.
    vec3 p=ray/max(.12,ray.z+.22); p.xy*=1.3; p.z*=9.0;
    float n=.58*skyNoise(p*1.7)+.28*skyNoise(p*3.4)+.14*skyNoise(p*6.8);
    float cloud=smoothstep(.50,.68,n)*smoothstep(.02,.13,altitude)*(1.0-smoothstep(.35,.7,altitude));
    sky=mix(sky,vec3(.40,.24,.17)+sunColor*.12,cloud*.65*(1.0-blur));
    return sky;
}
vec3 photoOutput(vec3 linearColor) {
    vec3 c=clamp(photoAdjust(linearColor)*exp2(exposureEV),vec3(0.0),vec3(1e10));
    if (filmicTone) c=clamp((c*(2.51*c+.03))/(c*(2.43*c+.59)+.14),0.0,1.0);
    else c=c/(1.0+c);
    return mix(c*12.92,1.055*pow(c,vec3(1.0/2.4))-.055,step(vec3(.0031308),c));
}
'''

VERTEX = '''#version 330 core
out vec2 ndc;
void main() {
    ndc=vec2((gl_VertexID<<1)&2,gl_VertexID&2)*2.0-1.0;
    gl_Position=vec4(ndc,1.0,1.0);
}'''
FRAGMENT = '''#version 330 core
in vec2 ndc;
out vec4 fragColor;
uniform mat4 inverseProjection;
uniform mat3 cameraRotation;
''' + ATMOSPHERE_GLSL + '''
void main() {
    vec4 q=inverseProjection*vec4(ndc,1.0,1.0);
    vec3 ray=normalize(cameraRotation*q.xyz);
    fragColor=vec4(photoOutput(skyRadiance(ray,sunDirection,0.0)),1.0);
}'''


class SkyRenderer:
    def __init__(self):
        self.program = compileProgram(compileShader(VERTEX,gl.GL_VERTEX_SHADER),
                                      compileShader(FRAGMENT,gl.GL_FRAGMENT_SHADER))
        self.vao = int(gl.glGenVertexArrays(1))
        from .photo_environment import PhotoEnvironment
        self.environment=PhotoEnvironment()

    def render(self, scene, camera, aspect):
        state = save_state()
        try:
            settings=atmosphere_state(scene)
            gl.glUseProgram(self.program)
            bind_photo_sky(self.program,scene,self.environment)
            loc=lambda name: gl.glGetUniformLocation(self.program,name)
            gl.glDisable(gl.GL_DEPTH_TEST); gl.glDepthMask(False)
            gl.glDisable(gl.GL_CULL_FACE); gl.glDisable(gl.GL_BLEND)
            gl.glDisable(gl.GL_FRAMEBUFFER_SRGB)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK,gl.GL_FILL)
            gl.glUniformMatrix4fv(loc('inverseProjection'),1,gl.GL_TRUE,
                                 np.asarray(np.linalg.inv(camera.projection_matrix(aspect)),np.float32))
            gl.glUniformMatrix3fv(loc('cameraRotation'),1,gl.GL_TRUE,np.asarray(camera.rotation,np.float32))
            gl.glUniform3fv(loc('sunDirection'),1,np.asarray(scene_light_direction(scene),np.float32))
            gl.glUniform3fv(loc('sunColor'),1,np.asarray(sun_color(settings['sun_temperature']),np.float32))
            gl.glUniform1f(loc('exposureEV'),settings['exposure_ev'])
            gl.glBindVertexArray(self.vao); gl.glDrawArrays(gl.GL_TRIANGLES,0,3)
        finally:
            restore_state(state)

    def close(self):
        self.environment.close()
        if self.program:
            gl.glDeleteProgram(self.program); self.program=0
        if self.vao:
            gl.glDeleteVertexArrays(1,[self.vao]); self.vao=0


def bind_photo_sky(program,scene,environment,lighting=False):
    bind_photo_color(program, scene)
    from .photo_environment import sky_rotation
    settings=atmosphere_state(scene)
    enabled=settings['enabled'] and settings['sky_texture']!='procedural'
    loc=lambda name:gl.glGetUniformLocation(program,name)
    gl.glUniform1i(loc('photoHDREnabled'),enabled)
    gl.glUniform1i(loc('photoSky'),11)
    gl.glUniform1i(loc('filmicTone'),settings['tone_mapping']=='filmic')
    gl.glUniform1f(loc('skyIntensity'),settings['sky_intensity'])
    if enabled:
        environment.prepare(settings['sky_texture'],lighting=lighting)
        gl.glUniformMatrix3fv(loc('photoEnvRotation'),1,gl.GL_TRUE,
            np.asarray(sky_rotation(settings['sky_texture'],scene_light_direction(scene)),np.float32))
    return enabled
