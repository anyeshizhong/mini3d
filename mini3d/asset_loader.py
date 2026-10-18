"""CPU-only background asset loading for editor-facing asset requests.

The worker owns its cache and never interacts with a live Scene or an OpenGL
context. Decoded image bytes are attached to shared material texture records so
the main thread can upload them without repeating image decoding.
"""
from io import BytesIO
import queue
import threading

from .assets import AssetCache


_STOP = object()


def _texture_slots(asset):
    """Yield texture dictionaries from every mesh in an Asset hierarchy."""
    pending = [asset.root]
    visited = set()
    while pending:
        entity = pending.pop()
        identity = id(entity)
        if identity in visited:
            continue
        visited.add(identity)
        pending.extend(getattr(entity, 'children', ()))

        mesh = getattr(entity, 'model', None)
        material = getattr(mesh, 'material', None) if mesh is not None else None
        if not isinstance(material, dict):
            continue
        textures = material.get('textures', {})
        if isinstance(textures, dict):
            for texture in textures.values():
                if isinstance(texture, dict):
                    yield texture


def _decode_image(encoded):
    # Import lazily so importing this module does not initialize any pygame or
    # display state on the caller's thread.
    import pygame

    surface = pygame.image.load(BytesIO(encoded))
    return (int(surface.get_width()), int(surface.get_height()),
            pygame.image.tostring(surface, 'RGBA', False))


def prepare_asset(path, cache=None):
    """Load an Asset and CPU-decode each distinct embedded texture once.

    The encoded ``texture['image']`` remains untouched. ``_decoded_image`` is
    a ``(width, height, rgba_bytes)`` tuple intended for main-thread upload.
    No scene instance is cloned and no display or GL API is used here.
    """
    cache = AssetCache() if cache is None else cache
    asset = cache.load(path)
    decoded_by_identity = {}
    for texture in _texture_slots(asset):
        encoded = texture['image']
        identity = id(encoded)
        cached = decoded_by_identity.get(identity)
        decoded_is_current = (texture.get('_decoded_source') is encoded and
                              '_decoded_image' in texture)
        if decoded_is_current:
            decoded = texture['_decoded_image']
            decoded_by_identity[identity] = (encoded, decoded)
        elif cached is not None and cached[0] is encoded:
            decoded = cached[1]
            texture['_decoded_image'] = decoded
            texture['_decoded_source'] = encoded
        else:
            decoded = _decode_image(encoded)
            texture['_decoded_image'] = decoded
            texture['_decoded_source'] = encoded
            decoded_by_identity[identity] = (encoded, decoded)
        # Hold a reference to the original bytes while this identity cache is
        # alive, preventing id reuse during this traversal. For a texture that
        # already has current metadata, no dictionary writes are needed.
    return asset


class AssetLoader:
    """Single-daemon-worker request queue with cancelable result delivery.

    ``cache_factory`` and ``prepare_fn`` are injectable for tests. The cache
    factory is invoked on the worker thread and its cache is private to this
    loader. A prepare function accepts ``(path, cache)`` and returns an asset.
    """

    def __init__(self, cache_factory=None, prepare_fn=None):
        self._cache_factory = AssetCache if cache_factory is None else cache_factory
        self._prepare_fn = prepare_fn
        self._requests = queue.Queue()
        self._results = queue.Queue()
        self._lock = threading.Lock()
        self._active = set()
        self._next_id = 1
        self._closed = False
        self._thread = threading.Thread(target=self._run, name='mini3d-asset-loader', daemon=True)
        self._thread.start()

    def submit(self, path):
        """Queue an asset path and return its monotonically increasing ID."""
        with self._lock:
            if self._closed:
                raise RuntimeError('AssetLoader is closed')
            request_id = self._next_id
            self._next_id += 1
            self._active.add(request_id)
            # Enqueue under the same lock used by close(), preserving sentinel
            # ordering even when submit and close race.
            self._requests.put((request_id, path))
            return request_id

    def poll(self):
        """Return the next live ``(request_id, asset, error)`` result, or None."""
        while True:
            try:
                request_id, asset, error = self._results.get_nowait()
            except queue.Empty:
                return None
            with self._lock:
                if self._closed or request_id not in self._active:
                    continue
                self._active.remove(request_id)
                return request_id, asset, error

    def cancel(self, request_id):
        """Suppress a queued or in-flight request's result; return whether live."""
        with self._lock:
            if self._closed or request_id not in self._active:
                return False
            self._active.remove(request_id)
            return True

    def close(self):
        """Suppress pending results and request worker shutdown without joining."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._active.clear()
            self._requests.put(_STOP)

    def _run(self):
        cache = None
        prepare = self._prepare_fn
        while True:
            request = self._requests.get()
            if request is _STOP:
                return
            request_id, path = request
            with self._lock:
                if self._closed:
                    continue
                if request_id not in self._active:
                    continue

            asset, error = None, None
            try:
                if cache is None:
                    cache = self._cache_factory()
                asset = (prepare or prepare_asset)(path, cache)
            except Exception as exc:
                error = exc

            with self._lock:
                if not self._closed and request_id in self._active:
                    self._results.put((request_id, asset, error))
