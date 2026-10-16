import tempfile
from pathlib import Path
import unittest
import numpy as np
from mini3d.api import Mini3DAPI
from mini3d.placement import geometry_bounds
from tools.build_pompeii import build_scene, extend_district
from tools.build_roman_street import build_scene as build_street


class PompeiiTests(unittest.TestCase):
    def api(self):
        api = Mini3DAPI()
        self.addCleanup(api._app.model_dialog.close)
        return api

    def test_scale_shared_assets_roundtrip_and_independent_edit(self):
        api = self.api(); report = build_scene(api)
        self.assertGreaterEqual(report['entity_count'], 85 * 3)
        self.assertGreaterEqual(report['building_count'], 23 * 3)
        roots = api._app.scene.root_entities
        models = [n.model for n in api._app.scene.get_flat_render_list() if n.model is not None]
        self.assertLessEqual(len({id(m) for m in models}), 39)
        self.assertLess(api.get_atmosphere()['ground_z'], -.12)
        buildings = [r for r in roots if 'roman-house' in r.asset_path or 'roman-shop' in r.asset_path]
        self.assertGreater(len({tuple(np.round(r.scale, 3)) for r in buildings}), 50)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'district.json'; api.save_scene(path)
            fresh = self.api(); fresh.load_scene(path)
            self.assertEqual(api.list_entities(), fresh.list_entities())
            self.assertEqual(api.list_groups(), fresh.list_groups())
            self.assertEqual(api.get_atmosphere(), fresh.get_atmosphere())
        before = api.list_entities()
        api.set_transform(buildings[-1].entity_id, position=[90, 90, 0])
        api.undo(); self.assertEqual(before, api.list_entities())

    def test_extension_undo_redo_and_clear_connected_walkways(self):
        api = self.api(); build_street(api)
        before, groups = api.list_entities(), api.list_groups()
        count = api.get_scene_state()['history']['undo_count']
        extend_district(api)
        after = api.list_entities()
        self.assertEqual(api.get_scene_state()['history']['undo_count'], count + 1)
        api.undo(); self.assertEqual(before, api.list_entities()); self.assertEqual(groups, api.list_groups())
        api.redo(); self.assertEqual(after, api.list_entities())
        bounds = [geometry_bounds(r) for r in api._app.scene.root_entities
                  if 'roman-house' in r.asset_path or 'roman-shop' in r.asset_path]
        # Sample the full connected route, not only the photograph endpoints.
        route = [(0,-10), (0,32), (30,32), (30,62), (-30,62), (-30,32),
                 (-44,32), (0,32), (30,32), (30,62), (0,62), (0,76)]
        for a, b in zip(route, route[1:]):
            for p in np.linspace(a, b, 80):
                for lo, hi in bounds:
                    self.assertFalse(np.all(p > lo[:2] - .35) and np.all(p < hi[:2] + .35),
                                     'Blocked walk route at ' + str(p))
        # Roof footprints of newly placed buildings must not intersect.
        homes = [r for r in api._app.scene.root_entities if not r.name.startswith('Roman_Street_')
                 and ('roman-house' in r.asset_path or 'roman-shop' in r.asset_path)]
        all_homes = [r for r in api._app.scene.root_entities
                     if 'roman-house' in r.asset_path or 'roman-shop' in r.asset_path]
        for a in homes:
            alo, ahi = geometry_bounds(a)
            for b in all_homes:
                if a is b: continue
                blo, bhi = geometry_bounds(b)
                self.assertFalse(np.all(np.minimum(ahi[:2], bhi[:2]) - np.maximum(alo[:2], blo[:2]) > .01),
                                 'Overlapping roofs: ' + a.name + ', ' + b.name)

    def test_sky_presets_preserve_authored_ground_and_legacy_photo_preset(self):
        api = self.api()
        keys = ('ground', 'ground_z', 'ground_scale', 'ground_texture')
        for ground in (False, True):
            api.set_atmosphere(ground=ground, ground_z=-.14, ground_scale=.4, ground_texture='gravel')
            before = api.get_atmosphere()
            for preset in ('sunset', 'day', 'stars', 'moonlit'):
                api.sky_preset(preset)
                self.assertEqual({k: api.get_atmosphere()[k] for k in keys}, {k: before[k] for k in keys})
        api.set_atmosphere(ground=False)
        api.sunset_preset()
        self.assertTrue(api.get_atmosphere()['ground'])


if __name__ == '__main__':
    unittest.main()
