#include "shadow_fit.hpp"
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
using Matrix = std::array<double, 16>;
const Matrix identity{1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
}

int main() {
    const double near = .1, far = 100.;
    const Matrix projection{1,0,0,0, 0,1,0,0,
        0,0,(far+near)/(near-far),2*near*far/(near-far), 0,0,-1,0};
    const double direction[3]{.4,-.5,.8};
    spqr::ShadowBox visible{{-1,-1,-6,1,1,-4}, identity, false};
    Matrix output{};
    bool empty = true;
    require(spqr::fit_shadow({visible}, direction, identity.data(), projection.data(),
                            2048, output.data(), &empty) && !empty,
            "valid visible caster was treated as empty");
    spqr::ShadowBox behind{{-1,-1,4,1,1,6}, identity, false};
    require(!spqr::fit_shadow({behind}, direction, identity.data(), projection.data(),
                             2048, output.data(), &empty) && empty,
            "normal empty camera region was not reported");
    spqr::ShadowBox ground{{-1,-1,0,1,1,0}, identity, true};
    require(!spqr::fit_shadow({ground}, direction, identity.data(), projection.data(),
                             2048, output.data(), &empty) && empty,
            "ground-only frame should have no caster footprint");
    ground.world[0] = std::numeric_limits<double>::quiet_NaN();
    require(!spqr::fit_shadow({ground}, direction, identity.data(), projection.data(),
                             2048, output.data(), &empty) && !empty,
            "invalid ground was hidden as empty");
    Matrix invalid{};
    require(!spqr::fit_shadow({visible}, direction, identity.data(), invalid.data(),
                             2048, output.data(), &empty) && !empty,
            "invalid camera was hidden as empty");
    std::cout << "PASS visible/empty/ground-only receivers and invalid-ground/camera diagnostics\n";
}
