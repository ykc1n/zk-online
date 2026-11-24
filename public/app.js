import { readDemo, startScript } from "./demo.js";
const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
let runtime,
  busy = false,
  running = false;
const history = [];
let scheduled = false;
let engineFailure = "";
function log(line) {
  history.push(String(line));
  if (history.length > 1024) history.splice(0, 256);
  if ($("diagnostics").open && !scheduled) {
    scheduled = true;
    setTimeout(() => {
      $("log").textContent = history.join("\n");
      scheduled = false;
    }, 350);
  }
}
$("diagnostics").ontoggle = () => {
  if ($("diagnostics").open) $("log").textContent = history.join("\n");
};
function status(message, error = false) {
  $("status").textContent = message;
  $("status").parentElement.classList.toggle("error", error);
}
function fail(error) {
  log(error.message || String(error));
  $("progress").hidden = true;
  status(error.message || String(error), true);
}
async function json(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Content request failed.");
  return data;
}
async function fileAt(root, path) {
  const parts = path.split("/");
  let dir = root;
  for (const part of parts.slice(0, -1))
    dir = await dir.getDirectoryHandle(part, { create: true });
  return dir.getFileHandle(parts.at(-1), { create: true });
}
async function write(root, path, data) {
  const writer = await (await fileAt(root, path)).createWritable();
  try {
    await writer.write(data);
    await writer.close();
  } catch (err) {
    await writer.abort().catch(() => {});
    throw err;
  }
}
async function install(root, asset, done, total) {
  const file = await fileAt(root, asset.path);
  const marker = await fileAt(
    root,
    ".webspring/" + encodeURIComponent(asset.path),
  );
  if (
    (await file.getFile()).size === asset.size &&
    (await (await marker.getFile()).text()) === asset.id
  )
    return;
  const res = await fetch(asset.url);
  if (!res.ok) throw new Error("Download failed for " + asset.path);
  let size = 0;
  const meter = new TransformStream({
    transform(chunk, controller) {
      size += chunk.byteLength;
      $("progress").value = (done + size) / total;
      controller.enqueue(chunk);
    },
    flush() {
      if (size !== asset.size)
        throw new Error(
          "Download was interrupted. Open the match again to retry.",
        );
    },
  });
  await res.body.pipeThrough(meter).pipeTo(await file.createWritable());
  const writer = await marker.createWritable();
  await writer.write(asset.id);
  await writer.close();
}
function diagnostics(line) {
  log(line);
  const fatal = String(line).match(/Fatal:.*?errorMsg="(.*?)" msgCaption=/);
  if (fatal) {
    engineFailure = fatal[1];
    fail(new Error(engineFailure));
  }
  if (engineFailure) return;
  if (String(line).includes("End of demo reached")) {
    status("Replay finished.");
    return;
  }
  if (String(line).includes("Beginning demo playback")) {
    status(
      "Replay loaded · Use Skip pregame in the game to jump to deployment.",
    );
    return;
  }
  if (/PreGame::AddModArchivesToVFS/.test(line))
    status("Reading game archives…");
  const stage = String(line).match(
    /\[LoadScreen::SetLoadMessage\] text="(.*)"/i,
  );
  if (stage) status(stage[1]);
  if (
    /Beginning demo playback|GameID:|Game has started|GameStartPlaying|\[Game::StartPlaying\]/i.test(
      line,
    )
  ) {
    status(
      "In session · Click the game for controls. Esc releases the pointer.",
    );
  }
  if (/DESYNC WARNING|DemoSync.*\b[1-9]\d* mismatched/i.test(line))
    status("Replay sync mismatch. See the engine log.", true);
}
async function launch(file) {
  if (busy || !runtime) return;
  busy = true;
  const keepLock = new Promise((resolve) => {
    window.addEventListener("pagehide", resolve, { once: true });
  });
  try {
    await navigator.locks.request(
      "webspring-engine",
      { ifAvailable: true },
      async (lock) => {
        if (!lock)
          throw new Error(
            "Close the running zk-online session in the other tab first.",
          );
        if (!runtime.ready)
          throw new Error(
            "The server is missing the Recoil browser build. See the project README.",
          );
        const meta = file
          ? await readDemo(file)
          : { game: runtime.game, map: $("map").value.trim() };
        if (file && meta.engine !== runtime.engine)
          throw new Error(
            `This demo needs Recoil ${meta.engine}. This player runs ${runtime.engine}.`,
          );
        const script = file ? null : startScript(meta.game, meta.map);
        $("kind").textContent = file ? "REPLAY" : "SKIRMISH · CAI";
        $("match").textContent = meta.map;
        $("launcher").hidden = true;
        $("session").hidden = false;
        $("diagnostics").hidden = false;
        $("progress").hidden = false;
        $("progress").removeAttribute("value");
        status("Resolving " + meta.game + " and " + meta.map + "…");
        const getAsset = (kind, name) =>
          json("/api/content?" + new URLSearchParams({ kind, name }));
        const [game, map] = await Promise.all([
          getAsset("game", meta.game),
          getAsset("map", meta.map),
        ]);
        const assets = [...runtime.files, game, map];
        const root = await navigator.storage.getDirectory();
        const total = assets.reduce((n, asset) => n + asset.size, 0);
        let done = 0;
        $("progress").max = 1;
        for (const asset of assets) {
          status(
            "Preparing " +
              (asset === game
                ? meta.game
                : asset === map
                  ? meta.map
                  : asset.path) +
              "…",
          );
          await install(root, asset, done, total);
          done += asset.size;
          $("progress").value = done / total;
        }
        const entry = file ? "write/upload.sdfz" : "write/skirmish.txt";
        await write(root, entry, file || script);
        await root.getDirectoryHandle("shadercache", { create: true });
        await write(
          root,
          "mtimes.tsv",
          assets.map((a) => "1700000000\t" + a.path).join("\n") + "\n",
        );
        const settings = {
          Fullscreen: 0,
          WindowBorderless: 1,
          XResolutionWindowed: 1280,
          YResolutionWindowed: 720,
          WorkerThreadCount: 4,
          VFSCacheArchiveFiles: 0,
          UseLuaMemPools: 0,
          TextureMemPoolSize: 0,
          ROAM: 0,
          SMFTextureStreaming: 1,
          Shadows: 0,
          Water: 0,
          LoadingMT: 0,
          VSync: 0,
          ForceSwapBuffers: 0,
          MSAALevel: 0,
          HangTimeout: 0,
          AdvMapShading: 1,
        };
        await write(
          root,
          "write/springsettings.cfg",
          Object.entries(settings)
            .map(([key, val]) => key + " = " + val)
            .join("\n") + "\n",
        );
        $("progress").hidden = true;
        status("Starting Recoil · Loading the battlefield…");
        window.Module = {
          canvas,
          locateFile: (name) =>
            "/engine/" + name + "?build=" + encodeURIComponent(runtime.build),
          arguments: [
            "--isolation-dir",
            "/recoil",
            "--write-dir",
            "/recoil/write",
            "/recoil/" + entry,
          ],
          recoilEnv: {
            SPRING_DATADIR: "/recoil/write:/recoil",
            SPRING_WRITEDIR: "/recoil/write",
            RECOIL_WEB_SHADER_CACHE: "/recoil/shadercache",
          },
          print: diagnostics,
          printErr: diagnostics,
          onAbort: (reason) =>
            fail(
              new Error(
                engineFailure ||
                  reason ||
                  "Recoil stopped. See the engine log.",
              ),
            ),
          onExit: (code) =>
            status(
              code
                ? engineFailure ||
                    "Engine exited with code " + code + ". See the engine log."
                : "Session finished.",
              !!code,
            ),
        };
        const loader = document.createElement("script");
        loader.src =
          "/engine/spring-web.js?build=" + encodeURIComponent(runtime.build);
        await new Promise((resolve, reject) => {
          loader.onload = resolve;
          loader.onerror = () =>
            reject(new Error("Could not load the Recoil engine."));
          document.body.append(loader);
        });
        running = true;
        canvas.focus({ preventScroll: true });
        await keepLock;
      },
    );
  } catch (error) {
    if (!$("session").hidden) $("diagnostics").hidden = false;
    fail(error);
    busy = false;
    $("demo").value = "";
  }
}
function mode(play) {
  $("play").hidden = !play;
  $("watch").hidden = play;
  $("playMode").setAttribute("aria-pressed", play);
  $("watchMode").setAttribute("aria-pressed", !play);
}
$("watchMode").onclick = () => mode(false);
$("playMode").onclick = () => mode(true);
$("demo").onchange = () => {
  if ($("demo").files.length) launch($("demo").files[0]);
};
$("skirmish").onsubmit = (e) => {
  e.preventDefault();
  launch(null);
};
$("leave").onclick = () => location.reload();
$("fullscreen").onclick = () => $("screen").requestFullscreen().catch(fail);
const launcher = $("launcher");
launcher.ondragover = (e) => {
  e.preventDefault();
  launcher.classList.add("drag");
};
launcher.ondragleave = () => launcher.classList.remove("drag");
launcher.ondrop = (e) => {
  e.preventDefault();
  launcher.classList.remove("drag");
  if (e.dataTransfer.files.length) launch(e.dataTransfer.files[0]);
};
canvas.oncontextmenu = (e) => e.preventDefault();
canvas.onwheel = (e) => e.preventDefault();
canvas.onmousedown = (e) => {
  if (e.button === 1) e.preventDefault();
  if (running && !document.pointerLockElement)
    canvas.requestPointerLock()?.catch(() => {});
};
try {
  const architecture = await navigator.userAgentData?.getHighEntropyValues?.([
    "bitness",
    "wow64",
  ]);
  if (architecture?.wow64 || architecture?.bitness === "32") {
    throw new Error(
      "Zero-K needs a 64-bit browser. Open this address in 64-bit Edge or Chrome.",
    );
  }
  if (
    !crossOriginIsolated ||
    !navigator.storage?.getDirectory ||
    !HTMLCanvasElement.prototype.transferControlToOffscreen ||
    !document.createElement("canvas").getContext("webgl2")
  ) {
    throw new Error(
      "Open this page in desktop Chrome or Edge with WebGL2 enabled, using HTTPS or localhost and cross-origin isolation.",
    );
  }
  runtime = await json("/api/runtime");
  $("map").value = runtime.map;
  $("version").textContent = runtime.engine;
  if (!runtime.ready)
    throw new Error("The Recoil build is missing on this server.");
  status(
    "Ready · Game and map files are cached in this browser on first launch.",
  );
} catch (error) {
  fail(error);
  $("demo").disabled = true;
  $("skirmish").querySelector("button").disabled = true;
}
