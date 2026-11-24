"""Resolve Recoil game releases and maps for the browser engine."""
from concurrent.futures import ThreadPoolExecutor
import contextlib
import gzip
import hashlib
import http.client
import io
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile

RAPID = "https://repos.springrts.com/zk"
BAR_RAPID = "https://repos-cdn.beyondallreason.dev/byar"
MAPS = "https://springfiles.springrts.com"
DEFAULT_GAME = "Zero-K v1.14.8.0"
DEFAULT_MAP = "TitanDuel 2.2"
PRESETS = {
    "zk": {"title": "Zero-K", "game": DEFAULT_GAME, "map": DEFAULT_MAP,
           "ai": "CAI", "sides": ["Robots", "Robots"]},
    "bar": {"title": "Beyond All Reason", "game": "Beyond All Reason test-31943-6cd6caa",
            "map": "All That Glitters v2.2", "ai": "SimpleAI", "sides": ["Armada", "Cortex"]},
}


def game_id(name):
    for key, preset in PRESETS.items():
        if re.fullmatch(re.escape(preset["title"]) + r" [a-zA-Z0-9._+:-]+", name, re.I):
            return key
    raise ValueError("Choose a versioned Zero-K or Beyond All Reason release.")


def read_url(url, data=None):
    return urllib.request.urlopen(url, data=data, timeout=120)


def exact(stream, count):
    data = stream.read(count)
    if len(data) != count:
        raise ValueError("The content server returned an incomplete file. Try again.")
    return data


def package_index(package):
    entries = []
    digest = hashlib.md5()
    with gzip.GzipFile(fileobj=io.BytesIO(package)) as index:
        while length := index.read(1):
            name = exact(index, length[0])
            checksum = exact(index, 16)
            _, size = struct.unpack(">II", exact(index, 8))
            digest.update(hashlib.md5(name).digest() + checksum)
            entries.append((name.decode("utf-8"), checksum.hex(), size))
    return digest.hexdigest(), entries


def bar_files(entries, install):
    # BAR distributes individual gzip pool objects on a CDN. Reuse TLS
    # connections and bound the number of results waiting for the ZIP writer.
    url = urllib.parse.urlsplit(BAR_RAPID)
    worker = threading.local()
    connections = []

    def fetch(entry):
        _, key, size = entry
        relative = f"pool/{key[:2]}/{key[2:]}.gz"
        if install and (install / relative).is_file():
            return (install / relative).read_bytes()
        if not hasattr(worker, "connection"):
            worker.connection = http.client.HTTPSConnection(url.netloc, timeout=120)
            connections.append(worker.connection)
        connection = worker.connection
        for attempt in range(3):
            try:
                connection.request("GET", f"{url.path}/{relative}")
                with connection.getresponse() as response:
                    if response.status != 200:
                        raise OSError(f"HTTP {response.status}")
                    return response.read(size + size // 100 + 4096)
            except (OSError, http.client.HTTPException) as error:
                connection.close()
                if attempt == 2:
                    raise OSError(f"BAR download failed for {key}: {error}") from error
                time.sleep(attempt + 1)

    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            for offset in range(0, len(entries), 64):
                yield from pool.map(fetch, entries[offset:offset + 64])
    finally:
        for connection in connections:
            connection.close()


def streamed_files(package, entries, install):
    local = {}
    requested = bytearray(len(entries) // 8 + 1)
    for i, (_, key, _) in enumerate(entries):
        file = install / "pool" / key[:2] / (key[2:] + ".gz") if install else None
        if file and file.is_file():
            local[i] = file
        else:
            requested[i // 8] |= 1 << (i % 8)

    stream = (read_url(f"{RAPID}/streamer.cgi?{package}", gzip.compress(requested))
              if any(requested) else contextlib.nullcontext())
    with stream as incoming:
        for i, (_, _, size) in enumerate(entries):
            if i in local:
                yield local[i].read_bytes()
            else:
                length = int.from_bytes(exact(incoming, 4), "big")
                if not 0 < length <= size + size // 100 + 4096:
                    raise ValueError("Invalid Rapid stream entry length.")
                yield exact(incoming, length)


def package_game(name, dest, install):
    bar = game_id(name) == "bar"
    repo = BAR_RAPID if bar else RAPID
    with read_url(f"{repo}/versions.gz") as response:
        versions = gzip.decompress(response.read()).decode().splitlines()
    package = next((row[1] for line in versions if len(row := line.split(",", 3)) == 4
                    and row[3].casefold() == name.casefold()), None)
    if not package or not re.fullmatch(r"[a-f0-9]{32}", package):
        raise ValueError(f"The Rapid repository has no release named {name}.")
    with read_url(f"{repo}/packages/{package}.sdp") as response:
        digest, entries = package_index(response.read())
    if digest != package:
        raise ValueError("The Rapid package index failed its checksum.")

    files = bar_files(entries, install) if bar else streamed_files(package, entries, install)
    with contextlib.closing(files), zipfile.ZipFile(
        dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6 if bar else 1
    ) as archive:
        for (path, key, size), compressed in zip(entries, files, strict=True):
            contents = gzip.decompress(compressed)
            if len(contents) != size or hashlib.md5(contents).hexdigest() != key:
                raise ValueError(f"Rapid integrity check failed for {path}.")
            archive.writestr(path, contents)


def fetch_map(name, dest_dir, install):
    # The engine's scanner knows internal map names even when SpringFiles does
    # not list the archive. Read its data as text, without executing Lua.
    if install:
        caches = list((install / "cache").glob("ArchiveCache*.lua"))
        caches.extend(install.glob("engine/*/*/cache/ArchiveCache*.lua"))
        for cache in sorted(caches, key=lambda p: p.stat().st_mtime, reverse=True):
            source = cache.read_text(encoding="utf-8", errors="replace")
            for entry in source.split("\n\t\t{"):
                outer, _, meta = entry.partition("archivedata = {")
                filename = re.search(r'^\s*name = "([^"]+\.(?:sd7|sdz))",', outer, re.M | re.I)
                title = re.search(r'^\s*name = "([^"]+)",', meta, re.M)
                if not (filename and title and title[1].casefold() == name.casefold()):
                    continue
                file = install / "maps" / Path(filename[1]).name
                if file.is_file():
                    with file.open("rb") as src:
                        dest = dest_dir / (hashlib.file_digest(src, "md5").hexdigest() + file.suffix.lower())
                    if not dest.exists():
                        with tempfile.NamedTemporaryFile(dir=dest_dir, delete=False) as out:
                            draft = Path(out.name)
                        try:
                            shutil.copyfile(file, draft)
                            draft.replace(dest)
                        finally:
                            draft.unlink(missing_ok=True)
                    return dest
    query = urllib.parse.urlencode({"category": "map", "springname": name})
    with read_url(f"{MAPS}/json.php?{query}") as response:
        results = json.load(response)
    match = next((r for r in results if r["springname"].casefold() == name.casefold()), None)
    if not match:
        raise ValueError(f"SpringFiles has no map named {name}.")
    filename = match["filename"]
    if Path(filename).name != filename or Path(filename).suffix.lower() not in (".sd7", ".sdz"):
        raise ValueError("Unexpected map archive name.")
    dest = dest_dir / (match["md5"] + Path(filename).suffix.lower())
    if not re.fullmatch("[a-f0-9]{32}", match["md5"]):
        raise ValueError("Invalid map digest.")
    if not dest.exists():
        local = install / "maps" / filename if install else None
        with tempfile.NamedTemporaryFile(dir=dest_dir, delete=False) as temp:
            draft = Path(temp.name)
        try:
            with (local.open("rb") if local and local.is_file() else
                  read_url(f"{MAPS}/files/maps/{urllib.parse.quote(filename)}")) as src, draft.open("wb") as out:
                shutil.copyfileobj(src, out)
            with draft.open("rb") as src:
                if hashlib.file_digest(src, "md5").hexdigest() != match["md5"]:
                    raise ValueError(f"Map checksum failed for {name}.")
            draft.replace(dest)
        finally:
            draft.unlink(missing_ok=True)
    return dest


def prepare(kind, name, cache, install=None):
    cache.mkdir(parents=True, exist_ok=True)
    index = cache / (hashlib.sha256((kind + "\n" + name.casefold()).encode()).hexdigest() + ".json")
    if index.is_file():
        result = json.loads(index.read_text())
        file = cache / result["file"]
        if file.is_file() and file.stat().st_size == result["size"]:
            return result
    if kind == "map":
        archive = fetch_map(name, cache, install)
    else:
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as temp:
            draft = Path(temp.name)
        try:
            package_game(name, draft, install)
            with draft.open("rb") as src:
                archive = cache / (hashlib.file_digest(src, "sha256").hexdigest() + ".sdz")
            draft.replace(archive)
        finally:
            draft.unlink(missing_ok=True)
    result = {"file": archive.name, "size": archive.stat().st_size,
              "path": ("maps/" if kind == "map" else "games/") + archive.name}
    pending = index.with_suffix(".tmp")
    pending.write_text(json.dumps(result))
    pending.replace(index)
    return result
