#include "shadow_fit.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace {

using V3 = std::array<double, 3>;
using V4 = std::array<double, 4>;
using M3 = std::array<double, 9>;
using M4 = std::array<double, 16>;
using Corners = std::array<V3, 8>;
using Planes = std::array<V4, 6>;

constexpr int kSigns[8][3] = {
    {-1, -1, -1}, {-1, -1, 1}, {-1, 1, -1}, {-1, 1, 1},
    {1, -1, -1}, {1, -1, 1}, {1, 1, -1}, {1, 1, 1}};

constexpr int kEdges[12][2] = {
    {0, 1}, {0, 2}, {0, 4}, {1, 3}, {1, 5}, {2, 3},
    {2, 6}, {3, 7}, {4, 5}, {4, 6}, {5, 7}, {6, 7}};

bool finite(double value) { return std::isfinite(value); }

V3 add(const V3& a, const V3& b) {
    return {a[0] + b[0], a[1] + b[1], a[2] + b[2]};
}

V3 sub(const V3& a, const V3& b) {
    return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}

V3 mul(const V3& a, double s) {
    return {a[0] * s, a[1] * s, a[2] * s};
}

double dot(const V3& a, const V3& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

V3 cross(const V3& a, const V3& b) {
    return {a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]};
}

double norm(const V3& a) { return std::sqrt(dot(a, a)); }

V3 normalize(const V3& a) {
    const double n = norm(a);
    if (!(n > 0.0) || !finite(n)) throw std::domain_error("zero or invalid vector");
    return mul(a, 1.0 / n);
}

bool finite(const V3& a) {
    return finite(a[0]) && finite(a[1]) && finite(a[2]);
}

bool finite(const M4& a) {
    return std::all_of(a.begin(), a.end(), [](double v) { return finite(v); });
}

M4 multiply(const M4& a, const M4& b) {
    M4 out{};
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            double value = 0.0;
            for (int k = 0; k < 4; ++k) value += a[r * 4 + k] * b[k * 4 + c];
            out[r * 4 + c] = value;
        }
    }
    return out;
}

V4 multiply(const M4& a, const V4& b) {
    V4 out{};
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) out[r] += a[r * 4 + c] * b[c];
    }
    return out;
}

bool inverse(const M4& input, M4& output) {
    double a[4][8]{};
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) a[r][c] = input[r * 4 + c];
        a[r][4 + r] = 1.0;
    }
    for (int c = 0; c < 4; ++c) {
        int pivot = c;
        for (int r = c + 1; r < 4; ++r)
            if (std::abs(a[r][c]) > std::abs(a[pivot][c])) pivot = r;
        if (!finite(a[pivot][c]) || a[pivot][c] == 0.0) return false;
        if (pivot != c) for (int k = 0; k < 8; ++k) std::swap(a[pivot][k], a[c][k]);
        const double divisor = a[c][c];
        for (int k = 0; k < 8; ++k) a[c][k] /= divisor;
        for (int r = 0; r < 4; ++r) {
            if (r == c) continue;
            const double factor = a[r][c];
            for (int k = 0; k < 8; ++k) a[r][k] -= factor * a[c][k];
        }
    }
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) output[r * 4 + c] = a[r][c + 4];
    return finite(output);
}

V3 transform_point(const M4& matrix, const V3& point) {
    return {matrix[0] * point[0] + matrix[1] * point[1] + matrix[2] * point[2] + matrix[3],
            matrix[4] * point[0] + matrix[5] * point[1] + matrix[6] * point[2] + matrix[7],
            matrix[8] * point[0] + matrix[9] * point[1] + matrix[10] * point[2] + matrix[11]};
}

Corners box_corners(const std::array<double, 6>& bounds) {
    Corners out{};
    for (int i = 0; i < 8; ++i) {
        for (int axis = 0; axis < 3; ++axis) {
            const double lo = bounds[axis];
            const double hi = bounds[axis + 3];
            // Keep the centered-corner convention used by the Python code.
            out[i][axis] = (lo + hi) * 0.5 + kSigns[i][axis] * (hi - lo) * 0.5;
        }
    }
    return out;
}

Planes box_planes(const std::array<double, 6>& bounds) {
    Planes out{};
    for (int axis = 0; axis < 3; ++axis) {
        out[axis] = {0.0, 0.0, 0.0, -bounds[axis]};
        out[axis][axis] = 1.0;
        out[axis + 3] = {0.0, 0.0, 0.0, bounds[axis + 3]};
        out[axis + 3][axis] = -1.0;
    }
    return out;
}

struct Record {
    std::array<double, 6> bounds{};
    M4 world{};
    M4 inverse_world{};
    Corners corners{};
    Corners world_corners{};
    Planes planes{};
    double tolerance = 1e-12;
};

bool affine_world(const M4& world) {
    return finite(world) && world[12] == 0.0 && world[13] == 0.0 &&
           world[14] == 0.0 && world[15] == 1.0;
}

Record prepare(const std::array<double, 6>& bounds, const M4& world) {
    if (!affine_world(world)) throw std::domain_error("invalid affine transform");
    for (int axis = 0; axis < 3; ++axis) {
        if (!finite(bounds[axis]) || !finite(bounds[axis + 3]) || bounds[axis] > bounds[axis + 3])
            throw std::domain_error("invalid bounds");
    }
    Record out;
    out.bounds = bounds;
    out.world = world;
    if (!inverse(world, out.inverse_world)) throw std::domain_error("singular transform");
    out.corners = box_corners(bounds);
    out.world_corners = out.corners;
    for (V3& p : out.world_corners) p = transform_point(world, p);
    for (const V3& p : out.corners)
        out.tolerance = std::max(out.tolerance,
            std::max({std::abs(p[0]), std::abs(p[1]), std::abs(p[2])}) * 1e-9);
    out.planes = box_planes(bounds);
    for (const V3& p : out.world_corners) if (!finite(p)) throw std::domain_error("invalid world bounds");
    return out;
}

V4 plane_to_local(const M4& world, const V4& plane) {
    V4 out{};
    // p_local = transpose(world) * p_world.
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) out[r] += world[c * 4 + r] * plane[c];
    return out;
}

std::vector<V3> crossings(const Corners& corners, const Planes& planes) {
    std::vector<V3> points;
    points.reserve(72);
    for (const auto& edge : kEdges) {
        const V3& start = corners[edge[0]];
        const V3 delta = sub(corners[edge[1]], start);
        for (const V4& plane : planes) {
            const V3 normal{plane[0], plane[1], plane[2]};
            const double distance = dot(start, normal) + plane[3];
            const double denominator = dot(delta, normal);
            if (std::abs(denominator) <= 1e-15) continue;
            const double t = -distance / denominator;
            if (!finite(t) || t < -1e-10 || t > 1.0 + 1e-10) continue;
            const V3 point = add(start, mul(delta, t));
            if (finite(point)) points.push_back(point);
        }
    }
    return points;
}

bool inside(const V3& point, const Planes& planes, double tolerance) {
    for (const V4& plane : planes) {
        const double value = point[0] * plane[0] + point[1] * plane[1] +
                             point[2] * plane[2] + plane[3];
        if (!(value >= -tolerance)) return false;
    }
    return true;
}

bool intersect(const Record& record, const Planes& clip_planes,
               const Corners& clip_corners, std::vector<V3>& output) {
    Planes local_planes{};
    for (int i = 0; i < 6; ++i) {
        local_planes[i] = plane_to_local(record.world, clip_planes[i]);
        const double n = norm(V3{local_planes[i][0], local_planes[i][1], local_planes[i][2]});
        if (!(n > 0.0) || !finite(n)) return false;
        for (double& value : local_planes[i]) value /= n;
    }
    std::array<std::array<double, 6>, 8> distances{};
    bool contained = true;
    bool rejected = false;
    for (int c = 0; c < 8; ++c) {
        for (int p = 0; p < 6; ++p) {
            const V4& plane = local_planes[p];
            const double value = dot(record.corners[c], V3{plane[0], plane[1], plane[2]}) + plane[3];
            distances[c][p] = value;
            if (!(value >= -record.tolerance)) contained = false;
        }
    }
    for (int p = 0; p < 6; ++p) {
        double maximum = -std::numeric_limits<double>::infinity();
        for (int c = 0; c < 8; ++c) maximum = std::max(maximum, distances[c][p]);
        if (maximum < -record.tolerance) rejected = true;
    }
    if (contained) {
        output.insert(output.end(), record.world_corners.begin(), record.world_corners.end());
        return true;
    }
    if (rejected) return true;

    Corners clip_local{};
    for (int i = 0; i < 8; ++i) clip_local[i] = transform_point(record.inverse_world, clip_corners[i]);
    std::vector<V3> candidates;
    candidates.reserve(160);
    candidates.insert(candidates.end(), record.corners.begin(), record.corners.end());
    candidates.insert(candidates.end(), clip_local.begin(), clip_local.end());
    const auto first_crossings = crossings(record.corners, local_planes);
    candidates.insert(candidates.end(), first_crossings.begin(), first_crossings.end());
    const auto second_crossings = crossings(clip_local, record.planes);
    candidates.insert(candidates.end(), second_crossings.begin(), second_crossings.end());
    for (const V3& candidate : candidates) {
        if (inside(candidate, local_planes, record.tolerance) &&
            inside(candidate, record.planes, record.tolerance)) {
            const V3 point = transform_point(record.world, candidate);
            if (!finite(point)) return false;
            output.push_back(point);
        }
    }
    return true;
}

void include_point(const V3& p, V3& lo, V3& hi, bool& first) {
    if (!finite(p)) throw std::domain_error("non-finite clipping point");
    if (first) {
        lo = hi = p;
        first = false;
        return;
    }
    for (int i = 0; i < 3; ++i) {
        lo[i] = std::min(lo[i], p[i]);
        hi[i] = std::max(hi[i], p[i]);
    }
}

}  // namespace

namespace spqr {

bool fit_shadow(const std::vector<ShadowBox>& input, const double* direction,
                const double* view, const double* projection, unsigned resolution,
                double* output, const double* previous, bool* emptyReceivers, bool stabilize) {
    if (output) std::fill(output, output + 16, 0.0);
    if (emptyReceivers) *emptyReceivers = false;
    try {
        if (!output || !direction || !view || !projection || input.empty() || resolution == 0) return false;

        V3 light{direction[0], direction[1], direction[2]};
        if (!finite(light)) return false;
        const double maximum = std::max({std::abs(light[0]), std::abs(light[1]), std::abs(light[2])});
        if (!(maximum > 0.0) || !finite(maximum)) return false;
        light = mul(light, 1.0 / maximum);
        light = normalize(light);

        M4 view_matrix{}, projection_matrix{};
        std::copy(view, view + 16, view_matrix.begin());
        std::copy(projection, projection + 16, projection_matrix.begin());
        if (!finite(view_matrix) || !finite(projection_matrix)) return false;
        const M4 vp = multiply(projection_matrix, view_matrix);
        M4 inverse_vp{};
        if (!finite(vp) || !inverse(vp, inverse_vp)) return false;

        // Match argmin(abs(light)) including first-index tie breaking.
        V3 up{};
        const double ax = std::abs(light[0]), ay = std::abs(light[1]), az = std::abs(light[2]);
        if (ax <= ay && ax <= az) up = {1.0, 0.0, 0.0};
        else if (ay <= az) up = {0.0, 1.0, 0.0};
        else up = {0.0, 0.0, 1.0};
        const V3 right = normalize(cross(up, light));
        const V3 second = cross(light, right);
        const std::array<V3, 3> rotation{right, second, light};

        Planes camera_planes{};
        int plane_index = 0;
        for (int axis = 0; axis < 3; ++axis) {
            for (double sign : {1.0, -1.0}) {
                V4 plane{};
                for (int c = 0; c < 4; ++c)
                    plane[c] = vp[12 + c] + sign * vp[axis * 4 + c];
                camera_planes[plane_index++] = plane;
            }
        }
        Corners frustum{};
        for (int i = 0; i < 8; ++i) {
            const V4 h = multiply(inverse_vp, V4{static_cast<double>(kSigns[i][0]),
                                                static_cast<double>(kSigns[i][1]),
                                                static_cast<double>(kSigns[i][2]), 1.0});
            if (!finite(h[0]) || !finite(h[1]) || !finite(h[2]) || !finite(h[3]) || h[3] == 0.0)
                return false;
            frustum[i] = {h[0] / h[3], h[1] / h[3], h[2] / h[3]};
            if (!finite(frustum[i])) return false;
        }

        std::vector<Record> ordinary;
        std::vector<const ShadowBox*> grounds;
        ordinary.reserve(input.size());
        for (const ShadowBox& box : input) {
            if (box.ground) {
                (void)prepare(box.bounds, box.world);  // Validate even when there are no casters.
                grounds.push_back(&box);
            }
            else ordinary.push_back(prepare(box.bounds, box.world));
        }
        if (grounds.empty()) {
            for (const ShadowBox& box : input)
                if (box.ground) ordinary.push_back(prepare(box.bounds, box.world));
        } else {
            if (ordinary.empty()) {
                if (emptyReceivers) *emptyReceivers = true;
                return false;  // Ground alone has no finite caster footprint.
            }
            std::vector<V3> caster_corners;
            caster_corners.reserve(ordinary.size() * 8);
            for (const Record& record : ordinary)
                caster_corners.insert(caster_corners.end(), record.world_corners.begin(), record.world_corners.end());
            for (const ShadowBox* ground : grounds) {
                const Record base = prepare(ground->bounds, ground->world);
                const M4& inverse_ground = base.inverse_world;
                const V3 normal{inverse_ground[8], inverse_ground[9], inverse_ground[10]};
                const double denominator = dot(normal, light);
                if (std::abs(denominator) < 1e-10) {
                    ordinary.push_back(base);
                    continue;
                }
                const V3 local_center{
                    (ground->bounds[0] + ground->bounds[3]) * 0.5,
                    (ground->bounds[1] + ground->bounds[4]) * 0.5,
                    (ground->bounds[2] + ground->bounds[5]) * 0.5};
                const V3 plane = transform_point(ground->world, local_center);
                V3 lo{}, hi{};
                bool first = true;
                for (const V3& point : caster_corners) {
                    const double distance = dot(sub(point, plane), normal) / denominator;
                    const V3 projected = sub(point, mul(light, distance));
                    const V3 local = transform_point(inverse_ground, projected);
                    include_point(local, lo, hi, first);
                }
                if (first) return false;
                const double local_z = local_center[2];
                lo[2] = hi[2] = local_z;
                std::array<double, 6> footprint{lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]};
                ordinary.push_back(prepare(footprint, ground->world));
            }
        }
        if (ordinary.empty()) return false;

        std::vector<V3> receiver_points;
        for (const Record& record : ordinary) {
            if (!intersect(record, camera_planes, frustum, receiver_points)) return false;
        }
        if (receiver_points.empty()) {
            if (emptyReceivers) *emptyReceivers = true;
            return false;
        }

        V3 lo{}, hi{};
        bool first = true;
        for (const V3& point : receiver_points) {
            V3 light_point{};
            for (int axis = 0; axis < 3; ++axis) light_point[axis] = dot(rotation[axis], point);
            include_point(light_point, lo, hi, first);
        }
        if (first) return false;
        const V3 extent = sub(hi, lo);
        const double margin = std::max(std::max(extent[0], extent[1]) *
                                       std::max(0.02, 4.0 / static_cast<double>(resolution)), 1e-12);
        lo[0] -= margin; lo[1] -= margin;
        hi[0] += margin; hi[1] += margin;

        // Snap the padded receiver volume before caster clipping, so newly
        // included XY texels also have conservative caster depth coverage.
        M4 receiver_matrix{0,0,0,0, 0,0,0,0, 0,0,1,0, 0,0,0,1};
        for (int r = 0; r < 2; ++r) {
            const double scale = 2.0 / (hi[r] - lo[r]);
            for (int c = 0; c < 3; ++c) receiver_matrix[r * 4 + c] = scale * rotation[r][c];
            receiver_matrix[r * 4 + 3] = -scale * (hi[r] + lo[r]) * .5;
        }
        if (stabilize && !stabilize_shadow_matrix(receiver_matrix.data(), previous, resolution)) return false;
        for (int r = 0; r < 2; ++r) {
            const double scale = std::hypot(receiver_matrix[r * 4], receiver_matrix[r * 4 + 1],
                                            receiver_matrix[r * 4 + 2]);
            const double center = -receiver_matrix[r * 4 + 3] / scale;
            lo[r] = center - 1.0 / scale;
            hi[r] = center + 1.0 / scale;
        }

        bool first_global = true;
        V3 global_lo{}, global_hi{};
        for (const Record& record : ordinary) {
            for (const V3& point : record.world_corners) {
                V3 light_point{};
                for (int axis = 0; axis < 3; ++axis) light_point[axis] = dot(rotation[axis], point);
                include_point(light_point, global_lo, global_hi, first_global);
            }
        }
        if (first_global) return false;
        lo[2] = global_lo[2] - margin;
        hi[2] = global_hi[2] + margin;

        const auto light_bounds = std::array<double, 6>{lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]};
        const Corners light_corners = box_corners(light_bounds);
        Corners clip_world{};
        for (int i = 0; i < 8; ++i) {
            for (int axis = 0; axis < 3; ++axis) {
                clip_world[i][axis] = light_corners[i][0] * rotation[0][axis] +
                                      light_corners[i][1] * rotation[1][axis] +
                                      light_corners[i][2] * rotation[2][axis];
            }
        }
        Planes light_planes = box_planes(light_bounds);
        for (V4& plane : light_planes) {
            const V3 normal{plane[0], plane[1], plane[2]};
            V3 transformed{};
            for (int axis = 0; axis < 3; ++axis)
                transformed[axis] = normal[0] * rotation[0][axis] +
                                    normal[1] * rotation[1][axis] +
                                    normal[2] * rotation[2][axis];
            plane[0] = transformed[0]; plane[1] = transformed[1]; plane[2] = transformed[2];
        }
        std::vector<V3> caster_points;
        for (const Record& record : ordinary) {
            if (!intersect(record, light_planes, clip_world, caster_points)) return false;
        }
        if (caster_points.empty()) return false;
        V3 caster_lo{}, caster_hi{};
        bool first_caster = true;
        for (const V3& point : caster_points) {
            V3 light_point{};
            for (int axis = 0; axis < 3; ++axis) light_point[axis] = dot(rotation[axis], point);
            include_point(light_point, caster_lo, caster_hi, first_caster);
        }
        if (first_caster) return false;
        lo[2] = caster_lo[2];
        hi[2] = caster_hi[2];
        const V3 final_extent = sub(hi, lo);
        const double depth_margin = std::max(std::max({final_extent[0], final_extent[1], final_extent[2]}) * 0.02,
                                             1e-12);
        lo[2] -= depth_margin;
        hi[2] += depth_margin;
        if (stabilize && previous) {
            const double scale = -std::hypot(previous[8], previous[9], previous[10]);
            if (scale < 0.0 && finite(scale)) {
                const V3 old_basis{previous[8] / scale, previous[9] / scale, previous[10] / scale};
                const double center = -previous[11] / scale;
                const double old_lo = center + 1.0 / scale, old_hi = center - 1.0 / scale;
                if (norm(sub(old_basis, light)) < 1e-12 &&
                    caster_lo[2] >= old_lo + depth_margin * .25 &&
                    caster_hi[2] <= old_hi - depth_margin * .25 &&
                    hi[2] - lo[2] >= (old_hi - old_lo) * .96) {
                    lo[2] = old_lo;
                    hi[2] = old_hi;
                }
            }
        }

        const V3 final_range = sub(hi, lo);
        V3 scale{2.0 / final_range[0], 2.0 / final_range[1], 2.0 / final_range[2]};
        scale[2] *= -1.0;
        M4 matrix{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
        for (int r = 0; r < 3; ++r) {
            for (int c = 0; c < 3; ++c) matrix[r * 4 + c] = scale[r] * rotation[r][c];
            matrix[r * 4 + 3] = -scale[r] * (lo[r] + hi[r]) * 0.5;
        }
        if (!finite(matrix)) return false;
        std::copy(matrix.begin(), matrix.end(), output);
        return true;
    } catch (...) {
        return false;
    }
}

bool stabilize_shadow_matrix(double* matrix, const double* previous, unsigned resolution) {
    if (!matrix || resolution == 0) return false;
    M4 result{};
    std::copy(matrix, matrix + 16, result.begin());
    if (!finite(result)) return false;
    if (resolution <= 2) return true;
    for (int axis = 0; axis < 2; ++axis) {
        const V3 row{result[axis * 4], result[axis * 4 + 1], result[axis * 4 + 2]};
        const double scale = norm(row);
        if (!(scale > 0.0) || !finite(scale)) return false;
        const V3 basis = mul(row, 1.0 / scale);
        const double input_span = 2.0 / scale;
        const double input_center = -result[axis * 4 + 3] / scale;
        double span = input_span * 1.02;
        double center = input_center;
        span /= 1.0 - 2.0 / resolution;
        if (previous) {
            const V3 old_row{previous[axis * 4], previous[axis * 4 + 1], previous[axis * 4 + 2]};
            const double old_scale = norm(old_row);
            if (old_scale > 0.0 && finite(old_scale) &&
                norm(sub(mul(old_row, 1.0 / old_scale), basis)) < 1e-12) {
                const double old_span = 2.0 / old_scale;
                if (input_span <= old_span * (1.0 - 1.0 / resolution) &&
                    input_span >= old_span * 0.96) span = old_span;
            }
        }
        const double texel = span / resolution;
        center = std::floor(center / texel + .5) * texel;
        const double stable_scale = 2.0 / span;
        for (int c = 0; c < 3; ++c) result[axis * 4 + c] = stable_scale * basis[c];
        result[axis * 4 + 3] = -stable_scale * center;
    }
    if (!finite(result)) return false;
    std::copy(result.begin(), result.end(), matrix);
    return true;
}

bool conservative_camera_near(const std::vector<ShadowBox>& boxes,
                              const double* view, const double* projection,
                              double originalNear, double* result) {
    if (result) *result = originalNear;
    try {
        if (!result || !view || !projection || boxes.empty() ||
            !finite(originalNear) || !(originalNear > 0.0)) return false;
        M4 view_matrix{}, projection_matrix{};
        std::copy(view, view + 16, view_matrix.begin());
        std::copy(projection, projection + 16, projection_matrix.begin());
        if (!finite(view_matrix) || !finite(projection_matrix)) return false;
        const M4 vp = multiply(projection_matrix, view_matrix);
        M4 inverse_vp{};
        if (!finite(vp) || !inverse(vp, inverse_vp)) return false;

        Planes camera_planes{};
        int plane_index = 0;
        for (int axis = 0; axis < 3; ++axis) {
            for (double sign : {1.0, -1.0}) {
                V4 plane{};
                for (int c = 0; c < 4; ++c)
                    plane[c] = vp[12 + c] + sign * vp[axis * 4 + c];
                camera_planes[plane_index++] = plane;
            }
        }
        Corners frustum{};
        for (int i = 0; i < 8; ++i) {
            const V4 h = multiply(inverse_vp, V4{static_cast<double>(kSigns[i][0]),
                                                static_cast<double>(kSigns[i][1]),
                                                static_cast<double>(kSigns[i][2]), 1.0});
            if (!finite(h[0]) || !finite(h[1]) || !finite(h[2]) ||
                !finite(h[3]) || h[3] == 0.0) return false;
            frustum[i] = {h[0] / h[3], h[1] / h[3], h[2] / h[3]};
            if (!finite(frustum[i])) return false;
        }

        double minimum_depth = std::numeric_limits<double>::infinity();
        bool found = false;
        for (const ShadowBox& box : boxes) {
            // Ground is intentionally treated as its supplied finite OBB here;
            // unlike shadow fitting, camera clipping never substitutes a caster footprint.
            const Record record = prepare(box.bounds, box.world);
            std::vector<V3> points;
            if (!intersect(record, camera_planes, frustum, points)) return false;
            for (const V3& point : points) {
                const V3 camera_point = transform_point(view_matrix, point);
                const double depth = -camera_point[2];
                if (!finite(depth)) return false;
                if (depth > 0.0) {
                    minimum_depth = std::min(minimum_depth, depth);
                    found = true;
                }
            }
        }
        if (!found || !finite(minimum_depth)) return false;
        const double safe_near = std::max(originalNear, minimum_depth * 0.5);
        if (!finite(safe_near) || !(safe_near > 0.0)) return false;
        *result = safe_near;
        return true;
    } catch (...) {
        *result = originalNear;
        return false;
    }
}

bool fit_stable_shadow(const std::vector<ShadowBox>& boxes, const double* direction,
                       const double* view, const double* projection, unsigned resolution,
                       double nearDistance, double farDistance, double* output) {
    if (output) std::fill(output, output + 16, 0.0);
    try {
        if (!output || !direction || !view || !projection || boxes.empty() || resolution <= 4 ||
            !finite(nearDistance) || !finite(farDistance) || !(nearDistance > 0.0) ||
            !(farDistance > nearDistance)) return false;

        V3 light{direction[0], direction[1], direction[2]};
        if (!finite(light)) return false;
        const double maximum = std::max({std::abs(light[0]), std::abs(light[1]), std::abs(light[2])});
        if (!(maximum > 0.0) || !finite(maximum)) return false;
        light = normalize(mul(light, 1.0 / maximum));

        M4 view_matrix{}, projection_matrix{}, inverse_view{}, inverse_projection{};
        std::copy(view, view + 16, view_matrix.begin());
        std::copy(projection, projection + 16, projection_matrix.begin());
        if (!affine_world(view_matrix) || !finite(projection_matrix) ||
            !inverse(view_matrix, inverse_view) || !affine_world(inverse_view) ||
            !inverse(projection_matrix, inverse_projection)) return false;
        // This fit uses perspective rays through the camera origin. Reject
        // orthographic or nonstandard projective matrices rather than guessing.
        if (std::abs(projection_matrix[12]) > 1e-12 ||
            std::abs(projection_matrix[13]) > 1e-12 ||
            std::abs(projection_matrix[15]) > 1e-12 ||
            std::abs(projection_matrix[14]) <= 1e-12) return false;

        V3 up{};
        const double ax = std::abs(light[0]), ay = std::abs(light[1]), az = std::abs(light[2]);
        if (ax <= ay && ax <= az) up = {1.0, 0.0, 0.0};
        else if (ay <= az) up = {0.0, 1.0, 0.0};
        else up = {0.0, 0.0, 1.0};
        const V3 right = normalize(cross(up, light));
        const V3 second = cross(light, right);

        const double split_center_depth = (nearDistance + farDistance) * 0.5;
        const V3 camera_center{0.0, 0.0, -split_center_depth};
        const std::array<double, 2> split_depths{nearDistance, farDistance};
        std::array<V3, 8> camera_corners{};
        Corners world_corners{};
        int corner_index = 0;
        for (int x_sign : {-1, 1}) {
            for (int y_sign : {-1, 1}) {
                const V4 h = multiply(inverse_projection,
                    V4{static_cast<double>(x_sign), static_cast<double>(y_sign), -1.0, 1.0});
                if (!finite(h[0]) || !finite(h[1]) || !finite(h[2]) || !finite(h[3]) || h[3] == 0.0)
                    return false;
                const V3 near_point{h[0] / h[3], h[1] / h[3], h[2] / h[3]};
                const double sample_depth = -near_point[2];
                if (!finite(near_point) || !(sample_depth > 0.0)) return false;
                const double slope_x = near_point[0] / sample_depth;
                const double slope_y = near_point[1] / sample_depth;
                if (!finite(slope_x) || !finite(slope_y)) return false;
                for (double depth : split_depths) {
                    const V3 point{slope_x * depth, slope_y * depth, -depth};
                    if (!finite(point)) return false;
                    camera_corners[corner_index] = point;
                    world_corners[corner_index] = transform_point(inverse_view, point);
                    if (!finite(world_corners[corner_index])) return false;
                    ++corner_index;
                }
            }
        }

        double radius = 0.0;
        for (const V3& corner : camera_corners)
            radius = std::max(radius, norm(sub(corner, camera_center)));
        if (!(radius > 0.0) || !finite(radius)) return false;
        radius = std::ceil(radius);  // Fixed whole-world-unit radius for this split.
        const double denominator = 1.0 - 4.0 / static_cast<double>(resolution);
        if (!(denominator > 0.0)) return false;
        const double side = (2.0 * radius) / denominator;
        const double texel = side / static_cast<double>(resolution);
        if (!(side > 0.0) || !(texel > 0.0) || !finite(side) || !finite(texel)) return false;

        const V3 center_world = transform_point(inverse_view, camera_center);
        if (!finite(center_world)) return false;
        const double center_x = dot(right, center_world);
        const double center_y = dot(second, center_world);
        const double snapped_x = std::round(center_x / texel) * texel;
        const double snapped_y = std::round(center_y / texel) * texel;
        if (!finite(snapped_x) || !finite(snapped_y)) return false;

        double caster_min_z = std::numeric_limits<double>::infinity();
        double caster_max_z = -std::numeric_limits<double>::infinity();
        bool has_caster = false;
        for (const ShadowBox& box : boxes) {
            const Record record = prepare(box.bounds, box.world);  // Validate even ignored ground inputs.
            if (box.ground) continue;
            for (const V3& point : record.world_corners) {
                const double z = dot(light, point);
                if (!finite(z)) return false;
                caster_min_z = std::min(caster_min_z, z);
                caster_max_z = std::max(caster_max_z, z);
                has_caster = true;
            }
        }
        if (!has_caster || !finite(caster_min_z) || !finite(caster_max_z)) return false;
        const double depth_range = caster_max_z - caster_min_z;
        if (!finite(depth_range)) return false;
        const double depth_margin = std::max(depth_range * 0.02, 1e-6);
        const double low_z = caster_min_z - depth_margin;
        const double high_z = caster_max_z + depth_margin;
        const double z_range = high_z - low_z;
        if (!(z_range > 0.0) || !finite(z_range)) return false;

        M4 matrix{0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1};
        const double scale_xy = 2.0 / side;
        const double scale_z = -2.0 / z_range;
        for (int axis = 0; axis < 3; ++axis) {
            const V3& basis = axis == 0 ? right : (axis == 1 ? second : light);
            const double scale = axis < 2 ? scale_xy : scale_z;
            for (int c = 0; c < 3; ++c) matrix[axis * 4 + c] = scale * basis[c];
        }
        matrix[3] = -scale_xy * snapped_x;
        matrix[7] = -scale_xy * snapped_y;
        matrix[11] = -scale_z * (low_z + high_z) * 0.5;
        if (!finite(matrix)) return false;
        std::copy(matrix.begin(), matrix.end(), output);
        return true;
    } catch (...) {
        if (output) std::fill(output, output + 16, 0.0);
        return false;
    }
}

}  // namespace spqr

extern "C" int spqr_stabilize_shadow(double* matrix, const double* previous, uint32_t resolution) {
    return spqr::stabilize_shadow_matrix(matrix, previous, resolution) ? 1 : 0;
}

extern "C" int spqr_fit_shadow(const double* bounds, const double* worlds,
                               const uint32_t* flags, uint32_t count,
                               const double* direction, const double* view,
                               const double* projection, uint32_t resolution,
                               double* output) {
    return spqr_fit_shadow_temporal(bounds, worlds, flags, count, direction, view,
                                   projection, resolution, nullptr, output);
}

extern "C" int spqr_fit_shadow_temporal(const double* bounds, const double* worlds,
                                        const uint32_t* flags, uint32_t count,
                                        const double* direction, const double* view,
                                        const double* projection, uint32_t resolution,
                                        const double* previous, double* output) {
    if (output) std::fill(output, output + 16, 0.0);
    try {
        if (!output || !bounds || !worlds || !flags || !direction || !view || !projection ||
            count == 0 || resolution == 0) return 0;
        std::vector<spqr::ShadowBox> boxes;
        boxes.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            if (flags[i] & ~uint32_t{3}) return 0;
            spqr::ShadowBox box;
            std::copy(bounds + static_cast<size_t>(i) * 6,
                      bounds + static_cast<size_t>(i + 1) * 6, box.bounds.begin());
            std::copy(worlds + static_cast<size_t>(i) * 16,
                      worlds + static_cast<size_t>(i + 1) * 16, box.world.begin());
            box.ground = (flags[i] & 1u) != 0;
            boxes.push_back(box);
        }
        return spqr::fit_shadow(boxes, direction, view, projection, resolution, output, previous) ? 1 : 0;
    } catch (...) {
        if (output) std::fill(output, output + 16, 0.0);
        return 0;
    }
}

extern "C" int spqr_fit_stable_shadow(const double* bounds, const double* worlds,
                                      const uint32_t* flags, uint32_t count,
                                      const double* direction, const double* view,
                                      const double* projection, uint32_t resolution,
                                      double nearDistance, double farDistance, double* output) {
    if (output) std::fill(output, output + 16, 0.0);
    try {
        if (!output || !bounds || !worlds || !flags || !direction || !view || !projection ||
            count == 0 || resolution <= 4) return 0;
        std::vector<spqr::ShadowBox> boxes;
        boxes.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            if (flags[i] & ~uint32_t{3}) return 0;
            spqr::ShadowBox box;
            std::copy(bounds + static_cast<size_t>(i) * 6,
                      bounds + static_cast<size_t>(i + 1) * 6, box.bounds.begin());
            std::copy(worlds + static_cast<size_t>(i) * 16,
                      worlds + static_cast<size_t>(i + 1) * 16, box.world.begin());
            box.ground = (flags[i] & 1u) != 0;
            boxes.push_back(box);
        }
        return spqr::fit_stable_shadow(boxes, direction, view, projection, resolution,
                                       nearDistance, farDistance, output) ? 1 : 0;
    } catch (...) {
        if (output) std::fill(output, output + 16, 0.0);
        return 0;
    }
}

extern "C" int spqr_camera_near(const double* bounds, const double* worlds,
                                const uint32_t* flags, uint32_t count,
                                const double* view, const double* projection,
                                double originalNear, double* result) {
    if (result) *result = originalNear;
    try {
        if (!result || !bounds || !worlds || !flags || !view || !projection || count == 0)
            return 0;
        std::vector<spqr::ShadowBox> boxes;
        boxes.reserve(count);
        for (uint32_t i = 0; i < count; ++i) {
            if (flags[i] & ~uint32_t{3}) return 0;
            spqr::ShadowBox box;
            std::copy(bounds + static_cast<size_t>(i) * 6,
                      bounds + static_cast<size_t>(i + 1) * 6, box.bounds.begin());
            std::copy(worlds + static_cast<size_t>(i) * 16,
                      worlds + static_cast<size_t>(i + 1) * 16, box.world.begin());
            // Both flag bits describe render metadata. The camera fit clips the
            // actual finite bounds identically for ordinary meshes and ground.
            box.ground = (flags[i] & 1u) != 0;
            boxes.push_back(box);
        }
        return spqr::conservative_camera_near(boxes, view, projection, originalNear, result) ? 1 : 0;
    } catch (...) {
        if (result) *result = originalNear;
        return 0;
    }
}
