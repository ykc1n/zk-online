"""Resolve exact Zero-K releases and maps for the browser engine."""
import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile
import urllib.parse
import urllib.request
import zipfile

RAPID = "https://repos.springrts.com/zk"
MAPS = "https://springfiles.springrts.com"
DEFAULT_GAME = "Zero-K v1.14.8.0"
DEFAULT_MAP = "TitanDuel 2.2"


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


def package_game(name, dest, install):
    with read_url(f"{RAPID}/versions.gz") as response:
        versions = gzip.decompress(response.read()).decode().splitlines()
    package = next((row[1] for line in versions if len(row := line.split(",", 3)) == 4
                    and row[3].casefold() == name.casefold()), None)
    if not package or not re.fullmatch(r"[a-f0-9]{32}", package):
        raise ValueError(f"The Zero-K Rapid repository has no release named {name}.")
    with read_url(f"{RAPID}/packages/{package}.sdp") as response:
        digest, entries = package_index(response.read())
    if digest != package:
        raise ValueError("The Rapid package index failed its checksum.")

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
    with stream as incoming, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for i, (path, key, size) in enumerate(entries):
            if i in local:
                compressed = local[i].read_bytes()
            else:
                length = int.from_bytes(exact(incoming, 4), "big")
                if not 0 < length <= size + size // 100 + 4096:
                    raise ValueError("Invalid Rapid stream entry length.")
                compressed = exact(incoming, length)
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
        if not re.fullmatch(r"Zero-K [a-zA-Z0-9._+\-]+", name, re.IGNORECASE):
            raise ValueError("Choose a versioned Zero-K game release.")
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
