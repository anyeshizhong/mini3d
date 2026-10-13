"""Format-neutral CPU asset templates and cache; no GL ownership."""
from pathlib import Path


class Asset:
    """Loaded template whose instances share mesh and material resources."""
    def __init__(self, path, root, animation_names=None, skin_count=0):
        self.path = str(path) if str(path).startswith('builtin:') else str(Path(path).resolve())
        self.name = Path(path).stem
        self.root = root
        self.animation_names = animation_names or []
        self.skin_count = skin_count

    def instantiate(self):
        instance = self.root.clone()
        instance.asset_path = self.path
        return instance


class AssetCache:
    def __init__(self):
        self._assets = {}

    def load(self, path):
        from .roman_assets import ROMAN_ASSETS, create_roman_asset
        if str(path) in {item['path'] for item in ROMAN_ASSETS}:
            if str(path) not in self._assets:
                self._assets[str(path)] = Asset(str(path), create_roman_asset(path))
            return self._assets[str(path)]
        if str(path) == 'builtin:roman-soldier':
            if str(path) not in self._assets:
                from .roman_soldier import create_roman_soldier
                self._assets[str(path)] = Asset(str(path), create_roman_soldier())
            return self._assets[str(path)]
        if str(path) == 'builtin:ground':
            if str(path) not in self._assets:
                from .placement import create_ground
                self._assets[str(path)] = Asset(str(path), create_ground(10))
            return self._assets[str(path)]
        key = str(Path(path).resolve())
        if key not in self._assets:
            suffix = Path(key).suffix.lower()
            if suffix == '.stl':
                from .stl_loader import load_stl
                self._assets[key] = load_stl(key)
            elif suffix in ('.gltf', '.glb'):
                from .gltf_loader import load_gltf
                self._assets[key] = load_gltf(key)
            else:
                raise ValueError('Unsupported model format: {}. Choose GLB, glTF or STL.'.format(suffix))
        return self._assets[key]


