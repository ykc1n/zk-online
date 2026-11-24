const decoder = new TextDecoder();

export async function readDemo(file) {
  const magic = new Uint8Array(await file.slice(0, 2).arrayBuffer());
  let stream = file.stream();
  if (magic[0] === 0x1f && magic[1] === 0x8b)
    stream = stream.pipeThrough(new DecompressionStream("gzip"));
  const reader = stream.getReader();
  let remaining = new Uint8Array();
  async function read(size) {
    const bytes = new Uint8Array(size);
    let pos = 0;
    while (pos < size) {
      if (!remaining.length) {
        const chunk = await reader.read();
        if (chunk.done)
          throw new Error("The replay ends before its start script.");
        remaining = chunk.value;
      }
      const count = Math.min(remaining.length, size - pos);
      bytes.set(remaining.subarray(0, count), pos);
      remaining = remaining.subarray(count);
      pos += count;
    }
    return bytes;
  }
  try {
    const header = await read(352);
    const view = new DataView(header.buffer);
    if (decoder.decode(header.subarray(0, 16)) !== "spring demofile\0")
      throw new Error("Choose a Spring .sdfz or .sdf replay.");
    if (view.getUint32(16, true) !== 5 || view.getUint32(20, true) !== 352)
      throw new Error("This demo format needs a different engine.");
    const length = view.getInt32(304, true);
    if (length <= 0 || length > 8 * 1024 * 1024)
      throw new Error("The replay start script is missing or too large.");
    const script = decoder.decode(await read(length));
    const field = (key) =>
      script
        .match(
          new RegExp("(?:^|[;{}\\n])\\s*" + key + "\\s*=\\s*([^;]+);", "i"),
        )?.[1]
        .trim();
    const game = field("gametype"),
      map = field("mapname");
    if (!game || !map)
      throw new Error("The replay does not identify its game and map.");
    return {
      engine: decoder.decode(header.subarray(24, 280)).split("\0")[0],
      game,
      map,
    };
  } finally {
    await reader.cancel().catch(() => {});
  }
}

export function startScript({game, ai, sides}, map) {
  if ([game, map, ai, ...sides].some((value) => !value || /[;{}\[\]\r\n]/.test(value)))
    throw new Error("Invalid map or game name.");
  return `[GAME]
{
  GameType=${game};
  MapName=${map};
  IsHost=1;
  HostIP=127.0.0.1;
  HostPort=0;
  MyPlayerName=Player;
  StartPosType=2;
  [PLAYER0] { Name=Player; Team=0; Spectator=0; }
  [AI0] { Name=${ai}; ShortName=${ai}; Team=1; Host=0; }
  [TEAM0] { TeamLeader=0; AllyTeam=0; Side=${sides[0]}; RGBColor=0.22 0.66 1; }
  [TEAM1] { TeamLeader=0; AllyTeam=1; Side=${sides[1]}; RGBColor=1 0.25 0.1; }
  [ALLYTEAM0] { NumAllies=0; StartRectLeft=0; StartRectRight=0.25; StartRectTop=0; StartRectBottom=1; }
  [ALLYTEAM1] { NumAllies=0; StartRectLeft=0.75; StartRectRight=1; StartRectTop=0; StartRectBottom=1; }
}
`;
}
