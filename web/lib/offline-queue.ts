/* Офлайн-очередь чек-листов (APP-8): фото и ответы лежат в IndexedDB, пока нет сети,
   и отправляются при появлении связи. Это единственное клиентское хранилище данных
   приложения, кроме токена/темы (docs/decisions.md, ШАГ 13). */

import { api, ApiError, currentUser, type ChecklistOut } from "@/lib/api";
import { t } from "@/lib/i18n";

const DB_NAME = "dg-driver";
const STORE = "checklists";

export interface PendingChecklist {
  id?: number;
  created_at: string;
  user_id?: number | null; // чей чек-лист: отправляем только под той же учёткой
  answers: Record<string, string>;
  photos: { slot: string; name: string; type: string; blob: Blob }[];
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error(t("IndexedDB недоступна")));
      return;
    }
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(STORE, mode);
        const req = run(t.objectStore(STORE));
        t.oncomplete = () => { db.close(); resolve(req.result); };
        t.onabort = () => { db.close(); reject(t.error ?? new Error("Запись отменена")); };
        t.onerror = () => { db.close(); reject(t.error ?? req.error); };
      }),
  );
}

export async function savePendingChecklist(entry: PendingChecklist): Promise<void> {
  await tx("readwrite", (s) => s.add({ ...entry, user_id: entry.user_id ?? currentUser()?.id ?? null }));
}

export async function countPendingChecklists(): Promise<number> {
  try {
    return await tx("readonly", (s) => s.count());
  } catch {
    return 0;
  }
}

/** Стандартные 7 слотов — отдельные поля формы; слоты, добавленные парком, — extra + extra_slots */
export const FIXED_SLOTS = ["front_lights", "rear_lights", "left_side", "right_side", "tires", "windshield", "under_engine"];

export function checklistFormData(entry: Pick<PendingChecklist, "answers" | "photos">): FormData {
  const fd = new FormData();
  const extraSlots: string[] = [];
  for (const p of entry.photos) {
    if (FIXED_SLOTS.includes(p.slot)) fd.append(p.slot, p.blob, p.name);
    else {
      fd.append("extra", p.blob, p.name);
      extraSlots.push(p.slot);
    }
  }
  if (extraSlots.length) fd.append("extra_slots", JSON.stringify(extraSlots));
  fd.append("answers", JSON.stringify(entry.answers));
  return fd;
}

let flushing: Promise<string[]> | null = null;

/** Отправляет накопленные чек-листы текущего пользователя. Параллельные вызовы (mount +
    событие online) делят один проход — иначе один чек-лист уходил бы дважды. */
export function flushPendingChecklists(): Promise<string[]> {
  if (!flushing) {
    flushing = flushOnce().finally(() => {
      flushing = null;
    });
  }
  return flushing;
}

async function flushOnce(): Promise<string[]> {
  let items: PendingChecklist[];
  try {
    items = await tx("readonly", (s) => s.getAll() as IDBRequest<PendingChecklist[]>);
  } catch {
    return [];
  }
  const me = currentUser()?.id ?? null;
  const messages: string[] = [];
  for (const item of items) {
    if (item.user_id != null && item.user_id !== me) continue; // чужая запись — ждёт своего входа
    try {
      const out = await api<ChecklistOut>("/checklists", { method: "POST", body: checklistFormData(item) });
      await tx("readwrite", (s) => s.delete(item.id as number));
      messages.push(`Отложенный чек-лист отправлен: ${out.verdict.replace("_", " ")}`);
    } catch (e) {
      if (e instanceof ApiError && [400, 413, 415, 422].includes(e.status)) {
        await tx("readwrite", (s) => s.delete(item.id as number)); // сервер отверг — повтор бессмыслен
        messages.push(`Отложенный чек-лист не принят: ${e.message}`);
        continue;
      }
      break; // сеть, авторизация, лимит запросов или 5xx — сохраняем фото для повтора
    }
  }
  return messages;
}
