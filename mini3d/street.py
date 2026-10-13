"""A finite Roman street assembled from ordinary, shared built-in assets.

The layout uses metres, Z up, and a local +Y street axis. Each four-metre
segment remains a collection of editable scene roots; groups are membership
sets, not a second scene hierarchy or a persistent procedural generator.
"""
from numbers import Integral, Real

import numpy as np


STREET_ASSETS = tuple('builtin:roman-' + name for name in
                      ('road', 'sidewalk', 'shop', 'house', 'column', 'amphora', 'arch'))
SEGMENT_LENGTH = 4.0


def _finite_number(value, label):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
            or not np.isfinite(value)):
        raise ValueError(label + ' must be a finite number')
    return float(value)


def _parameters(segments, road_width, origin, facing):
    if (isinstance(segments, (bool, np.bool_)) or not isinstance(segments, Integral)
            or not 2 <= segments <= 12):
        raise ValueError('segments must be an integer from 2 to 12')
    width = _finite_number(road_width, 'road_width')
    if not 4.0 <= width <= 10.0:
        raise ValueError('road_width must be from 4 to 10 metres')
    yaw = _finite_number(facing, 'facing')
    try:
        point = np.asarray([0., 0., 0.] if origin is None else origin)
        if point.shape != (3,) or point.dtype.kind not in 'fiu':
            raise ValueError('origin must contain three finite numbers')
        point = point.astype(np.float64)
    except (TypeError, OverflowError) as exc:
        raise ValueError('origin must contain three finite numbers') from exc
    if not np.all(np.isfinite(point)):
        raise ValueError('origin must contain three finite numbers')
    return int(segments), width, point, yaw


def _layout(segments, width, origin, facing, variation=False, seed=0, extension_segments=0):
    rng = np.random.RandomState(seed)
    cosine, sine = np.cos(facing), np.sin(facing)
    basis = np.array([[cosine, -sine, 0.], [sine, cosine, 0.], [0., 0., 1.]])
    plan = []

    def add(category, asset, label, position, yaw=0., scale=(1., 1., 1.)):
        with np.errstate(over='ignore', invalid='ignore'):
            point = origin + basis @ np.asarray(position)
            rotation = np.array([0., 0., facing + yaw])
        # Rendering ultimately uploads float32 matrices. Reject unrepresentable
        # locations before loading assets or adding any scene roots.
        if (not np.all(np.isfinite(point)) or not np.all(np.isfinite(rotation))
                or np.any(np.abs(point) > np.finfo(np.float32).max / 2)):
            raise ValueError('Street transforms exceed the finite rendering range')
        plan.append((category, 'builtin:roman-' + asset, label, point, rotation, scale))

    for index in range(segments + extension_segments):
        y = (index - (segments - 1) / 2.) * SEGMENT_LENGTH
        number = index + 1
        add('roads', 'road', 'Road_{:02d}'.format(number), (0., y, 0.),
            scale=(width / 6., 1., 1.))
        for side, sign in (('Left', -1.), ('Right', 1.)):
            add('roads', 'sidewalk', '{}_Sidewalk_{:02d}'.format(side, number),
                (sign * (width / 2. + 1.), y, 0.))
            building = 'shop' if index % 2 == 0 else 'house'
            sx, sz, setback = 1., 1., 0.
            if variation:
                building = ('shop', 'house')[rng.randint(2)]
                building += ('', '-ochre', '-rose')[rng.randint(3)]
                sx, sz, setback = rng.uniform(.86, 1.), rng.uniform(.84, 1.16), rng.uniform(0., .35)
            add('buildings', building, '{}_{}_{:02d}'.format(side, building.title(), number),
                (sign * (width / 2. + 4.5 + setback), y, .18), yaw=-sign * np.pi / 2.,
                scale=(sx, 1., sz))
            add('details', 'column', '{}_Column_{:02d}'.format(side, number),
                (sign * (width / 2. + .45), y + (rng.uniform(.8, 1.4) if variation else 1.25), .18))
        # Alternate small props along the sidewalks, outside the road corridor.
        side = -1. if index % 2 == 0 else 1.
        add('details', 'amphora', 'Amphora_{:02d}'.format(number),
            (side * (width / 2. + 1.4), y - .8, .18))
    add('details', 'arch', 'Street_Arch', (0., segments * 2. + .5, 0.),
        scale=(width / 6., 1., 1.))
    if extension_segments:
        end = segments * 2. + extension_segments * 4.
        add('roads', 'road', 'Small_Square', (0., end + 4., 0.), scale=((width + 14.) / 6., 2., 1.))
        for index, x in enumerate((-6., 0., 6.)):
            add('buildings', 'house-ochre' if variation else 'house',
                'Square_House_' + str(index + 1), (x, end + 10.5, 0.))
    return plan


def create_roman_street(commands, segments=6, road_width=6.0, origin=None, facing=0.0,
                        variation=False, seed=0, extension_segments=0):
    """Append/select a bounded street in one undoable placement transaction.

    No camera, workspace, lighting, existing instances, or save format is
    changed. All parameters, transforms and asset availability are checked
    before mutation. The returned summary contains only JSON-safe values.
    """
    if commands.active_transaction:
        raise ValueError('Roman Street requires a completed placement transaction')
    segments, width, origin, facing = _parameters(segments, road_width, origin, facing)
    if type(variation) is not bool:
        raise ValueError('variation must be a boolean')
    for label, value, limit in (('seed', seed, 2147483647), ('extension_segments', extension_segments, 6)):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or not 0 <= value <= limit:
            raise ValueError(label + ' must be an integer from 0 to ' + str(limit))
    plan = _layout(segments, width, origin, facing, variation, int(seed), extension_segments)
    for asset in sorted({item[1] for item in plan}):
        commands.cache.load(asset)
    used_names = {group.name for group in commands.scene.groups}
    number = 1
    while 'Roman_Street_{:03d}'.format(number) in used_names:
        number += 1
    name = 'Roman_Street_{:03d}'.format(number)
    categories = {'roads': [], 'buildings': [], 'details': []}
    member_ids = []
    with commands.transaction('Roman Street'):
        for category, asset, label, position, rotation, scale in plan:
            entity = commands.spawn(asset, name=name + '_' + label, position=position,
                                    rotation=rotation, scale=scale, anchor='pivot')
            member_ids.append(entity.entity_id)
            categories[category].append(entity.entity_id)
        group = commands.create_group(member_ids, name=name)
        groups = {category: commands.create_group(ids, name=name + '_' + category.title()).group_id
                  for category, ids in categories.items()}
        commands.set_selection(member_ids, primary_id=member_ids[0], group_id=group.group_id)
    return dict(group_id=group.group_id, member_ids=member_ids, groups=groups,
                entity_count=len(member_ids), segments=segments,
                length=segments * SEGMENT_LENGTH, width=width,
                origin=origin.tolist(), facing=facing, variation=variation, seed=int(seed),
                extension_segments=int(extension_segments), total_length=(segments + extension_segments) * SEGMENT_LENGTH)
