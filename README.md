# zk-online

zk-online runs Zero-K and Beyond All Reason inside a desktop browser using the Recoil engine compiled to WebAssembly. The simulation runs on a pthread worker and renders to an OffscreenCanvas through WebGL2. A small Python server supplies the engine, games, and maps.

## Run

Use Python 3.11 or newer. From this directory, run:

```sh
python server.py
```

Open **http://127.0.0.1:8080** in 64-bit desktop Edge or Chrome with hardware acceleration enabled. Zero-K can exceed the memory available to a 32-bit browser tab. The included engine build is based on Recoil **2026.07.04**.

- **Watch replay** accepts a local `.sdfz` or uncompressed `.sdf`. Choose a file or drop it on the launcher. The browser reads the header, requests the recorded game version and map by name, and passes the original demo to Recoil. The demo stays in the browser. Zero-K's replay controls in the upper right let you skip pregame, pause, and change playback speed.
- **[Beyond All Reason skirmish](http://127.0.0.1:8080/?game=bar)** starts a local match against SimpleAI on All That Glitters v2.2 using release `test-31943-6cd6caa`. Click **Start skirmish**, choose your deployment point, then click **Ready**. Select your commander and right-click the terrain to move. BAR's native BARbarian AI requires a desktop engine.
- **[Zero-K skirmish](http://127.0.0.1:8080/?game=zk)** starts a local match against CAI on TitanDuel 2.2. You can enter a different map name for either game. Click inside the game for mouse and keyboard control. Esc releases the mouse.
- **Leave session** returns to the launcher. The browser retains downloaded assets in origin-private storage for the next match.

The first launch transfers about 2.1 GB for BAR or 650–700 MB for Zero-K. Allow time for the server to package the game, then for the browser to scan it and compile shaders. The engine log is available below the canvas. The player supports local skirmishes and replays.

## Game content

The server looks up the exact release in the game's Rapid repository, verifies the package index and each file, and packages the original contents into an engine-readable SDZ. It finds maps by internal name in a local archive cache or in SpringFiles. Generated archives stay in `public/content/`. A server with an empty cache needs internet access.

The server checks the default Windows Zero-K Steam install and BAR application data directories. To reuse content from other installations, pass either or both paths.

```sh
python server.py --install "/path/to/Zero-K" --bar-install "/path/to/Beyond All Reason/data"
```

Replays need the recorded engine version and available game and map assets. A replay recorded by an older Spring/Recoil release requires a matching engine port. For remote hosting, serve the Python app behind HTTPS and preserve its cross-origin isolation headers. Both shared memory and OffscreenCanvas are required.

## Verification

In a Chromium browser on Windows, BAR loaded SimpleAI for the Cortex team, deployed an Armada commander, accepted a move order, and built a wind turbine. The browser then opened the resulting demo from the replay picker and played it to frame 2,923. Recoil reported 31 matching checksums and zero mismatches at frame 1,800. BAR's health-bar widget selected its WebGL-compatible fallback shader.

In 64-bit Edge on Windows, a 12-minute 28-second Zero-K v1.14.8.0 demo on Isidis crack 1.1 played through its recorded end. Recoil reported 1,128 matching simulation checksums and zero mismatches. A separate TitanDuel 2.2 skirmish loaded CAI, accepted a Guardian commander selection and deployment, and acknowledged a browser-issued move order.

## Rebuild Recoil

The bundled executable can be rebuilt using Git, Python, CMake 3.27+, Ninja, 7-Zip and an activated **Emscripten 7.0.0** environment. Put those programs on PATH. Use a work directory with several GB free.

```sh
python tools/build_engine.py --work /path/to/zk-online-build -j 6
```

The script fetches the pinned engine and submodules, applies the RLE bitmap decoder patch for older Zero-K textures, builds glslang and SPIRV-Cross for WASM, prepares the Emscripten ports, builds the `engine-web` target, and copies the JS loader, WASM, engine archives and font into `public/engine/`.

## Sources

- [Recoil browser port, exact source revision](https://github.com/SgtMetz/RecoilEngine/tree/71b7f5713e2be411c34b5900aa7a7a87638ce399). The engine is GPL-2.0-or-later. Engine notices and font credits are included in `public/engine/`.
- [Upstream browser harness and engineering notes](https://github.com/SgtMetz/beyond-all-reason-web). zk-online supplies the Zero-K launcher and content resolution.
- [Zero-K](https://github.com/ZeroK-RTS/Zero-K), [Rapid](https://repos.springrts.com/zk/) and [SpringFiles](https://springfiles.springrts.com/). Game and map archives retain their original content and licensing.
- [Zero-K Steam library artwork](https://cdn.akamai.steamstatic.com/steam/apps/334920/library_hero.jpg).
- [Beyond All Reason game and Armada loading artwork](https://github.com/beyond-all-reason/Beyond-All-Reason/tree/6cd6caa25da9365bf24e3a407a6ccb2e74eb2fef), [BAR Rapid index](https://repos-cdn.beyondallreason.dev/byar/versions.gz).
