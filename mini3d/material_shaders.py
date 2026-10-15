"""Material and selection GLSL; runtime ownership stays in MaterialRenderer."""
from .shadow_map import SHADOW_GLSL
from .sky_renderer import ATMOSPHERE_GLSL

VERTEX_SHADER = """#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in vec3 normal;
layout(location=2) in vec2 texcoord;
layout(location=3) in vec4 color;
layout(location=4) in mat4 instanceModel;
layout(location=8) in mat3 instanceNormal;
uniform mat4 model, view, projection;
uniform mat3 normalMatrix;
uniform bool useInstances;
out vec3 worldPosition;
out vec3 worldNormal;
out vec2 uv;
out vec4 vertexColor;
void main() {
    vec4 p = (useInstances ? instanceModel : model) * vec4(position, 1.0);
    worldPosition = p.xyz;
    worldNormal = (useInstances ? instanceNormal : normalMatrix) * normal;
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
uniform bool sceneLighting, photographicGround;
uniform bool environmentEnabled;
uniform float environmentIntensity;
uniform samplerCube diffuseEnv, specularEnv;
uniform sampler2D brdfLut;
""" + SHADOW_GLSL + ATMOSPHERE_GLSL + """
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
vec2 surfaceUV() { return photographicGround ? worldPosition.xy*groundScale : uv; }
vec3 mappedNormal() {
    vec3 n = normalize(worldNormal);
    if (!gl_FrontFacing) n = -n;
    if (!hasNormal) return n;
    vec3 dp1 = dFdx(worldPosition), dp2 = dFdy(worldPosition);
    vec2 dt1 = dFdx(surfaceUV()), dt2 = dFdy(surfaceUV());
    float determinant = dt1.x * dt2.y - dt1.y * dt2.x;
    if (abs(determinant) < 1e-10) return n;
    vec3 t = (dp1 * dt2.y - dp2 * dt1.y) / determinant;
    vec3 b = (dp2 * dt1.x - dp1 * dt2.x) / determinant;
    t -= n * dot(n, t);
    if (dot(t,t) < 1e-12) return n;
    t = normalize(t);
    b = normalize(cross(n,t)) * (dot(cross(n,t),b) < 0.0 ? -1.0 : 1.0);
    vec3 mapNormal = texture(normalMap, surfaceUV()).xyz * 2.0 - 1.0;
    mapNormal.xy *= normalScale;
    return normalize(mat3(t,b,n) * mapNormal);
}
void main() {
    vec4 base = baseFactor * vertexColor;
    if (hasBase) {
        vec4 sampled = texture(baseMap, surfaceUV());
        base *= vec4(linearize(sampled.rgb), sampled.a);
    }
    if (alphaMode == 1 && base.a < alphaCutoff) discard;
    float alpha = alphaMode == 2 ? base.a : 1.0;
    if (shadingMode == 1) { fragColor = vec4(srgb(photoAdjust(base.rgb)), alpha); return; }
    if (shadingMode == 2) { fragColor = vec4(0.72,0.83,0.94,alpha); return; }
    float metal = metallicFactor;
    float rough = roughnessFactor;
    if (hasMR) {
        vec4 mr = texture(mrMap,surfaceUV());
        metal *= mr.b; rough *= mr.g;
    }
    metal = clamp(metal, 0.0, 1.0);
    rough = clamp(rough, 0.045, 1.0);
    float specWeight = specularFactor;
    vec3 specColor = specularColorFactor;
    if (hasSpecular) specWeight *= texture(specularMap,surfaceUV()).a;
    if (hasSpecularColor) specColor *= linearize(texture(specularColorMap,surfaceUV()).rgb);
    vec3 f0 = mix(min(vec3(1.0), 0.04 * specColor) * specWeight, base.rgb, metal);
    vec3 n = mappedNormal();
    vec3 v = normalize(eye-worldPosition);
    float ao = hasAO ? mix(1.0,texture(aoMap,surfaceUV()).r,aoStrength) : 1.0;
    vec3 result;
    if (sceneLighting) {
        // light0 is surface-to-light in WORLD space, without distance falloff.
        // Keep the existing BRDF; no studio fill lights or reflection panels.
        result = directLight(n,v,light0,base.rgb,f0,metal,rough,(atmosphereEnabled ? sunColor : vec3(1.0))*lightIntensity) * shadowVisibility(worldPosition,n,light0);
        result += (1.0-metal)*base.rgb * ao * ambientIntensity * (atmosphereEnabled ? vec3(.55,.68,1.0) : vec3(1.0));
    } else {
        result = directLight(n,v,light0,base.rgb,f0,metal,rough,vec3(3.1,2.9,2.65));
        result += directLight(n,v,light1,base.rgb,f0,metal,rough,vec3(1.3,1.5,1.9));
        result += directLight(n,v,light2,base.rgb,f0,metal,rough,vec3(1.3));
        result *= lightIntensity;
        // Broad virtual studio panels keep metals legible without an HDR asset.
        vec3 reflection = reflect(-v,n);
        float panel = pow(max(dot(reflection,light0),0.0),mix(80.0,2.0,rough));
        panel += 0.65 * pow(max(dot(reflection,light1),0.0),mix(45.0,2.0,rough));
        vec3 reflected = fresnel(max(dot(n,v),0.0),f0) * (0.27 + panel * 0.9);
        result += ((1.0-metal)*base.rgb*0.32 + reflected) * ao * ambientIntensity;
    }
    if (environmentEnabled) {
        // Classic split-sum IBL, following Khronos/Filament (Q1 source notes).
        // Mini3D Z-up -> environment/glTF Y-up. No camera-relative rotation.
        vec3 rotatedN=photoHDREnabled ? photoEnvRotation*n : n;
        vec3 envN = vec3(rotatedN.x,rotatedN.z,-rotatedN.y);
        vec3 r = reflect(-v,n);
        if (photoHDREnabled) r=photoEnvRotation*r;
        vec3 envR = vec3(r.x,r.z,-r.y);
        vec2 ab = texture(brdfLut,vec2(clamp(dot(n,v),0.0,1.0),rough)).rg;
        vec3 radiance = textureLod(specularEnv,envR,rough*8.0).rgb;
        vec3 irradianceOverPi = texture(diffuseEnv,envN).rgb;
        float f90 = mix(clamp(specWeight,0.0,1.0),1.0,metal);
        vec3 specular = radiance * (f0*ab.x + f90*ab.y);
        vec3 diffuse = irradianceOverPi * (1.0-f0) * (1.0-metal) * base.rgb;
        result += (diffuse+specular) * ao * environmentIntensity;
    }
    if (atmosphereEnabled && sceneLighting && !photoHDREnabled) {
        vec3 reflectedSky=skyRadiance(reflect(-v,n),sunDirection,rough*.15);
        // Integrate the rough GGX response, as in the HDR split-sum path.
        // A bare grazing-angle Fresnel term makes matte sand reflect like water.
        vec2 skyBRDF=texture(brdfLut,vec2(clamp(dot(n,v),0.0,1.0),rough)).rg;
        float skyF90=mix(clamp(specWeight,0.0,1.0),1.0,metal);
        result+=(f0*skyBRDF.x+skyF90*skyBRDF.y)*reflectedSky*ao*.7;
    }
    vec3 emission = emissiveFactor;
    if (hasEmissive) emission *= linearize(texture(emissiveMap,surfaceUV()).rgb);
    result += emission;
    if (atmosphereEnabled) {
        float distanceToEye=length(eye-worldPosition);
        float fog=1.0-exp(-distanceToEye*hazeDensity);
        result=mix(result,skyRadiance(normalize(worldPosition-eye),sunDirection,.08),fog);
        fragColor=vec4(photoOutput(result),alpha);
        return;
    }
    // Gentle highlight compression, with an sRGB output for the viewport FBO.
    result = photoAdjust(result);
    result = result / (1.0 + result);
    vec3 displayColor=srgb(result);
    fragColor = vec4(displayColor, alpha);
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


