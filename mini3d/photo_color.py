"""Camera-only linear color adjustment; scene lights and exposure stay intact."""
import math
from numbers import Real
import numpy as np

PRESETS = ('Original', 'Warm', 'Low saturation')


def validate_color(kelvin, preset):
    if (isinstance(kelvin, (bool, np.bool_)) or not isinstance(kelvin, Real)
            or not math.isfinite(kelvin) or not 2000 <= kelvin <= 12000):
        raise ValueError('White balance must be finite and between 2000 and 12000 K')
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ValueError('Color preset must be one of '+str(PRESETS))
    return float(kelvin), preset


def white_balance_gains(kelvin):
    from .atmosphere import sun_color
    validate_color(kelvin, 'Original')
    if kelvin == 6500:
        return np.ones(3)
    gains = sun_color(6500) / np.maximum(sun_color(kelvin), 1e-4)
    return gains / np.dot(gains, [.2126, .7152, .0722])


def adjust_linear(color, kelvin=6500, preset='Original'):
    """CPU reference of the GLSL operation, prior to tone mapping and sRGB."""
    validate_color(kelvin, preset)
    value = np.asarray(color) * white_balance_gains(kelvin)
    if preset == 'Warm': value = value * [1.06, 1., .9]
    if preset == 'Low saturation':
        gray = np.sum(value * [.2126, .7152, .0722], axis=-1, keepdims=True)
        value = gray * .35 + value * .65
    return value


PHOTO_COLOR_GLSL = r'''
uniform bool photoColorEnabled;
uniform vec3 photoWhiteBalance;
uniform int photoColorPreset;
vec3 photoAdjust(vec3 value) {
    if (!photoColorEnabled) return value;
    vec3 c=max(value*photoWhiteBalance,vec3(0.0));
    if (photoColorPreset==1) c*=vec3(1.06,1.0,.9);
    if (photoColorPreset==2) c=mix(vec3(dot(c,vec3(.2126,.7152,.0722))),c,.65);
    return c;
}
vec3 photoAdjustDisplay(vec3 c) {
    if (!photoColorEnabled) return c;
    vec3 linear=mix(c/12.92,pow((c+.055)/1.055,vec3(2.4)),step(vec3(.04045),c));
    linear=photoAdjust(linear);
    return mix(linear*12.92,1.055*pow(linear,vec3(1.0/2.4))-.055,step(vec3(.0031308),linear));
}
'''


def bind_photo_color(program, scene):
    from OpenGL import GL as gl
    settings = getattr(scene, '_photo_color', None)
    kelvin, preset = (6500., 'Original') if settings is None else settings
    enabled = kelvin != 6500 or preset != 'Original'
    loc = lambda name: gl.glGetUniformLocation(program, name)
    gl.glUniform1i(loc('photoColorEnabled'), enabled)
    gl.glUniform3fv(loc('photoWhiteBalance'), 1, np.asarray(white_balance_gains(kelvin), np.float32))
    gl.glUniform1i(loc('photoColorPreset'), PRESETS.index(preset))
