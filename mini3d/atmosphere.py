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
                 haze=.025, ground_scale=1., ground_z=0.)


def atmosphere_state(scene):
    return {**_DEFAULTS, **getattr(scene, '_atmosphere', {})}


def sun_angles(scene):
    from .lighting import scene_light_direction
    x, y, z = scene_light_direction(scene)
    return dict(azimuth=math.degrees(math.atan2(y, x)),
                elevation=math.degrees(math.asin(np.clip(z, -1, 1))))


def update_atmosphere(scene, enabled=None, ground=None, sun_temperature=None,
                      exposure_ev=None, haze=None, ground_scale=None, ground_z=None,
                      azimuth=None, elevation=None):
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
    values = dict(sun_temperature=sun_temperature, exposure_ev=exposure_ev,
                  haze=haze, ground_scale=ground_scale, ground_z=ground_z,
                  azimuth=azimuth, elevation=elevation)
    limits = dict(sun_temperature=(2000, 12000), exposure_ev=(-10, 10),
                  haze=(0, 1), ground_scale=(.01, 100), ground_z=(-1e6, 1e6),
                  azimuth=(-360, 360), elevation=(-89, 89))
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
                      azimuth=-145, elevation=9, exposure_ev=.25, haze=.025)
    update_lighting(scene, mode='Scene', diffuse=6., ambient=.09)
    update_shadows(scene, enabled=True, resolution=2048, bias=.0003, pcf=True)
    return atmosphere_state(scene)


def _ground_material():
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
        ground_entity.model.material = _ground_material()
    size = 2 * camera.far
    ground_entity.scale = np.array([size, size, 1.])
    ground_entity.pos = np.array([*camera.position[:2], state['ground_z']])
    ground_entity.update_transform()
    clean = copy.copy(scene)
    clean.root_entities = [*scene.root_entities, ground_entity]
    return clean, ground_entity
