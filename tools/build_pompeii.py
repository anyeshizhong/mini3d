"""An editable Pompeii-inspired district study, not a historical reconstruction.

python -B tools/build_pompeii.py
python -B -m mini3d --scene examples/pompeii/district.json

Only public Mini3DAPI placement/group/transaction calls build the extension.
No generated geometry, renderer hooks, or special scene format are required.
"""
import argparse
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_roman_street import build_scene as build_street


VIEWS = {
    'street': ([1.1, -11, 1.7], [0, 31, 3]),
    'through-arch': ([.5, 15, 1.7], [3, 36, 3]),
    'market': ([11, 32, 1.8], [48, 32, 3]),
    'west-lane': ([-30, 36, 1.8], [-30, 60, 3]),
    'court': ([1, 64.5, 1.8], [-3, 81, 3.5]),
    'east-lane': ([30, 73, 2], [30, 39, 3]),
    'overview': ([105, -80, 112], [0, 36, 0]),
}


def extend_district(api, seed=41):
    """Extend the unmodified example street; one undo restores its 85 roots.

    This is a finite art-directed example recipe. Coordinates describe plots,
    not baked geometry; every building remains a normal independent instance.
    """
    rng = random.Random(seed)
    groups = {}
    buildings = []

    def add(area, asset, name, x, y, z=0., yaw=0., scale=(1., 1., 1.)):
        item = api.spawn('builtin:roman-' + asset, name=area + '_' + name,
                         position=[x, y, z], rotation=[0., 0., yaw],
                         scale=scale, anchor='pivot')
        groups.setdefault(area, []).append(item['entity_id'])
        return item['entity_id']

    def surface(area, name, xmin, xmax, ymin, ymax, raised=False):
        # Tile at native stone scale rather than stretch one road across a plaza.
        width = 2. if raised else 6.
        sideways = raised and xmax - xmin > ymax - ymin
        nx = int(math.ceil((xmax - xmin) / (4. if sideways else width)))
        ny = int(math.ceil((ymax - ymin) / (width if sideways else 4.)))
        dx, dy = (xmax - xmin) / nx, (ymax - ymin) / ny
        for ix in range(nx):
            for iy in range(ny):
                add(area, 'sidewalk' if raised else 'road',
                    '{}_{}_{}'.format(name, ix, iy), xmin + (ix + .5) * dx,
                    ymin + (iy + .5) * dy, yaw=math.pi / 2 if sideways else 0.,
                    scale=(dy / width, dx / 4., 1.) if sideways else (dx / width, dy / 4., 1.))

    def building(area, name, x, y, yaw=0., kind=None, palette=None):
        kind = kind or rng.choice(('shop', 'house', 'house'))
        palette = palette if palette is not None else rng.choice(('', '-ochre', '-rose'))
        sx, sy, sz = rng.uniform(.83, 1.08), rng.uniform(.88, 1.), rng.uniform(.86, 1.18)
        # A low masonry footing closes the gap to the surrounding ground.
        # It is an ordinary shared pavement asset, editable with the building.
        add(area, 'sidewalk', name + '_Footing', x, y, yaw=yaw,
            scale=(2. * sx, 1.25 * sy, 1.))
        ident = add(area, kind + palette, name, x, y, .18, yaw, (sx, sy, sz))
        buildings.append(ident)
        return ident

    with api.transaction('Expand Pompeii district'):
        # Retain the original street and buildings, but subdivide its stretched
        # square into native-scale paving. Undo restores the original square.
        for item in api.list_entities():
            if item['name'].endswith('_Small_Square'):
                api.delete(item['entity_id'])
        surface('Junction', 'Square', -10, 10, 28, 36)

        # Main cross street: market east, quieter residential frontage west.
        for area, a, b in (('Market', 10, 54), ('West', -46, -10)):
            surface(area, 'Road', a, b, 29, 35)
            surface(area, 'SouthWalk', a, b, 27, 29, True)
            # Open the northern sidewalk where the residential lanes join.
            lane = 30 if area == 'Market' else -30
            surface(area, 'NorthWalkA', a, lane - 4, 35, 37, True)
            surface(area, 'NorthWalkB', lane + 4, b, 35, 37, True)
        for i, x in enumerate((13, 18, 23, 28, 33, 38, 43, 48, 52.5)):
            building('Market', 'SouthShop_%02d' % i, x, 24.4 + rng.uniform(-.35, .1),
                     math.pi, 'shop' if i % 3 else 'house')
            if i % 2 == 0:
                add('Market', 'amphora', 'Stock_%02d' % i, x + .8, 27.6, .18,
                    scale=(1.2, 1.2, 1.2))
        for i, x in enumerate((13, 18, 23, 37, 42, 47, 52)):
            building('Market', 'NorthFront_%02d' % i, x, 39.5 + rng.uniform(0, .5),
                     kind='house' if i % 3 else 'shop')
            add('Market', 'column', 'Portico_%02d' % i, x, 35.6, .18,
                scale=(1., 1., .96 + .03 * (i % 3)))
        for i, x in enumerate((-43, -38, -33, -28, -22.5, -17, -12.5)):
            building('West', 'South_%02d' % i, x, 24.3 - rng.uniform(0, .7), math.pi)
        for i, x in enumerate((-43, -38, -22, -17, -12.5)):
            building('West', 'North_%02d' % i, x, 39.7 + rng.uniform(0, .8))

        # Two lanes of unequal length connect a cross lane and the court.
        # All intersections are disjoint rectangles: no coplanar road overlaps.
        for area, x in (('WestLane', -30), ('EastLane', 30)):
            surface(area, 'Road', x - 2, x + 2, 35, 60)
            surface(area, 'LeftWalk', x - 4, x - 2, 37, 58, True)
            surface(area, 'RightWalk', x + 2, x + 4, 37, 58, True)
            for i, y in enumerate((46, 51, 55.5)):
                for side in (-1, 1):
                    building(area, 'Home_%d_%d' % (i, side), x + side * 6.6,
                             y + (.35 if side > 0 else -.25), -side * math.pi / 2,
                             kind='house' if area == 'WestLane' else None)
            add(area, 'amphora', 'CornerVessel', x + 3, 43, .18)
        surface('CrossLane', 'Road', -32, 32, 60, 64)
        surface('CrossLane', 'SouthWalk', -26, 26, 58, 60, True)
        for a, b in ((-26, -6), (6, 26)):
            surface('CrossLane', 'NorthWalk', a, b, 64, 66, True)
        for i, x in enumerate((-16, -10, -4, 3, 10, 16)):
            building('CrossLane', 'SouthFront_%02d' % i, x, 55.4, math.pi,
                     kind='shop' if i in (1, 4) else 'house')

        # Broad open court, low shop edge to the west and taller eastern homes.
        surface('Court', 'Entrance', -6, 6, 64, 66)
        surface('Court', 'Paving', -18, 18, 66, 82)
        for i, x in enumerate((-15, -10, -5, 0, 5, 10, 15)):
            building('Court', 'North_%02d' % i, x, 84.6 + (.4 if i % 3 == 0 else 0),
                     kind='house' if i in (0, 3, 6) else 'shop', palette='-ochre' if i % 2 else '')
            add('Court', 'column', 'NorthColumn_%02d' % i, x, 80.7, 0.)
        for i, y in enumerate((68.5, 74, 79.5)):
            building('Court', 'WestShop_%02d' % i, -20.5, y, math.pi / 2, 'shop', '-rose')
            building('Court', 'EastHome_%02d' % i, 20.5, y + .2, -math.pi / 2, 'house', '')
            add('Court', 'column', 'WestColumn_%02d' % i, -16.8, y, 0.)
        surface('EastLane', 'UpperRoad', 28, 32, 64, 82)
        surface('EastLane', 'UpperWalk', 32, 34, 64, 82, True)
        for i, y in enumerate((68, 74, 79)):
            building('EastLane', 'UpperHome_%02d' % i, 36.6, y, -math.pi / 2)

        # Footings for the retained street houses also meet the lowered backdrop.
        for item in api.list_entities():
            if item['name'].startswith('Roman_Street_') and any(
                    word in item['asset_path'] for word in ('roman-house', 'roman-shop')):
                x, y, _ = item['position']; sx, sy, _ = item['scale']
                add('Junction', 'sidewalk', item['name'] + '_Footing', x, y,
                    yaw=item['rotation'][2], scale=(2 * sx, 1.25 * sy, 1.))
        for name, ids in groups.items():
            api.create_group(ids, name='Pompeii_' + name)
        api.create_group([ident for ids in groups.values() for ident in ids], name='Pompeii_Extension')
    api.select_entities([])
    return dict(added_buildings=len(buildings), districts=list(groups), seed=seed)


def build_scene(api):
    original = build_street(api)
    summary = extend_district(api)
    # Below the mortar bed (-.12), never across the stone tops at zero.
    api.set_atmosphere(ground=True, ground_z=-.14, haze=.0015)
    api.set_shadows(resolution=2048)
    api.set_editor_camera(position=[100, -78, 108], target=[0, 36, 0], fov_y=48)
    api.create_shot_camera(position=VIEWS['market'][0], target=VIEWS['market'][1],
                           focal_mm=24, near=.05, far=300)
    entities = api.list_entities()
    summary.update(original_entities=original['entity_count'], entity_count=len(entities),
        building_count=sum(any(s in item['asset_path'] for s in ('roman-house', 'roman-shop'))
                           for item in entities))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'examples/pompeii/district.json')
    args = parser.parse_args()
    from mini3d.api import Mini3DAPI
    api = Mini3DAPI()
    result = build_scene(api)
    api.save_scene(args.output)
    print(result)
    print(args.output)


if __name__ == '__main__':
    main()
