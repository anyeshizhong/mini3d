#version 330 core
#ifdef ANALYTIC_GROUND
vec3 worldPosition;
in vec2 groundNDC;
flat in float groundHeight;
uniform mat4 groundInverseViewProjection, view, projection;
#else
in vec3 worldPosition;
#endif
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

uniform bool shadowEnabled, shadowPCF;
uniform sampler2DArrayShadow shadowDepth;
uniform sampler2DArray shadowRaw;
uniform float sunRadius;
uniform vec3 shadowWorldScale, shadowPreviousWorldScale;
uniform mat4 shadowMatrix, shadowPreviousMatrix;
uniform float shadowBias;
uniform int shadowLayer, shadowPreviousLayer;
uniform bool shadowTransition;
uniform float shadowBlend;

float shadowMapVisibility(vec3 world, vec3 normal, vec3 light, mat4 matrix,
                          vec3 worldScale, int layer, out bool inside) {
    vec4 p = matrix * vec4(world, 1.0);
    vec3 q = p.xyz / p.w * 0.5 + 0.5;
    inside = !any(lessThan(q, vec3(0.0))) && !any(greaterThan(q, vec3(1.0)));
    if (!inside) return 1.0;
    float bias = shadowBias * (1.0 + 4.0 * (1.0 - max(dot(normal, light), 0.0)));
    vec2 texel = 1.0 / vec2(textureSize(shadowDepth, 0).xy);
    // Orthographic PCSS: search raw blocker depths, then filter comparisons.
    // Sun radius is angular; blocker distance sets the penumbra in world units.
    if (shadowPCF && sunRadius>0.0) {
        const vec2 disk[16]=vec2[16](vec2(0,0),vec2(-.63,-.47),vec2(.67,.48),
            vec2(.44,-.77),vec2(-.49,.73),vec2(-.89,.14),vec2(.87,-.16),
            vec2(.15,.93),vec2(-.13,-.94),vec2(.29,.26),vec2(-.28,-.23),
            vec2(-.37,.31),vec2(.32,-.34),vec2(.73,-.61),vec2(-.76,-.60),vec2(-.70,.60));
        vec2 search=max(texel,worldScale.xy*sunRadius*q.z*worldScale.z);
        search=min(search,vec2(.03));
        float sum=0.0, count=0.0;
        for (int i=0;i<16;++i) {
            float depth=texture(shadowRaw,vec3(q.xy+disk[i]*search,float(layer))).r;
            if (depth<q.z-bias) {sum+=depth;count+=1.0;}
        }
        if (count==0.0) return 1.0;
        float separation=max(0.0,(q.z-sum/count)*worldScale.z);
        vec2 width=max(texel*.65,worldScale.xy*sunRadius*separation);
        width=min(width,vec2(.03));
        float soft=0.0;
        for (int i=0;i<16;++i)
            soft+=texture(shadowDepth,vec4(q.xy+disk[i]*width,float(layer),q.z-bias));
        return soft/16.0;
    }
    float visibility = 0.0;
    int radius = shadowPCF ? 1 : 0;
    // Filtering the comparison results (hardware PCF) keeps fractional texel
    // motion smooth. Interpolating raw depths would create false blockers.
    vec2 center = shadowPCF ? q.xy : (floor(q.xy / texel) + 0.5) * texel;
    for (int x = -radius; x <= radius; ++x)
        for (int y = -radius; y <= radius; ++y) {
            visibility += texture(shadowDepth,
                                  vec4(center + vec2(x,y)*texel, float(layer), q.z - bias));
        }
    return visibility / (shadowPCF ? 9.0 : 1.0);
}

float shadowFarVisibility(vec3 world, vec3 normal, vec3 light) {
    if (!shadowEnabled) return 1.0;
    bool currentInside;
    float current = shadowMapVisibility(world, normal, light, shadowMatrix,
                                        shadowWorldScale, shadowLayer, currentInside);
    // A newly fitted map has priority outside its coverage. The old layer must
    // not leave stale shadows where the current fit has no depth samples.
    if (!currentInside || !shadowTransition || shadowBlend >= 1.0) return current;
    bool previousInside;
    float previous = shadowMapVisibility(world, normal, light, shadowPreviousMatrix,
                                          shadowPreviousWorldScale, shadowPreviousLayer,
                                          previousInside);
    if (!previousInside) return current;
    if (shadowBlend <= 0.0) return previous;
    return mix(previous, current, clamp(shadowBlend, 0.0, 1.0));
}

float shadowVisibility(vec3 world, vec3 normal, vec3 light) {
    return shadowFarVisibility(world, normal, light);
}

uniform bool photoColorEnabled;
uniform vec3 photoWhiteBalance;
uniform int photoColorPreset;
vec3 photoAdjust(vec3 value) {
    if (!photoColorEnabled) return value;
    vec3 c=max(value*photoWhiteBalance,vec3(0.0));
    if (photoColorPreset==1) c*=vec3(1.06,1.0,.9);
    if (photoColorPreset==2) c=mix(vec3(dot(c,vec3(.2126,.7152,.0722))),c,.65);
    return c;
}
vec3 photoAdjustDisplay(vec3 c) {
    if (!photoColorEnabled) return c;
    vec3 linear=mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));
    linear=photoAdjust(linear);
    return mix(linear*12.92,1.055*pow(linear,vec3(1.0/2.4))-.055,step(vec3(.0031308),linear));
}

uniform bool atmosphereEnabled, photoHDREnabled, filmicTone;
uniform sampler2D photoSky;
uniform mat3 photoEnvRotation;
uniform float skyIntensity, celestialDiameter;
uniform int nightSky;
uniform bool moonEmitter;
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
vec3 nightRadiance(vec3 ray, vec3 emitter, float blur) {
    float altitude=max(ray.z,0.0);
    vec3 sky=mix(vec3(.003,.004,.009),vec3(.0007,.0014,.004),sqrt(altitude));
    vec2 coord=vec2((atan(ray.y,ray.x)/6.28318530718+.5)*512.,
                    acos(clamp(ray.z,-1.,1.))/3.14159265359*256.);
    vec2 cell=floor(coord);
    float stars=0.;
    #ifdef SKY_BACKDROP
    if (ray.z>0. && blur<.03) {
        for(int x=-1;x<=1;++x) for(int y=-1;y<=1;++y) {
            vec2 index=cell+vec2(x,y);
            vec3 id=vec3(mod(index.x,512.),clamp(index.y,0.,255.),17.);
            float h=skyHash(id);
            if(h<.975) continue;
            vec2 point=index+vec2(.15+.7*skyHash(id+31.),.15+.7*skyHash(id+57.));
            float az=(point.x/512.-.5)*6.28318530718;
            float polar=point.y/256.*3.14159265359;
            vec3 star=vec3(sin(polar)*cos(az),sin(polar)*sin(az),cos(polar));
            float distance=length(ray-star);
            float width=max(length(fwidth(ray)),.0004);
            stars+=exp(-pow(distance/max(.00065,width*.65),2.))*pow((h-.975)/.025,2.);
        }
    }
    #endif
    sky+=vec3(.8,.88,1.)*stars*.5*smoothstep(0.,.08,altitude);
    if(moonEmitter && emitter.z>0.) {
        float angle=acos(clamp(dot(ray,emitter),-1.,1.));
        float radius=radians(max(celestialDiameter,.1)*.5);
        float edge=max(length(fwidth(ray)),.00012)+blur;
        float disc=1.-smoothstep(radius-edge,radius+edge,angle);
        float textureShade=disc>0. ? .78+.22*skyNoise(ray*600.) : 1.;
        sky+=sunColor*(disc*textureShade*.55+ .012*exp(-angle*18.));
    }
    return sky*skyIntensity;
}
vec3 skyRadiance(vec3 ray, vec3 sun, float blur) {
    if (photoHDREnabled) {
        vec3 r=photoEnvRotation*normalize(ray);
        vec2 coords=vec2(.5+atan(-r.y,r.x)/6.28318530718,acos(clamp(r.z,-1.0,1.0))/3.14159265359);
        return textureLod(photoSky,coords,blur*7.0).rgb*skyIntensity;
    }
    if(nightSky>0) return nightRadiance(ray,sun,blur);
    float altitude=max(ray.z,0.0);
    float daylight=smoothstep(-.08,.5,sun.z);
    vec3 zenith=mix(vec3(.03,.065,.18),vec3(.075,.16,.32),daylight);
    vec3 horizon=mix(vec3(.9,.26,.12),vec3(.64,.48,.30),daylight);
    vec3 sky=mix(horizon,zenith,(1.0-exp(-altitude*22.0)));
    float angle=acos(clamp(dot(ray,sun),-1.0,1.0));
    sky+=sunColor*.6*exp(-angle*4.5)*exp(-altitude*1.3);
    // Angular radius follows the lighting control. Pixel derivatives soften
    // subpixel silhouettes instead of a fixed-resolution hard edge.
    float radius=radians(max(celestialDiameter,.1)*.5);
    float edge=max(length(fwidth(ray))*.65,.00012);
    float disc=1.0-smoothstep(max(0.,radius+blur-edge),radius+blur+edge,angle);
    sky+=sunColor*8.0*disc/(1.0+blur*150.0);
    // Fine cloud structure belongs to sharp sky rays. Rough reflections and
    // aerial haze use the smooth large-scale sky approximation: evaluating
    // unresolved cloud octaves there creates noisy matte surfaces and wastes
    // fragment work. This is an approximation, not a prefiltered GGX cubemap.
    vec3 p=ray/max(.12,ray.z+.22); p.xy*=1.3; p.z*=9.0;
    float footprint=length(fwidth(p));
    if (blur<.06 && altitude>.02 && altitude<.7) {
        float n=0., weight=0.;
        float frequency=1.7, amplitude=.5;
        for(int octave=0;octave<5;++octave) {
            float octaveWeight=1.-smoothstep(.35,1.,footprint*frequency);
            if(octaveWeight>0.) {
                n+=amplitude*octaveWeight*skyNoise(p*frequency);
                weight+=amplitude*octaveWeight;
            }
            frequency*=2.; amplitude*=.5;
        }
        n=weight>0. ? n/weight : .5;
        float cloud=smoothstep(.46,.70,n)*smoothstep(.02,.13,altitude)
                    *(1.-smoothstep(.35,.7,altitude));
        float fade=1.-smoothstep(.025,.06,blur);
        sky=mix(sky,vec3(.40,.24,.17)+sunColor*.12,cloud*.65*fade);
    }
    return sky;
}
vec3 photoOutput(vec3 linearColor) {
    vec3 c=clamp(photoAdjust(linearColor)*exp2(exposureEV),vec3(0.0),vec3(1e10));
    if (filmicTone) c=clamp((c*(2.51*c+.03))/(c*(2.43*c+.59)+.14),0.0,1.0);
    else c=c/(1.0+c);
    return mix(c*12.92,1.055*pow(c,vec3(1.0/2.4))-.055,step(vec3(.0031308),c));
}

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

const vec2 LAB_MATERIAL_ORIGIN = vec2(-18.0, -13.0);
const vec2 LAB_MATERIAL_SIZE = vec2(36.0, 26.0);
const float LAB_TILE_METRES[3] = float[3](1.3, 2.4, 2.0);
vec2 labWeightUV() {
    ivec2 dimensions = textureSize(aoMap, 0);
    vec2 coordinate = clamp((worldPosition.xy - LAB_MATERIAL_ORIGIN) /
                            LAB_MATERIAL_SIZE, vec2(0.0), vec2(1.0));
    return (coordinate * vec2(dimensions - ivec2(1)) + vec2(0.5)) /
           vec2(dimensions);
}
vec3 labWeights() {
    vec3 weights = texture(aoMap, labWeightUV()).rgb;
    float total = dot(weights, vec3(1.0));
    return total > 1e-8 ? weights / total : vec3(1.0, 0.0, 0.0);
}
float labLayerLOD(float tileMetres) {
    vec2 coordinate = worldPosition.xy / tileMetres;
    float footprint = max(length(dFdx(coordinate)), length(dFdy(coordinate))) * 256.0;
    return clamp(log2(max(footprint, 1.0)), 0.0, 8.0);
}
vec2 labAtlasUV(float tileMetres, int layer, float level) {
    float dimension = exp2(8.0 - level);
    return (fract(worldPosition.xy / tileMetres) * (dimension - 1.0) + vec2(0.5) +
            vec2(float(layer * 256), 512.0 - 2.0 * dimension)) / vec2(768.0, 511.0);
}
vec3 labSample(sampler2D image, float tileMetres, int layer, bool colorData) {
    float lod = labLayerLOD(tileMetres);
    vec3 first = texture(image, labAtlasUV(tileMetres, layer, floor(lod))).rgb;
    vec3 second = texture(image, labAtlasUV(tileMetres, layer, ceil(lod))).rgb;
    if (colorData) {
        first = linearize(first);
        second = linearize(second);
    }
    return mix(first, second, fract(lod));
}

vec4 qSampleBase(float tileMetres, int layer, float lod) {
    vec4 a = textureLod(baseMap, labAtlasUV(tileMetres, layer, floor(lod)), 0.0);
    vec4 b = textureLod(baseMap, labAtlasUV(tileMetres, layer, ceil(lod)), 0.0);
    a.rgb = linearize(a.rgb); b.rgb = linearize(b.rgb);
    return mix(a, b, fract(lod));
}
vec3 qSampleData(sampler2D image, float tileMetres, int layer, float lod) {
    vec3 a = textureLod(image, labAtlasUV(tileMetres, layer, floor(lod)), 0.0).rgb;
    vec3 b = textureLod(image, labAtlasUV(tileMetres, layer, ceil(lod)), 0.0).rgb;
    return mix(a, b, fract(lod));
}
vec3 qBlend(vec3 p, vec3 h) {
    vec3 score = p + h;
    vec3 q;

    // Log-domain normalization avoids overflow at high sharpness.
    vec3 logs = 4.0 * log(max(score, vec3(1e-30))) + log(max(p, vec3(1e-30)));
    logs = mix(vec3(-1e20), logs, greaterThan(p, vec3(0.0)));
    q = exp(logs - vec3(max(logs.x, max(logs.y, logs.z)))) * step(vec3(1e-30), p);

    float total = dot(q, vec3(1.0));
    q = total > 1e-20 ? q / total : p;
    return mix(p, q, 0.75);
}

vec3 qColor;
vec3 qNormal;
float qRough;
vec3 qEffective;
void qPrepare() {
    vec3 p = labWeights();
    vec3 h;
    vec3 colors[3];
    vec3 normals[3];
    float roughnesses[3];
    for (int i = 0; i < 3; ++i) {
        // Derivatives must be evaluated before non-uniform layer culling.
        // Atlas GL storage has only level zero; explicit LOD avoids implicit
        // derivatives inside the branch, while manual prefilter LOD is retained.
        float lod = labLayerLOD(LAB_TILE_METRES[i]);
        colors[i] = vec3(0.0); normals[i] = vec3(0.0);
        roughnesses[i] = 0.0; h[i] = 0.0;
        if (p[i] > 0.0) {
            vec4 colorHeight = qSampleBase(LAB_TILE_METRES[i], i, lod);
            colors[i] = colorHeight.rgb;
            h[i] = colorHeight.a;
            normals[i] = qSampleData(normalMap, LAB_TILE_METRES[i], i, lod) * 2.0 - 1.0;
            roughnesses[i] = qSampleData(mrMap, LAB_TILE_METRES[i], i, lod).g;
        }
    }
    qEffective = qBlend(p, h);
    qColor = vec3(0.0); qNormal = vec3(0.0); qRough = 0.0;
    for (int i = 0; i < 3; ++i) {
        qColor += colors[i] * qEffective[i];
        qNormal += normals[i] * qEffective[i];
        qRough += roughnesses[i] * qEffective[i];
    }
    float magnitude = length(qNormal);
    qNormal = magnitude > 1e-8 ? qNormal / magnitude : vec3(0.0, 0.0, 1.0);
}
vec3 labBaseColor() { return qColor; }
vec3 labNormal() { return qNormal; }
float labRoughness() { return qRough; }
vec2 surfaceUV() {
    return hasAO ? worldPosition.xy :
           (photographicGround ? worldPosition.xy*groundScale : uv);
}
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
    vec3 mapNormal = hasAO ? labNormal() :
                     texture(normalMap, surfaceUV()).xyz * 2.0 - 1.0;
    mapNormal.xy *= normalScale;
    return normalize(mat3(t,b,n) * mapNormal);
}
void main() {
    if (hasAO) qPrepare();
#ifdef ANALYTIC_GROUND
    vec4 farPoint = groundInverseViewProjection * vec4(groundNDC, 1.0, 1.0);
    vec3 ray = farPoint.xyz / farPoint.w - eye;
    if (abs(ray.z) < 1e-7) discard;
    float t = (groundHeight - eye.z) / ray.z;
    if (t <= 0.0) discard;
    worldPosition = eye + ray * t;
    vec4 clip = projection * view * vec4(worldPosition, 1.0);
    float depth = clip.z / clip.w * 0.5 + 0.5;
    if (depth < 0.0) discard;
    // Keep real in-range depth for objects, focusing and DoF. The infinite
    // continuation sits at the last depth value before sky, without changing
    // the camera near/far planes or the precision of any authored geometry.
    gl_FragDepth = min(depth, 0.99999994);
#endif
    vec4 base = baseFactor * vertexColor;
    if (hasBase) {
        if (hasAO) {
            base.rgb *= labBaseColor();
        } else {
            vec4 sampled = texture(baseMap, surfaceUV());
            base *= vec4(linearize(sampled.rgb), sampled.a);
        }
    }
    if (alphaMode == 1 && base.a < alphaCutoff) discard;
    float alpha = alphaMode == 2 ? base.a : 1.0;
    if (shadingMode == 1) { fragColor = vec4(srgb(photoAdjust(base.rgb)), alpha); return; }
    if (shadingMode == 2) { fragColor = vec4(0.72,0.83,0.94,alpha); return; }
    float metal = metallicFactor;
    float rough = roughnessFactor;
    if (hasMR) {
        if (hasAO) {
            rough *= labRoughness();
            metal = 0.0;
        } else {
            vec4 mr = texture(mrMap,surfaceUV());
            metal *= mr.b; rough *= mr.g;
        }
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
    // In this fixture hasAO marks Terrain; aoMap stores layer weights, not AO.
    float ao = 1.0;
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
