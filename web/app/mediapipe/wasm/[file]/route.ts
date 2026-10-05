/* Раздача WASM-рантайма MediaPipe с собственного origin (пакет 6): телефон в Wi-Fi ноутбука
   не зависит от CDN, а service worker может кэшировать файлы как обычную статику.
   Файлы берутся из node_modules/@mediapipe/tasks-vision/wasm — в репозитории их нет. */

import { createReadStream, statSync } from "node:fs";
import { join } from "node:path";
import { Readable } from "node:stream";

import { NextResponse } from "next/server";

const ALLOWED = new Set([
  "vision_wasm_internal.js",
  "vision_wasm_internal.wasm",
  "vision_wasm_nosimd_internal.js",
  "vision_wasm_nosimd_internal.wasm",
  "vision_wasm_module_internal.js",
  "vision_wasm_module_internal.wasm",
]);

// Next 15: params приходят промисом; ответ и так помечен immutable-кэшем на год
export async function GET(_req: Request, { params }: { params: Promise<{ file: string }> }) {
  const { file: name } = await params;
  if (!ALLOWED.has(name)) return new NextResponse("Not found", { status: 404 });
  const path = join(process.cwd(), "node_modules", "@mediapipe", "tasks-vision", "wasm", name);
  let size: number;
  try {
    size = statSync(path).size;
  } catch {
    return new NextResponse("Not found", { status: 404 });
  }
  const stream = Readable.toWeb(createReadStream(path)) as ReadableStream;
  return new NextResponse(stream, {
    headers: {
      "Content-Type": name.endsWith(".wasm") ? "application/wasm" : "text/javascript; charset=utf-8",
      "Content-Length": String(size),
      "Cache-Control": "public, max-age=31536000, immutable",
    },
  });
}
