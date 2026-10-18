"""Scene pass shared by Arrange, Shot previews and PNG capture.

The target owns the public color/depth attachments. Native owns its internal
MSAA resolve; Python overlays consume the effective camera after that resolve.
Photo preparation and lens effects belong to shot_camera, not to a backend.
"""
import copy


def render_scene(scene, camera, renderer, target, size, samples=1, *, workspace='arrange'):
    from OpenGL import GL as gl
    from .native_renderer import backend_policy, scene_backend, NativeRenderError
    from .render_target import RenderTarget
    from .scene_snapshot import scene_frame

    size = tuple(max(1, int(value)) for value in size)
    samples = RenderTarget.validate_samples(samples)
    _mode, required = backend_policy(workspace)
    with scene_frame(scene):
        native = scene_backend(renderer, workspace)
        reason = None
        # Preserve the diagnostic rasterization mode until native supports it.
        if native is not None and getattr(scene, 'render_mode', 'Lit').lower() == 'wireframe':
            reason = 'Native renderer does not support Wireframe'
            if required:
                raise NativeRenderError(reason)
        elif native is not None:
            target.resize(*size, samples=1)
            renderer.resize(*size)
            if native.render(scene, camera, target, size, samples,
                             workspace=workspace, required=required):
                if workspace == 'arrange':
                    renderer.render_editor_helpers(scene, target.render_camera)
                return
            reason = native.last_reason

        target.resize(*size, samples=samples)
        target.bind()
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glDepthMask(True)
        renderer.resize(*size)
        multisample = bool(gl.glIsEnabled(gl.GL_MULTISAMPLE))
        try:
            gl.glEnable(gl.GL_MULTISAMPLE)
            renderer.render(scene, camera)
            target.resolve()
            target.render_camera = copy.copy(camera)
            renderer.render_stats.update(backend='python-fallback' if reason else 'python',
                                         workspace=workspace, samples=samples,
                                         width=size[0], height=size[1])
            if reason:
                renderer.render_stats['native_fallback_reason'] = reason
        finally:
            if not multisample:
                gl.glDisable(gl.GL_MULTISAMPLE)
