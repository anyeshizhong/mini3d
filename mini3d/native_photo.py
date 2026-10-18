"""Compatibility imports for the shared Arrange/Shot native scene renderer."""
from .native_renderer import (
    NativeRenderError as NativePhotoError,
    NativeSceneRenderer as NativePhotoRenderer,
    preserved_native_state,
    scene_backend,
)


def photo_backend(renderer):
    return scene_backend(renderer, 'shot')
