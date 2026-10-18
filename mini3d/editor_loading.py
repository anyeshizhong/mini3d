"""Interactive asset requests; worker templates commit through main-thread commands."""
from pathlib import Path

from .asset_loader import AssetLoader
from .placement import raycast_surface


class EditorAssetLoading:
    def __init__(self, app):
        self.app = app
        self.loader = AssetLoader()
        self.pending = None
        self.closed = False

    def request(self, command, *args, **kwargs):
        if self.closed:
            return None
        self.cancel()
        app = self.app
        hit = None
        if command == 'import_asset':
            path = str(Path(args[0]).expanduser().resolve())
            index = None
        else:
            index = args[0]
            path = app.assets[index]['path']
            if command == 'drop_asset':
                app.finish_edit()
                app.scene.update()
                hit = raycast_surface(app.scene, app.viewer.camera, args[1], app.viewport_rect,
                                      fallback=app.viewer.controller.target)
        request = self.loader.submit(path)
        self.pending = (request, command, index, hit, args, kwargs, app.scene)
        app.status = 'Loading model: ' + Path(path).name
        return None

    def poll(self):
        result = self.loader.poll()
        if result is None:
            return None
        request, asset, error = result
        pending = self.pending
        if pending is None or request != pending[0]:
            return None
        self.pending = None
        _, command, index, hit, args, kwargs, scene = pending
        app = self.app
        if app.scene is not scene:
            return None
        if error is not None:
            app.status = 'Import failed: ' + str(error)
            return None
        app.cache.adopt(asset)
        try:
            if command == 'drop_asset':
                return app._drop_asset_on_hit(index, hit)
            return getattr(app, command)(*args, **kwargs)
        except Exception as exc:
            app.status = 'Import failed: ' + str(exc)
            return None

    def cancel(self):
        if self.pending is not None:
            self.loader.cancel(self.pending[0])
            self.pending = None
            self.app.status = 'Model loading cancelled'

    def close(self):
        self.cancel()
        self.closed = True
        self.loader.close()
