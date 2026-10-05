import { createReadStream, statSync } from "node:fs";
import { join } from "node:path";
import { Readable } from "node:stream";
import { NextResponse } from "next/server";
const ALLOWED = new Set(["ort-wasm-simd-threaded.wasm", "ort-wasm-simd-threaded.mjs"]);
export async function GET(_req: Request, { params }: { params: Promise<{ file: string }> }) {
  const { file } = await params;
  if (!ALLOWED.has(file)) return new NextResponse("Not found", { status: 404 });
  const path = join(process.cwd(), "node_modules", "onnxruntime-web", "dist", file);
  let size: number;
  try { size = statSync(path).size; } catch { return new NextResponse("Not found", { status: 404 }); }
  return new NextResponse(Readable.toWeb(createReadStream(path)) as ReadableStream, { headers: {
    "Content-Type": file.endsWith(".wasm") ? "application/wasm" : "text/javascript; charset=utf-8",
    "Content-Length": String(size), "Cache-Control": "public, max-age=31536000, immutable",
  } });
}
