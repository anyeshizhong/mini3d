// Diagnostic only: render real native maps, then run the production shadow
// function at fixed world probes and shade a stationary observation camera.
#include "renderer.hpp"
#include "shadow_fit.hpp"
#include "platform_win32.hpp"
#include <algorithm>
#include <cmath>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>

namespace spqr {
struct ShadowAudit {
    static void setTransitions(Renderer& r, bool enabled) { r.shadowTransitionsEnabled_=enabled; }

    static FrameStats render(Renderer& r, const CameraFrame& camera, bool originalFar) {
        auto stats=r.render(camera);
        if(originalFar) {
            std::vector<ShadowBox> boxes;
            for(const auto& entity:r.bundle_.entities)
                boxes.push_back({r.bundle_.meshes[entity.mesh].bounds,r.effectiveWorld(entity,camera),bool(entity.flags&1u)});
            // Keep the existing native near cascade and replace only the far
            // depth with the exact pre-fix receiver fit. No production hook.
            r.shadowTransition_=false;
            r.stableShadows_=false;
            r.drawShadowLayer(camera,stats,boxes,false);
            r.stableShadows_=true;
            r.farFitValid_=false;
        }
        return stats;
    }
    static void invalidateDepth(Renderer& r) {
        r.shadowDepthValid_=r.nearShadowDepthValid_=false;
    }
    static std::uint64_t depthHash(Renderer& r) {
        std::uint64_t hash=1469598103934665603ull;
        for(bool nearLayer : {false,true}) {
            const GLuint fbo=nearLayer?r.nearShadowFbo_:r.shadowFbo_;
            if(!fbo) continue;
            const auto size=nearLayer?r.nearShadowResolution_:r.bundle_.shadowResolution;
            std::vector<float> depth(std::size_t(size)*size);
            r.gl_.BindFramebuffer(GL_READ_FRAMEBUFFER,fbo);
            r.gl_.ReadPixels(0,0,size,size,GL_DEPTH_COMPONENT,GL_FLOAT,depth.data());
            const auto bytes=reinterpret_cast<const unsigned char*>(depth.data());
            for(std::size_t j=0;j<depth.size()*sizeof(float);++j) { hash^=bytes[j];hash*=1099511628211ull; }
        }
        r.checkError("audit raw shadow depth hash");
        return hash;
    }
    static void testInvalidation(Renderer& r, const CameraFrame& camera) {
        const auto entity=r.bundle_.entities.front();
        auto moved=entity.world;moved[3]+=.02;
        if(!r.setTransform(entity.id,moved)||r.render(camera).shadowDraws==0)
            throw std::runtime_error("transform failed to invalidate shadow depth");
        r.setTransform(entity.id,entity.world);
        if(r.render(camera).shadowDraws==0) throw std::runtime_error("transform restore cache invalidation failed");
        const auto direction=r.bundle_.lightDirection;
        auto changed=direction;changed[0]+=.01;
        auto update=[&](const std::array<double,3>& light) {
            r.updateGlobals(r.bundle_.materialGlobals,r.bundle_.skyGlobals,light,r.bundle_.shadowResolution,
                            r.bundle_.shadowBias,r.bundle_.shadowEnabled,r.bundle_.groundZ);
        };
        update(changed);
        if(r.render(camera).shadowDraws==0) throw std::runtime_error("light failed to invalidate shadow depth");
        update(direction);
        if(r.render(camera).shadowDraws==0) throw std::runtime_error("light restore cache invalidation failed");
    }
    static GLuint program(Renderer& r, const std::filesystem::path& output) {
        auto source = readTextFile(r.shaderDirectory_ / "probe.frag");
        if(r.stableShadows_) {
            const auto begin=source.find("float shadowVisibility(");
            const auto end=source.find("uniform bool photoColorEnabled;",begin);
            source.replace(begin,end-begin,readTextFile(r.shaderDirectory_/"shadow_cascade.glsl")+"\n");
            source.insert(source.find('\n')+1,"#define AUDIT_STABLE\n");
        }
        const auto fragment=output/"probe.frag";
        { std::ofstream out(fragment); out<<source; }
        return r.compileProgram(r.shaderDirectory_ / "probe.vert",fragment);
    }
    static void probe(Renderer& r, const CameraFrame& camera, GLuint program, GLuint fbo,
                      GLuint points, int width, int height, std::ostream& output) {
        r.gl_.UseProgram(program);
        r.activeColorProgram_ = program;
        r.applyUniformBlock(program, r.bundle_.materialGlobals);
        r.bindMaterial(0, false, false);
        std::array<float,16> view{};
        std::transform(camera.view.begin(), camera.view.end(), view.begin(), [](double x) { return float(x); });
        r.setUniformMatrix4(program, "view", view.data());
        const auto& light = r.bundle_.lightDirection;
        const double length = std::hypot(light[0], light[1], light[2]);
        r.setUniform3f(program, "auditLight", float(light[0]/length), float(light[1]/length), float(light[2]/length));
        r.setUniform1i(program, "auditPoints", 15);
        r.gl_.ActiveTexture(GL_TEXTURE0+15);
        r.gl_.BindTexture(GL_TEXTURE_2D, points);
        r.gl_.BindSampler(15, 0);
        r.gl_.BindFramebuffer(GL_FRAMEBUFFER, fbo);
        r.gl_.Viewport(0,0,width,height);
        r.gl_.Disable(GL_DEPTH_TEST); r.gl_.DepthMask(GL_FALSE);
        r.gl_.Disable(GL_CULL_FACE); r.gl_.Disable(GL_BLEND);
        r.gl_.BindVertexArray(r.skyVao_);
        r.gl_.DrawArrays(GL_TRIANGLES,0,3);
        std::vector<float> values(std::size_t(width)*height*4);
        r.gl_.ReadBuffer(GL_COLOR_ATTACHMENT0);
        r.gl_.ReadPixels(0,0,width,height,GL_RGBA,GL_FLOAT,values.data());
        output.write(reinterpret_cast<const char*>(values.data()), std::streamsize(values.size()*sizeof(float)));
        r.checkError("native fixed-world shadow probes");
    }
    static void observer(Renderer& r, const CameraFrame& camera, const std::filesystem::path& file) {
        r.gl_.BindFramebuffer(GL_FRAMEBUFFER, r.colorFbo_);
        r.gl_.ColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE);
        r.gl_.DepthMask(GL_TRUE);
        r.gl_.ClearColor(0,0,0,1); r.gl_.ClearDepth(1);
        r.gl_.Clear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        r.drawSky(camera);
        FrameStats stats;
        r.drawColor(camera,r.visibleInFrustum(camera,true),stats);
        r.captureColor(file);
        r.checkError("native stationary observer");
    }
    static void shadowTiming(Renderer& r, const CameraFrame& camera, bool originalFar,
                             const std::filesystem::path& path) {
        const auto gen = reinterpret_cast<PFNGLGENQUERIESPROC>(wglGetProcAddress("glGenQueries"));
        const auto begin = reinterpret_cast<PFNGLBEGINQUERYPROC>(wglGetProcAddress("glBeginQuery"));
        const auto end = reinterpret_cast<PFNGLENDQUERYPROC>(wglGetProcAddress("glEndQuery"));
        const auto get = reinterpret_cast<PFNGLGETQUERYOBJECTUI64VPROC>(wglGetProcAddress("glGetQueryObjectui64v"));
        const auto del = reinterpret_cast<PFNGLDELETEQUERIESPROC>(wglGetProcAddress("glDeleteQueries"));
        if(!gen || !begin || !end || !get || !del) throw std::runtime_error("missing GL3.3 timer queries");
        GLuint query=0;gen(1,&query);
        std::ofstream out(path);out<<"{\"method\":\"forced production far+near depth redraw, color excluded; 2 warmups + 9 samples\",\"gpu_ms\":[";
        std::vector<ShadowBox> boxes;
        for(const auto& entity:r.bundle_.entities)
            boxes.push_back({r.bundle_.meshes[entity.mesh].bounds,r.effectiveWorld(entity,camera),bool(entity.flags&1u)});
        for(int i=0;i<11;++i) {
            invalidateDepth(r);r.farFitValid_=false;r.shadowTransition_=false;
            r.gl_.Finish();begin(GL_TIME_ELAPSED,query);
            FrameStats stats;
            const auto start=std::chrono::steady_clock::now();
            r.stableShadows_=!originalFar;
            r.drawShadowLayer(camera,stats,boxes,false);
            r.stableShadows_=true;
            r.drawShadowLayer(camera,stats,boxes,true);
            end(GL_TIME_ELAPSED);
            GLuint64 ns=0;get(query,GL_QUERY_RESULT,&ns);
            const auto elapsed=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
            if(i>=2) {if(i>2) out<<',';out<<ns/1e6;}
            (void)elapsed;
        }
        out<<"]}";del(1,&query);r.checkError("shadow-only GPU timing");
    }
    static void trace(Renderer& r, std::ostream& out, std::size_t index, bool comma) {
        if (comma) out << ',';
        out << "{\"frame\":" << index << ",\"far_active\":" << r.shadowActive_
            << ",\"transition\":" << r.shadowTransition_ << ",\"blend\":" << (r.shadowBlendStep_-1)/7.0
            << ",\"near_active\":" << r.nearShadowActive_ << ",\"far\":[";
        for (std::size_t j=0;j<16;++j) { if(j) out<<','; out<<r.shadowMatrix_[j]; }
        out << "],\"near\":[";
        for (std::size_t j=0;j<16;++j) { if(j) out<<','; out<<r.nearShadowMatrix_[j]; }
        out << "]}";
    }
};
}

int main(int argc, char** argv) {
    try {
        if(argc<4) throw std::runtime_error("usage: spqr-shadow-audit BUNDLE OUTPUT stable|before|legacy");
        const std::filesystem::path bundlePath=argv[1], outputPath=argv[2];
        const bool stable=std::string(argv[3])!="legacy";
        const bool originalFar=std::string(argv[3])=="before";
        std::filesystem::create_directories(outputPath);
        auto bundle=spqr::loadBundle(bundlePath);
        const auto cameras=spqr::loadFrames(bundlePath/"frames.bin");
        constexpr int height=384,probeWidth=256,probeHeight=288;
        const int width=int(std::lround(height*std::abs(cameras.front().projection[5]/cameras.front().projection[0])));
        std::vector<float> points(std::size_t(probeWidth)*probeHeight*3);
        std::ifstream probeFile(bundlePath/"probes.f32",std::ios::binary);
        if(!probeFile.read(reinterpret_cast<char*>(points.data()),std::streamsize(points.size()*sizeof(float))))
            throw std::runtime_error("missing/truncated probes.f32");
        spqr::Win32Window window(width,height,true,false);
        spqr::GLApi gl;
        std::string error;
        if(!gl.load(error)) throw std::runtime_error(error);
        spqr::Renderer renderer(gl,bundle,bundlePath,width,height,false,1,stable);
        spqr::ShadowAudit::setTransitions(renderer,std::string(argv[3])!="nofade");
        const GLuint program=spqr::ShadowAudit::program(renderer,outputPath);
        GLuint textures[2]{},fbo=0;
        gl.GenTextures(2,textures);
        for(int i=0;i<2;++i) {
            gl.BindTexture(GL_TEXTURE_2D,textures[i]);
            gl.TexImage2D(GL_TEXTURE_2D,0,i?GL_RGBA32F:GL_RGB32F,probeWidth,probeHeight,
                          0,i?GL_RGBA:GL_RGB,GL_FLOAT,i?nullptr:points.data());
            gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
            gl.TexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        }
        gl.GenFramebuffers(1,&fbo);
        gl.BindFramebuffer(GL_FRAMEBUFFER,fbo);
        gl.FramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,textures[1],0);
        gl.DrawBuffer(GL_COLOR_ATTACHMENT0);
        if(gl.CheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)
            throw std::runtime_error("probe framebuffer incomplete");
        std::ofstream trace(outputPath/"trace.json"), values(outputPath/"probes.rgba.f32",std::ios::binary);
        trace<<std::setprecision(17)<<"{\"renderer\":\""<<renderer.rendererName()<<"\",\"frames\":[";
        // Three repeated first-camera renders are independent deterministic controls.
        std::ofstream controls(outputPath/"static.rgba.f32",std::ios::binary);
        std::uint64_t cachedHash=0;
        for(int i=0;i<3;++i) {
            if(i==2) spqr::ShadowAudit::invalidateDepth(renderer);
            const auto stats=spqr::ShadowAudit::render(renderer,cameras.front(),originalFar);
            if(i==1&&!originalFar&&stats.shadowDraws!=0) throw std::runtime_error("identical matrix missed shadow cache");
            if(i==2&&stats.shadowDraws==0) throw std::runtime_error("forced shadow redraw was skipped");
            spqr::ShadowAudit::probe(renderer,cameras.front(),program,fbo,textures[0],probeWidth,probeHeight,controls);
            if(i==1) cachedHash=spqr::ShadowAudit::depthHash(renderer);
            if(i==2&&cachedHash!=spqr::ShadowAudit::depthHash(renderer))
                throw std::runtime_error("cached/forced-redraw raw depth differs");
            if(i>0) spqr::ShadowAudit::observer(renderer,cameras.front(),outputPath/(i==1?"cached.ppm":"forced.ppm"));
        }
        spqr::ShadowAudit::testInvalidation(renderer,cameras.front());
        {std::ofstream out(outputPath/"cache-control.json");
         out<<"{\"cached_vs_forced_depth_exact\":true,\"transform_invalidates\":true,\"light_invalidates\":true,\"raw_depth_hash\":"<<cachedHash<<"}";}
        for(std::size_t i=0;i<cameras.size();++i) {
            if(!window.pumpEvents()) throw std::runtime_error("audit window closed");
            spqr::ShadowAudit::render(renderer,cameras[i],originalFar);
            spqr::ShadowAudit::probe(renderer,cameras[i],program,fbo,textures[0],probeWidth,probeHeight,values);
            spqr::ShadowAudit::trace(renderer,trace,i,i!=0);
            {
                std::ostringstream name; name<<"fixed-"<<std::setw(3)<<std::setfill('0')<<i<<".ppm";
                spqr::ShadowAudit::observer(renderer,cameras.front(),outputPath/name.str());
            }
            if(i%30==0) std::cout<<i<<'/'<<cameras.size()<<'\n'<<std::flush;
        }
        trace<<"],\"all_gl_errors_zero\":"<<(gl.GetError()==GL_NO_ERROR)<<"}";
        spqr::ShadowAudit::shadowTiming(renderer,cameras.back(),originalFar,outputPath/"shadow-timing.json");
        gl.DeleteProgram(program); gl.DeleteFramebuffers(1,&fbo); gl.DeleteTextures(2,textures);
        std::cout<<"PASS native GPU audit capture "<<outputPath.string()<<'\n';
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<"SPQR shadow audit: "<<e.what()<<'\n'; return 1;
    }
}
