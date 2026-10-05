import { API_URL, ApiError, api, currentUser } from "./api";
import type { Detection } from "./dms/rules";

export type CameraEventBody = {
  uuid: string; type: Detection["type"]; severity: Detection["severity"];
  confidence: number; ts: string; lat: number | null; lon: number | null;
  gps_valid: boolean; speed_kmh: number | null; value: number | null; note: string;
  detector?: "face_rules" | "hand_gesture" | "object_model";
  model_run_id?: string; model_sha256?: string;
};
export type QueuedCameraEvent = {
  key: string; owner: string; body: CameraEventBody; savedAt: number;
  rejected?: string;
};
export const CAMERA_QUEUE_CHANGED = "dg-camera-queue-changed";
const DB = "dg-camera-events";
const STORE = "events";

export function cameraOwner(): string | null {
  const user = currentUser();
  return user?.role === "driver" && Number.isSafeInteger(user.id) && user.id > 0
    ? `${API_URL}|${user.id}` : null;
}

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE, { keyPath: "key" }).createIndex("owner", "owner");
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    req.onblocked = () => reject(new Error("Закройте другие вкладки DriverGuard и повторите."));
  });
}

async function transaction<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise<T>((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const request = run(tx.objectStore(STORE));
    tx.oncomplete = () => { db.close(); resolve(request.result); };
    tx.onerror = tx.onabort = () => { db.close(); reject(tx.error ?? new Error("Хранилище телефона недоступно")); };
  });
}

function notify(owner: string, synced: string[] = []) {
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new CustomEvent(CAMERA_QUEUE_CHANGED, { detail: { owner, synced } }));
  }
}

/** Resolve only after the entire transaction commits, before any network send. */
export async function saveCameraEvents(owner: string, bodies: CameraEventBody[]): Promise<void> {
  if (!owner || !bodies.length) return;
  await transaction("readwrite", (store) => {
    let request!: IDBRequest<IDBValidKey>;
    for (const body of bodies) {
      request = store.put({ key: `${owner}|${body.uuid}`, owner, body, savedAt: Date.now() } satisfies QueuedCameraEvent);
    }
    return request;
  });
  notify(owner);
}

export async function listCameraEvents(owner = cameraOwner()): Promise<QueuedCameraEvent[]> {
  if (!owner) return [];
  const rows = await transaction("readonly", (store) => store.index("owner").getAll(owner));
  return (rows as QueuedCameraEvent[]).sort((a, b) => a.body.ts.localeCompare(b.body.ts));
}

let inFlight: Promise<void> | null = null;

export function flushCameraEvents(): Promise<void> {
  if (inFlight) return inFlight;
  inFlight = flush().finally(() => { inFlight = null; });
  return inFlight;
}

async function flush(): Promise<void> {
  const owner = cameraOwner();
  if (!owner || (typeof navigator !== "undefined" && navigator.onLine === false)) return;
  let batchSize = 20;
  for (let attempt = 0; attempt < 25; attempt++) {
    const batch = (await listCameraEvents(owner)).filter((row) => !row.rejected).slice(0, batchSize);
    // An account may have changed while IndexedDB was opening.
    if (!batch.length || cameraOwner() !== owner) return;
    try {
      const result = await api<{ accepted: number; duplicates: number }>("/drivers/me/camera-events", {
        method: "POST", body: JSON.stringify(batch.map((row) => row.body)),
        signal: AbortSignal.timeout(15_000),
      }, false, Number(owner.slice(owner.lastIndexOf("|") + 1)));
      if (!Number.isInteger(result.accepted) || !Number.isInteger(result.duplicates)
          || result.accepted < 0 || result.duplicates < 0
          || result.accepted + result.duplicates !== batch.length) return;
      await transaction("readwrite", (store) => {
        let request!: IDBRequest<undefined>;
        for (const row of batch) request = store.delete(row.key);
        return request;
      });
      notify(owner, batch.map((row) => row.body.uuid));
      batchSize = 20;
    } catch (error) {
      if (error instanceof ApiError && [400, 413, 415, 422].includes(error.status)) {
        // Isolate invalid rows; one bad item must not discard the rest of a batch.
        if (batch.length > 1) { batchSize = 1; continue; }
        await transaction("readwrite", (store) => store.put({ ...batch[0], rejected: error.message }));
        notify(owner);
        continue;
      }
      // Offline, expired login, missing assignment, timeout, rate limit and 5xx are retryable.
      return;
    }
  }
}
