import { decodeObjects, letterboxGeometry, validateManifest, type ObjectBox, type ObjectManifest } from "./objects";
import type { InferenceSession } from "onnxruntime-web";

export class ObjectDetector {
  private canvas = document.createElement("canvas");
  private closed = false;
  private busy = false;
  private constructor(private session: InferenceSession, public manifest: ObjectManifest) {}
  static async create(bytes: ArrayBuffer, value: unknown): Promise<ObjectDetector> {
    const manifest = validateManifest(value);
    if (bytes.byteLength > 50 * 1024 * 1024) throw new Error("Модель больше 50 МБ.");
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
    if (hash !== manifest.sha256) throw new Error("Контрольная сумма модели не совпадает с отчётом обучения.");
    const ort = await import("onnxruntime-web/wasm");
    ort.env.wasm.numThreads = 1;
    ort.env.wasm.wasmPaths = `${location.origin}/onnx/1.22.0/`;
    const session = await ort.InferenceSession.create(bytes, { executionProviders: ["wasm"] });
    try {
      if (session.inputNames.length !== 1 || session.outputNames.length !== 1) throw new Error("Неверный формат модели.");
      const tensor = new ort.Tensor("float32", new Float32Array(3 * 640 * 640), [1, 3, 640, 640]);
      const result = await session.run({ [session.inputNames[0]]: tensor });
      try { decodeObjects(result[session.outputNames[0]].data as Float32Array, result[session.outputNames[0]].dims, 640, 640); }
      finally { tensor.dispose(); Object.values(result).forEach((t) => t.dispose()); }
      return new ObjectDetector(session, manifest);
    } catch (e) { await session.release(); throw e; }
  }
  async detect(source: HTMLVideoElement | HTMLImageElement): Promise<ObjectBox[]> {
    if (this.closed || this.busy) throw new Error("Детектор занят или закрыт.");
    this.busy = true;
    try {
      const width = source instanceof HTMLVideoElement ? source.videoWidth : source.naturalWidth;
      const height = source instanceof HTMLVideoElement ? source.videoHeight : source.naturalHeight;
      const { w, h, dx, dy } = letterboxGeometry(width, height);
      this.canvas.width = this.canvas.height = 640;
      const ctx = this.canvas.getContext("2d", { willReadFrequently: true })!;
      ctx.fillStyle = "rgb(114,114,114)"; ctx.fillRect(0, 0, 640, 640);
      ctx.drawImage(source, dx, dy, w, h);
      const pixels = ctx.getImageData(0, 0, 640, 640).data;
      const n = 640 * 640, input = new Float32Array(n * 3);
      for (let k = 0; k < n; k++) for (let c = 0; c < 3; c++) input[c * n + k] = pixels[k * 4 + c] / 255;
      const ort = await import("onnxruntime-web/wasm");
      const tensor = new ort.Tensor("float32", input, [1, 3, 640, 640]);
      let result: InferenceSession.ReturnType | undefined;
      try {
        result = await this.session.run({ [this.session.inputNames[0]]: tensor });
        const output = result[this.session.outputNames[0]];
        return decodeObjects(output.data as Float32Array, output.dims, width, height);
      } finally { tensor.dispose(); if (result) Object.values(result).forEach((t) => t.dispose()); }
    } finally {
      this.busy = false;
      if (this.closed) await this.session.release();
    }
  }
  close() { if (this.closed) return; this.closed = true; if (!this.busy) void this.session.release(); }
}

export async function loadPublishedDetector(): Promise<ObjectDetector | null> {
  const response = await fetch("/models/browser-model.json", { cache: "no-store", signal: AbortSignal.timeout(5000) });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error("Не удалось загрузить сведения о модели.");
  const manifest = validateManifest(await response.json());
  if (!manifest.model_url?.match(/^\/models\/[a-zA-Z0-9_-]+\.onnx$/)) throw new Error("Неверный адрес модели.");
  const model = await fetch(manifest.model_url, { signal: AbortSignal.timeout(60000) });
  if (!model.ok) throw new Error("Файл модели не найден.");
  return ObjectDetector.create(await model.arrayBuffer(), manifest);
}
