"""Rebuild the shipped Recoil WebAssembly engine in an initialized emsdk shell."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ENGINE_COMMIT = "71b7f5713e2be411c34b5900aa7a7a87638ce399"
GLSLANG = "e1b562a8bed273a02f30b59b66a5d499793cede5"
SPIRV_CROSS = "f11ba9f0b21ba8fc15153d50a2a1ae31ab1cf8f7"
ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=None):
    command, *params = map(str, args)
    subprocess.run([shutil.which(command) or command, *params], cwd=cwd, check=True)


def checkout(dest, repo, revision, depth=1):
    if not dest.exists():
        run("git", "init", dest)
        run("git", "remote", "add", "origin", repo, cwd=dest)
    run("git", "fetch", "--no-tags", f"--depth={depth}", "origin", revision, cwd=dest)
    run("git", "checkout", "--detach", revision, cwd=dest)


def shader(name, work, repo, revision, options, jobs):
    source = work / name
    build = work / (name + "-build")
    checkout(source, repo, revision)
    run("emcmake", "cmake", "-S", source, "-B", build, "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_INSTALL_PREFIX={work / 'shaders'}",
        "-DCMAKE_CXX_FLAGS=-pthread -fwasm-exceptions -sSUPPORT_LONGJMP=wasm",
        "-DCMAKE_C_FLAGS=-pthread -sSUPPORT_LONGJMP=wasm", *options)
    run("cmake", "--build", build, "--target", "install", "-j", jobs)


def stage(out, source):
    target = ROOT / "public/engine"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("spring-web.js", "spring-web.wasm"):
        shutil.copy2(out / name, target / name)
    shutil.copytree(out / "base", target / "base", dirs_exist_ok=True)
    shutil.copytree(source / "cont/fonts", target / "fonts", dirs_exist_ok=True)
    for name in ("LICENSE", "AUTHORS", "gpl-2.0.txt"):
        shutil.copy2(source / name, target / name)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--work", type=Path, default=ROOT / ".build")
    cli.add_argument("-j", default="6")
    args = cli.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    src, out = work / "RecoilEngine", work / "out"
    checkout(src, "https://github.com/SgtMetz/RecoilEngine.git", ENGINE_COMMIT, depth=64)
    patch = ROOT / "tools/zero-k-bmp.patch"
    applied = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)],
                             cwd=src, capture_output=True).returncode == 0
    if not applied:
        run("git", "apply", patch, cwd=src)
    run("git", "fetch", "--depth=1", "https://github.com/beyond-all-reason/RecoilEngine.git",
        "tag", "2026.07.04", cwd=src)
    run("git", "submodule", "update", "--init", "--recursive", "--depth", "1", "--jobs", args.j,
        "--", "rts/lib", "tools/pr-downloader", cwd=src)
    shader("glslang", work, "https://github.com/KhronosGroup/glslang.git", GLSLANG,
           ["-DENABLE_GLSLANG_BINARIES=OFF", "-DENABLE_OPT=OFF", "-DENABLE_HLSL=OFF", "-DGLSLANG_TESTS=OFF"], args.j)
    shader("cross", work, "https://github.com/KhronosGroup/SPIRV-Cross.git", SPIRV_CROSS,
           ["-DSPIRV_CROSS_CLI=OFF", "-DSPIRV_CROSS_ENABLE_TESTS=OFF", "-DSPIRV_CROSS_ENABLE_HLSL=OFF",
            "-DSPIRV_CROSS_ENABLE_MSL=OFF", "-DSPIRV_CROSS_ENABLE_CPP=OFF", "-DSPIRV_CROSS_ENABLE_REFLECT=OFF",
            "-DSPIRV_CROSS_ENABLE_C_API=OFF"], args.j)

    run("embuilder", "build", "zlib", "freetype", "sdl2")
    probe = work / "warm.c"
    probe.write_text("int main(void) { return 0; }\n")
    run("emcc", probe, "-pthread", "-fwasm-exceptions", "-sSUPPORT_LONGJMP=wasm", "-sUSE_FREETYPE=1",
        "-sUSE_ZLIB=1", "-sUSE_SDL=2", "-sUSE_OGG=1", "-sUSE_VORBIS=1", "-o", work / "warm.js")
    em = Path(shutil.which("emcc")).resolve().parent
    sysroot = Path(os.environ.get("EM_CACHE", em / "cache")) / "sysroot"
    libs = sysroot / "lib/wasm32-emscripten"
    run("emcmake", "cmake", "-S", src, "-B", out, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5", "-DCMAKE_NINJA_FORCE_RESPONSE_FILE=ON",
        "-DBUILD_spring-legacy=OFF", "-DBUILD_spring-dedicated=OFF", "-DUSE_MIMALLOC=OFF",
        "-DNO_SOUND=ON", "-DAI_TYPES=NONE", f"-DSDL2_INCLUDE_DIRS={sysroot / 'include/SDL2'}",
        "-DSDL2_LIBRARIES=SDL2", f"-DSDL2_LIBRARY={libs / 'libSDL2-mt.a'}",
        f"-DZLIB_LIBRARY_RELEASE={libs / 'libz.a'}", f"-DCMAKE_PREFIX_PATH={work / 'shaders'}")
    run("cmake", "--build", out, "--target", "engine-web", "-j", args.j)
    stage(out, src)


if __name__ == "__main__":
    main()
