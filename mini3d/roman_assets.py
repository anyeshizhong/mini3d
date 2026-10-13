"""Small original Roman street kit, in metres and Z-up.

The buildings face -Y and have closed, simplified facades. These are reusable
editor assets, not archaeological reconstructions. Every part of one material
is combined into one immutable Mesh; AssetCache shares those meshes between
ordinary editable scene instances. No textures or external models are needed.
"""
import math
from copy import deepcopy

import numpy as np

from .geometry import make_box
from .scene import Entity, Mesh


ROMAN_ASSETS = (
    dict(path='builtin:roman-road', name='Roman road segment',
         description='6 x 4 m stone road; top surface at Z=0.'),
    dict(path='builtin:roman-sidewalk', name='Roman sidewalk segment',
         description='2 x 4 m raised pavement; height 0.18 m.'),
    dict(path='builtin:roman-shop', name='Roman street shop',
         description='4 x 5 m shop, tiled roof; front faces -Y.'),
    dict(path='builtin:roman-house', name='Roman street house',
         description='4 x 5 m two-storey house; front faces -Y.'),
    dict(path='builtin:roman-column', name='Roman column',
         description='2.8 m stone column with base and capital.'),
    dict(path='builtin:roman-arch', name='Roman street arch',
         description='Open stone gateway across X, 6.4 m clear span.'),
    dict(path='builtin:roman-amphora', name='Roman amphora',
         description='0.7 m terracotta vessel with two handles.'),
)


for _kind in ('shop', 'house'):
    for _palette in ('ochre', 'rose'):
        ROMAN_ASSETS += (dict(path='builtin:roman-' + _kind + '-' + _palette,
            name='Roman ' + _kind + ' (' + _palette + ')',
            description='Shared facade variant; original footprint and editable instance.'),)


def _material(color, roughness=.85):
    return dict(pbrMetallicRoughness=dict(baseColorFactor=[*color, 1.],
                metallicFactor=0., roughnessFactor=roughness))


_MATERIALS = {
    'stone': _material((.58, .51, .39)),
    'paving': _material((.32, .34, .33)),
    'mortar': _material((.105, .105, .095)),
    'plaster': _material((.73, .65, .48)),
    'terracotta': _material((.42, .13, .065)),
    'timber': _material((.12, .065, .027)),
    'shadow': _material((.025, .02, .015)),
}


class _Builder:
    """Collect geometry by material while retaining hard polygon edges."""
    def __init__(self, path):
        self.path = path
        self.parts = {}

    def add(self, vertices, faces, material, tint=1.):
        vertices = np.asarray(vertices, dtype=np.float64)
        faces = np.asarray(faces, dtype=np.uint32).reshape(-1, 3)
        bucket = self.parts.setdefault(material, [[], [], []])
        offset = len(bucket[0])
        bucket[0].extend(vertices.tolist())
        bucket[1].extend((faces + offset).tolist())
        bucket[2].extend([[tint, tint, tint, 1.]] * len(vertices))

    def face(self, points, material, tint=1.):
        self.add(points, [[0, i, i + 1] for i in range(1, len(points) - 1)], material, tint)

    def box(self, center, size, material, tint=1.):
        vertices, faces = make_box(*size)
        self.add(vertices + np.asarray(center), faces, material, tint)

    def lathe(self, profile, material, sectors=16, tint=1., center=(0., 0., 0.)):
        """Smooth surface of revolution; profile contains (radius, height)."""
        vertices = [[r * math.cos(a), r * math.sin(a), z]
                    for r, z in profile
                    for a in np.arange(sectors) * (2 * math.pi / sectors)]
        faces = []
        for row in range(len(profile) - 1):
            for col in range(sectors):
                nxt = (col + 1) % sectors
                a, b = row * sectors + col, row * sectors + nxt
                c, d = a + sectors, b + sectors
                faces.extend(((a, b, d), (a, d, c)))
        self.add(np.asarray(vertices) + np.asarray(center), faces, material, tint)

    def finish(self):
        name = next(item['name'] for item in ROMAN_ASSETS if item['path'] == self.path)
        root = Entity(name=name)
        root.asset_path = self.path
        for material, (vertices, faces, colors) in self.parts.items():
            mat = _MATERIALS[material]
            palette = self.path.rsplit('-', 1)[-1]
            if material == 'plaster' and palette in ('ochre', 'rose'):
                mat = deepcopy(mat)
                mat['pbrMetallicRoughness']['baseColorFactor'] = (
                    [.63, .43, .23, 1.] if palette == 'ochre' else [.64, .39, .32, 1.])
            mesh = Mesh(vertices, faces, material=mat)
            mesh.vertex_colors = np.asarray(colors, dtype=np.float32)
            root.add_child(Entity(mesh, material.title()))
        root.update_transform()
        return root


def _paving(builder, width, length, surface, rows, material):
    """Staggered stones clipped to a repeatable module boundary."""
    row_length = length / rows
    for row in range(rows):
        y0, y1 = -length / 2 + row * row_length, -length / 2 + (row + 1) * row_length
        start = -width / 2 - (.5 if row % 2 == 0 else 0.)
        for col in range(int(width) + 1):
            x0, x1 = max(-width / 2, start + col), min(width / 2, start + col + 1.)
            if x1 <= x0:
                continue
            tint = .87 + .035 * ((row * 11 + col * 7) % 7)
            builder.box(((x0 + x1) / 2, (y0 + y1) / 2, surface - .026),
                        (x1 - x0 - .018, y1 - y0 - .018, .052), material, tint)


def _road(builder):
    builder.box((0., 0., -.085), (6., 4., .07), 'mortar')
    _paving(builder, 6., 4., 0., 5, 'paving')


def _sidewalk(builder):
    builder.box((0., 0., .073), (2., 4., .146), 'stone', .78)
    _paving(builder, 2., 4., .18, 5, 'stone')


def _roof(builder, wall_height):
    # Gable ends remain inside the 4 x 5 metre module footprint.
    ridge, eave = wall_height + .88, wall_height + .10
    for y in (-2.35, 2.35):
        points = [(-1.9, y, wall_height), (1.9, y, wall_height),
                  (1.9, y, ridge - 1.9 * .39 - .12), (0., y, ridge - .12),
                  (-1.9, y, ridge - 1.9 * .39 - .12)]
        builder.face(points if y < 0 else points[::-1], 'plaster')
    for side in (-1, 1):
        x = side * 2.
        points = [(0., -2.5, ridge), (x, -2.5, eave), (x, 2.5, eave), (0., 2.5, ridge)]
        top = points if side > 0 else points[::-1]
        bottom = [(x, y, z - .12) for x, y, z in top]
        # Closed roof slab: both slopes, underside and overhang edges. Keep
        # back-face culling enabled; do not hide missing geometry with doubleSided.
        builder.face(top, 'terracotta')
        builder.face(bottom[::-1], 'terracotta', .78)
        for edge in range(4):
            nxt = (edge + 1) % 4
            builder.face([top[edge], bottom[edge], bottom[nxt], top[nxt]], 'terracotta', .88)
        builder.box((side * 1.95, 0., wall_height + .05), (.1, 5., .12), 'terracotta', .82)
        # Raised imbrex ridges run down the pitch. Each ridge is still part of
        # the single roof draw; subtle color differences suggest tile courses.
        for row in range(14):
            y = -2.43 + row * .374
            for col in range(4):
                x0, x1 = side * col * .5, side * (col + 1) * .5
                z0 = ridge + .018 - abs(x0) * .39
                z1 = ridge + .018 - abs(x1) * .39
                points = [(x0, y - .028, z0), (x1, y - .028, z1),
                          (x1, y, z1 + .036), (x0, y, z0 + .036)]
                builder.face(points if side > 0 else points[::-1], 'terracotta', .92 + .035 * (col % 3))
                points = [(x0, y, z0 + .036), (x1, y, z1 + .036),
                          (x1, y + .028, z1), (x0, y + .028, z0)]
                builder.face(points if side > 0 else points[::-1], 'terracotta', .89 + .035 * (col % 3))
    builder.box((0., 0., ridge + .025), (.12, 5., .065), 'terracotta', 1.07)


def _window(builder, x, z, width=.64, height=.88):
    x += .10 if builder.path.endswith('-ochre') else -.10 if builder.path.endswith('-rose') else 0.
    # Shallow panels deliberately close the facade; there is no fake interior.
    y = -2.378
    builder.box((x, y, z), (width + .13, .065, height + .14), 'stone')
    builder.box((x, y - .043, z), (width, .032, height), 'shadow')
    for side in (-1, 1):
        builder.box((x + side * width * .30, y - .068, z),
                    (width * .34, .04, height), 'timber', 1.14)
    builder.box((x, y - .075, z), (.05, .04, height), 'timber')
    builder.box((x, y - .075, z), (width, .04, .045), 'timber')
    builder.box((x, y - .06, z - height / 2 - .095), (width + .2, .18, .12), 'stone')


def _building(builder, house=False):
    height = 5.8 if house else 3.6
    builder.box((0., 0., height / 2), (3.8, 4.7, height), 'plaster')
    builder.box((0., 0., .38), (3.84, 4.74, .76), 'terracotta', .83)
    builder.box((0., 0., .055), (3.94, 4.88, .11), 'stone', .86)
    builder.box((0., 0., height - .16), (3.96, 4.92, .17), 'stone')
    if house:
        builder.box((0., 0., 3.18), (3.94, 4.86, .13), 'stone', .93)
    # Door/shop opening is a recessed-looking, closed wooden facade panel.
    width = 1.08 if house else 2.56
    builder.box((0., -2.387, 1.27), (width + .20, .08, 2.44), 'stone')
    builder.box((0., -2.435, 1.23), (width, .035, 2.24), 'shadow')
    count = 5 if house else 10
    for i in range(count):
        builder.box((-width / 2 + (i + .5) * width / count, -2.459, 1.23),
                    (width / count - .012, .018, 2.22), 'timber', .89 + (i % 3) * .10)
    for z in (.58, 1.91):
        builder.box((0., -2.477, z), (width, .015, .085), 'timber', .64)
    builder.box((0., -2.39, .07), (width + .26, .22, .14), 'stone')
    if house:
        for x in (-1.12, 1.12):
            _window(builder, x, 4.32)
        _window(builder, -1.28, 1.64, .49, .68)
        _window(builder, 1.28, 1.64, .49, .68)
    else:
        # The beam and sign give the street shop a distinct low silhouette.
        builder.box((0., -2.414, 2.88), (2.96, .13, .27), 'timber', 1.22)
        builder.box((0., -2.494, 2.88), (1.26, .012, .12), 'stone', .80)
    # Side-wall panels keep oblique street views readable without extra assets.
    if house:
        for side in (-1, 1):
            for y in (-.95, 1.05):
                builder.box((side * 1.925, y, 4.26), (.055, .69, .97), 'stone')
                builder.box((side * 1.962, y, 4.26), (.025, .55, .82), 'timber')
    _roof(builder, height)


def _column(builder):
    builder.box((0., 0., .08), (.72, .72, .16), 'stone', .86)
    builder.box((0., 0., .205), (.60, .60, .09), 'stone')
    builder.lathe(((0., .25), (.27, .25), (.27, .31), (.215, .36),
                   (.19, 2.39), (.235, 2.44), (.26, 2.52), (0., 2.52)), 'stone', 20)
    builder.box((0., 0., 2.57), (.58, .58, .10), 'stone', .96)
    builder.box((0., 0., 2.71), (.76, .76, .18), 'stone')


def _arch(builder):
    radius, outer, spring = 3.2, 3.68, 3.0
    for side in (-1, 1):
        builder.box((side * 3.65, 0., .12), (.90, 1.52, .24), 'stone', .83)
        builder.box((side * 3.65, 0., 1.59), (.90, 1.25, 2.70), 'stone')
        builder.box((side * 3.65, 0., 2.98), (.90, 1.43, .22), 'stone', .92)
        for z in (.62, 1.25, 1.88, 2.51):
            builder.box((side * 3.65, -.638, z), (.90, .015, .026), 'mortar')
    sectors = 18
    for i in range(sectors):
        a0, a1 = i * math.pi / sectors + .0016, (i + 1) * math.pi / sectors - .0016
        inner0 = (radius * math.cos(a0), spring + radius * math.sin(a0))
        inner1 = (radius * math.cos(a1), spring + radius * math.sin(a1))
        outer0 = (outer * math.cos(a0), spring + outer * math.sin(a0))
        outer1 = (outer * math.cos(a1), spring + outer * math.sin(a1))
        ring = (inner0, outer0, outer1, inner1)
        front = [(x, -.65, z) for x, z in ring]
        back = [(x, .65, z) for x, z in ring]
        tint = .91 + .025 * (i % 5)
        builder.face(front, 'stone', tint)
        builder.face(back[::-1], 'stone', tint)
        for edge in range(4):
            nxt = (edge + 1) % 4
            builder.face([front[edge], back[edge], back[nxt], front[nxt]], 'stone', tint)
    # Flat spandrel masonry above the curved opening, split into narrow strips.
    for i in range(18):
        x0, x1 = -outer + i * (2 * outer / 18), -outer + (i + 1) * (2 * outer / 18)
        z0 = spring + math.sqrt(max(0., outer * outer - x0 * x0))
        z1 = spring + math.sqrt(max(0., outer * outer - x1 * x1))
        front = [(x0, -.60, z0), (x1, -.60, z1), (x1, -.60, 6.82), (x0, -.60, 6.82)]
        back = [(x, .60, z) for x, _, z in front]
        builder.face(front, 'stone', .82)
        builder.face(back[::-1], 'stone', .82)
    builder.box((0., 0., 6.91), (8.2, 1.55, .22), 'stone')
    builder.box((0., -.795, 6.89), (2.5, .04, .13), 'terracotta', .75)


def _amphora(builder):
    profile = ((0., 0.), (.075, 0.), (.085, .035), (.070, .08),
               (.14, .17), (.225, .32), (.235, .41), (.185, .52),
               (.10, .59), (.084, .645), (.112, .655), (.112, .69),
               (.098, .70), (.073, .69), (.073, .645), (.060, .62))
    builder.lathe(profile, 'terracotta', sectors=20, tint=1.20)
    builder.lathe(((0., .619), (.06, .619)), 'shadow', sectors=20)
    # Elliptical handles in the XZ plane, made from a low-sided tube.
    for side in (-1, 1):
        vertices, faces = [], []
        for i in range(16):
            angle = i * 2 * math.pi / 16
            center = np.array([side * (.218 + .087 * math.cos(angle)), 0., .49 + .132 * math.sin(angle)])
            radial = np.array([side * math.cos(angle), 0., math.sin(angle)])
            for j in range(6):
                tube_angle = j * 2 * math.pi / 6
                vertices.append(center + .019 * (radial * math.cos(tube_angle) +
                                                 np.array([0., 1., 0.]) * math.sin(tube_angle)))
        for i in range(16):
            for j in range(6):
                a, b = i * 6 + j, i * 6 + (j + 1) % 6
                c, d = ((i + 1) % 16) * 6 + j, ((i + 1) % 16) * 6 + (j + 1) % 6
                faces.extend(((a, b, d), (a, d, c)) if side > 0 else ((a, d, b), (a, c, d)))
        builder.add(vertices, faces, 'terracotta', 1.13)


_FACTORIES = {
    'builtin:roman-road': _road,
    'builtin:roman-sidewalk': _sidewalk,
    'builtin:roman-shop': _building,
    'builtin:roman-house': lambda builder: _building(builder, house=True),
    'builtin:roman-column': _column,
    'builtin:roman-arch': _arch,
    'builtin:roman-amphora': _amphora,
}


def create_roman_asset(path):
    """Create a deterministic CPU template; unknown identifiers are rejected."""
    key = str(path)
    base = key.rsplit('-', 1)[0] if key.endswith(('-ochre', '-rose')) else key
    if base not in _FACTORIES or key not in {a['path'] for a in ROMAN_ASSETS}:
        raise ValueError('Unknown Roman street asset: ' + key)
    builder = _Builder(key)
    _FACTORIES[base](builder)
    return builder.finish()
