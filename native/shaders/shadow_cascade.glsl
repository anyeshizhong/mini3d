// Appended to material.frag after the existing far-shadow uniform declarations.
// This replaces shadowVisibility while leaving the far-map uniforms unchanged.
uniform sampler2DShadow shadowNearDepth;
uniform sampler2D shadowNearRaw;
uniform mat4 shadowNearMatrix;
uniform vec3 shadowNearWorldScale;
uniform float shadowNearBias;
uniform bool shadowNearEnabled;
#ifndef ANALYTIC_GROUND
uniform mat4 view;
#endif

bool shadowCoordinateValid(vec3 coordinate) {
    return all(greaterThanEqual(coordinate, vec3(0.0))) &&
           all(lessThanEqual(coordinate, vec3(1.0)));
}

bool projectShadowCoordinate(mat4 lightMatrix, vec3 world, out vec3 coordinate) {
    vec4 projected = lightMatrix * vec4(world, 1.0);
    if (abs(projected.w) < 1e-7) {
        coordinate = vec3(0.0);
        return false;
    }
    coordinate = projected.xyz / projected.w * 0.5 + 0.5;
    return shadowCoordinateValid(coordinate);
}

float sampleShadowMap(in sampler2DShadow compareMap, in sampler2D rawMap,
                      vec3 coordinate, vec3 worldScale, float bias) {
    if (!shadowCoordinateValid(coordinate)) return 1.0;
    vec2 texel = 1.0 / vec2(textureSize(compareMap, 0));

    // Orthographic PCSS: search raw blocker depths, then filter comparisons.
    // Sun radius is angular; blocker distance sets the penumbra in world units.
    if (shadowPCF && sunRadius > 0.0) {
        const vec2 disk[16] = vec2[16](
            vec2(0,0), vec2(-.63,-.47), vec2(.67,.48), vec2(.44,-.77),
            vec2(-.49,.73), vec2(-.89,.14), vec2(.87,-.16), vec2(.15,.93),
            vec2(-.13,-.94), vec2(.29,.26), vec2(-.28,-.23), vec2(-.37,.31),
            vec2(.32,-.34), vec2(.73,-.61), vec2(-.76,-.60), vec2(-.70,.60));
        vec2 search = max(texel, worldScale.xy * sunRadius * coordinate.z * worldScale.z);
        search = min(search, vec2(.03));
        float sum = 0.0;
        float count = 0.0;
        for (int i = 0; i < 16; ++i) {
            float depth = texture(rawMap, coordinate.xy + disk[i] * search).r;
            if (depth < coordinate.z - bias) {
                sum += depth;
                count += 1.0;
            }
        }
        if (count == 0.0) return 1.0;
        float separation = max(0.0, (coordinate.z - sum / count) * worldScale.z);
        vec2 width = max(texel * .65, worldScale.xy * sunRadius * separation);
        width = min(width, vec2(.03));
        float soft = 0.0;
        for (int i = 0; i < 16; ++i)
            soft += texture(compareMap, vec3(coordinate.xy + disk[i] * width,
                                             coordinate.z - bias));
        return soft / 16.0;
    }

    float visibility = 0.0;
    int radius = shadowPCF ? 1 : 0;
    // Comparison filtering preserves fractional-texel motion without turning
    // interpolated raw depths into false blockers.
    vec2 center = shadowPCF ? coordinate.xy
                            : (floor(coordinate.xy / texel) + 0.5) * texel;
    for (int x = -radius; x <= radius; ++x)
        for (int y = -radius; y <= radius; ++y)
            visibility += texture(compareMap,
                                  vec3(center + vec2(x, y) * texel,
                                       coordinate.z - bias));
    return visibility / (shadowPCF ? 9.0 : 1.0);
}

float shadowVisibility(vec3 world, vec3 normal, vec3 light) {
    if (!shadowEnabled) return 1.0;

    vec3 farCoordinate;
    bool farValid = projectShadowCoordinate(shadowMatrix, world, farCoordinate);
    float farBias = shadowBias *
        (1.0 + 4.0 * (1.0 - max(dot(normal, light), 0.0)));
    if (!shadowNearEnabled) {
        return farValid
            ? sampleShadowMap(shadowDepth, shadowRaw, farCoordinate, shadowWorldScale, farBias)
            : 1.0;
    }

    float cameraDepth = -(view * vec4(world, 1.0)).z;
    if (cameraDepth >= 16.0) {
        return farValid
            ? sampleShadowMap(shadowDepth, shadowRaw, farCoordinate, shadowWorldScale, farBias)
            : 1.0;
    }

    vec3 nearCoordinate;
    // The near fit uses stable camera-depth input over roughly 1..18 m; its
    // transition to the far map completes at 16 m as a guard band.
    bool nearValid = projectShadowCoordinate(shadowNearMatrix, world, nearCoordinate);
    if (!nearValid) {
        return farValid
            ? sampleShadowMap(shadowDepth, shadowRaw, farCoordinate, shadowWorldScale, farBias)
            : 1.0;
    }

    float nearBias = shadowNearBias *
        (1.0 + 4.0 * (1.0 - max(dot(normal, light), 0.0)));
    float nearVisibility = sampleShadowMap(shadowNearDepth, shadowNearRaw,
                                           nearCoordinate, shadowNearWorldScale,
                                           nearBias);
    if (cameraDepth < 12.0) return nearVisibility;
    // A valid near result is preferable to a lit seam if only the far
    // projection is out of bounds during the overlap band.
    if (!farValid) return nearVisibility;

    float farVisibility = sampleShadowMap(shadowDepth, shadowRaw, farCoordinate,
                                          shadowWorldScale, farBias);
    float farWeight = smoothstep(12.0, 16.0, cameraDepth);
    return mix(nearVisibility, farVisibility, farWeight);
}
