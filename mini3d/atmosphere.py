"""Photographic sky, warm directional sun and camera-following textured ground.

CPU settings have no GL ownership. The ground covers the complete clipping
volume and repeats in WORLD coordinates, so camera movement never exposes an
edge or swims the texture. It is a render-only receiver, not a placement object.
"""
import copy
import io
import math
from numbers import Real

import numpy as np

_DEFAULTS = dict(enabled=False, ground=False, sun_temperature=3500., exposure_ev=0.,
                 haze=.025, ground_scale=1., ground_z=0., sky_texture="procedural",
                 sky_intensity=1., ground_texture="procedural", sun_size=0., tone_mapping="reinhard", celestial_body="sun")


PROCEDURAL_SKIES = ("procedural", "stars", "moonlit")


def atmosphere_state(scene):
    return {**_DEFAULTS, **getattr(scene, '_atmosphere', {})}


def sun_angles(scene):
    from .lighting import scene_light_direction
    x, y, z = scene_light_direction(scene)
    return dict(azimuth=math.degrees(math.atan2(y, x)),
                elevation=math.degrees(math.asin(np.clip(z, -1, 1))))


def update_atmosphere(scene, enabled=None, ground=None, sun_temperature=None,
                      exposure_ev=None, haze=None, ground_scale=None, ground_z=None,
                      azimuth=None, elevation=None, sky_texture=None, sky_intensity=None,
                      ground_texture=None, sun_size=None, tone_mapping=None, celestial_body=None):
    """Validate the complete update before changing settings or sun direction.

    Temperature is an artistic black-body approximation, EV is a real linear
    exposure multiplier (2**EV), and angles are Z-up surface-to-sun degrees.
    Enabling a sky does not replace the user's light strengths or direction.
    """
    state = atmosphere_state(scene)
    for key, value in (('enabled', enabled), ('ground', ground)):
        if value is not None:
            if type(value) is not bool:
                raise ValueError(key + ' must be a boolean')
            state[key] = value
    for key, value, choices in (('ground_texture', ground_texture, ('procedural','gravel')),
            ('celestial_body', celestial_body, ('sun','moon')),
            ('tone_mapping', tone_mapping, ('reinhard','filmic'))):
        if value is not None:
            if not isinstance(value,str) or value not in choices:
                raise ValueError(key+' must be one of '+str(choices))
            state[key]=value
    if sky_texture is not None:
        if not isinstance(sky_texture,str) or not sky_texture or len(sky_texture)>4096:
            raise ValueError('sky_texture must be procedural, stars, moonlit, sunset, or a Radiance HDR path')
        if sky_texture not in PROCEDURAL_SKIES + ('sunset',):
            from .photo_environment import sky_path
            sky_texture=str(sky_path(sky_texture))
        if sky_texture not in PROCEDURAL_SKIES:
            from .photo_environment import load_sky
            load_sky(sky_texture) # Validate bytes before changing any live state.
        state['sky_texture']=sky_texture
    values = dict(sky_intensity=sky_intensity, sun_size=sun_size, sun_temperature=sun_temperature, exposure_ev=exposure_ev,
                  haze=haze, ground_scale=ground_scale, ground_z=ground_z,
                  azimuth=azimuth, elevation=elevation)
    limits = dict(sky_intensity=(0,20), sun_size=(0,3), sun_temperature=(2000, 12000), exposure_ev=(-10, 10),
                  haze=(0, 1), ground_scale=(.01, 100), ground_z=(-1e6, 1e6),
                  azimuth=(-360, 360), elevation=(-90, 90))
    for key, value in values.items():
        if value is None:
            continue
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                or not math.isfinite(value) or not limits[key][0] <= value <= limits[key][1]):
            raise ValueError(key + ' must be finite and in ' + str(limits[key]))
        if key in state:
            state[key] = float(value)
    direction = None
    if azimuth is not None or elevation is not None:
        angles = sun_angles(scene)
        a = math.radians(angles['azimuth'] if azimuth is None else azimuth)
        e = math.radians(angles['elevation'] if elevation is None else elevation)
        direction = np.array([math.cos(e)*math.cos(a), math.cos(e)*math.sin(a), math.sin(e)])
    scene._atmosphere = state
    if direction is not None:
        scene.light_dir = direction
    return atmosphere_state(scene)


def sun_color(kelvin):
    """Approximate black-body chromaticity, normalized linear RGB, not a filter."""
    t = float(kelvin) / 100
    rgb = [255 if t <= 66 else 329.698727446 * (t-60)**-.1332047592,
           99.4708025861*math.log(t)-161.1195681661 if t <= 66 else
           288.1221695283*(t-60)**-.0755148492,
           255 if t >= 66 else 0 if t <= 19 else 138.5177312231*math.log(t-10)-305.0447927307]
    c = np.clip(rgb, 0, 255) / 255
    return np.where(c <= .04045, c/12.92, ((c+.055)/1.055)**2.4)


def sunset_preset(scene):
    from .lighting import update_lighting, update_shadows
    update_atmosphere(scene, enabled=True, ground=True, sun_temperature=3500,
                      azimuth=-145, elevation=9, exposure_ev=.25, haze=.025, sky_texture="procedural", ground_texture="procedural",
                      sun_size=0., tone_mapping="reinhard", celestial_body="sun")
    update_lighting(scene, mode='Scene', diffuse=6., ambient=.09)
    update_shadows(scene, enabled=True, resolution=2048, bias=.0003, pcf=True)
    return atmosphere_state(scene)


def direct_light_strength(scene):
    """Suppress a below-horizon celestial emitter without changing stored intensity."""
    state = atmosphere_state(scene)
    if state['enabled']:
        from .lighting import scene_light_direction
        z = float(scene_light_direction(scene)[2])
        # Fade over the last half degree above the horizon; no underground sunlight.
        return float(scene.diffuse) * min(1., max(0., z / .0087265355))
    return float(scene.diffuse)


def sky_preset(scene, name):
    """One active directional emitter; artistic presets, no astronomical simulation."""
    if name not in ('day', 'sunset', 'stars', 'moonlit'):
        raise ValueError('Choose day, sunset, stars or moonlit')
    if name == 'sunset':
        # Sky selection must not place a coplanar photography floor over an
        # authored road. Keep the full photography preset as a separate API.
        previous = atmosphere_state(scene)
        sunset_preset(scene)
        return update_atmosphere(scene, **{key: previous[key] for key in
            ('ground', 'ground_z', 'ground_texture', 'ground_scale')})
    from .lighting import update_lighting, update_shadows
    night = name in ('stars', 'moonlit')
    moon = name == 'moonlit'
    update_atmosphere(scene, enabled=True, sky_texture=name if night else 'procedural',
        celestial_body='moon' if moon else 'sun', sun_temperature=8500 if moon else 5500,
        azimuth=-90, elevation=35 if moon else -30 if night else 40,
        sky_intensity=1., exposure_ev=0., haze=.002 if night else .005,
        sun_size=.53 if moon else 0., tone_mapping='filmic')
    update_lighting(scene, mode='Scene', diffuse=.7 if moon else 0. if night else 3.,
                    ambient=.025 if night else .25)
    update_shadows(scene, enabled=True)
    return atmosphere_state(scene)


from functools import lru_cache

@lru_cache(maxsize=2)
def _ground_material(source="procedural"):
    if source=="gravel":
        from .photo_environment import RESOURCES
        arm=dict(image=(RESOURCES/"gravel_arm.png").read_bytes())
        return dict(pbrMetallicRoughness=dict(baseColorFactor=[1,1,1,1],metallicFactor=0.,roughnessFactor=1.),
            doubleSided=True,extras=dict(photographicGround=True),normalTexture=dict(scale=.7),
            textures=dict(baseColor=dict(image=(RESOURCES/"gravel_color.jpg").read_bytes()),
                normal=dict(image=(RESOURCES/"gravel_normal.png").read_bytes()),
                metallicRoughness=arm,occlusion=arm))
    # Deterministic tileable stone/sand maps. No external assets or downloads.
    import pygame
    rng = np.random.default_rng(1701)
    size = 512
    y, x = np.mgrid[:size, :size] / size
    height = (.025*np.sin(2*np.pi*x*11)*np.cos(2*np.pi*y*13) +
              .018*np.cos(2*np.pi*(x*3+y*7)) + rng.normal(0, .012, (size, size)))
    grain = rng.normal(0, .017, (size, size))
    tone = .58 + height + grain
    pixels = np.clip(tone[:,:,None] * np.array([1., .85, .65])*255, 0, 255).astype('uint8')
    dx = (np.roll(height, -1, 1)-np.roll(height, 1, 1))*2
    dy = (np.roll(height, -1, 0)-np.roll(height, 1, 0))*2
    normal = np.dstack((-dx, -dy, np.ones_like(dx)))
    normal /= np.linalg.norm(normal, axis=2, keepdims=True)
    def encode(array):
        surface = pygame.image.fromstring(array.tobytes(), (size, size), 'RGB')
        output = io.BytesIO(); pygame.image.save(surface, output, 'tile.png')
        return dict(image=output.getvalue())
    return dict(pbrMetallicRoughness=dict(baseColorFactor=[1,1,1,1],
                metallicFactor=0., roughnessFactor=.92), doubleSided=True,
                extras=dict(photographicGround=True), normalTexture=dict(scale=.35),
                textures=dict(baseColor=encode(pixels),
                              normal=encode(np.clip((normal*.5+.5)*255,0,255).astype('uint8'))))


def prepare_photographic_scene(scene, camera, ground_entity=None):
    """Borrow the scene, inject one bounded receiver without editing its roots."""
    state = atmosphere_state(scene)
    if not state['ground']:
        return scene, ground_entity
    if ground_entity is None:
        from .placement import create_ground
        ground_entity = create_ground(2)
        ground_entity.name = 'Photographic Ground (render-only)'
        ground_entity.model.material = _ground_material(state["ground_texture"])
    if getattr(ground_entity,"_ground_source",None)!=state["ground_texture"]:
        ground_entity.model.material=_ground_material(state["ground_texture"])
        ground_entity._ground_source=state["ground_texture"]
    size = 2 * camera.far
    ground_entity.scale = np.array([size, size, 1.])
    ground_entity.pos = np.array([*camera.position[:2], state['ground_z']])
    ground_entity.update_transform()
    clean = copy.copy(scene)
    clean.root_entities = [*scene.root_entities, ground_entity]
    clean._render_base_scene = scene
    clean._render_extra_entities = [ground_entity]
    return clean, ground_entity
