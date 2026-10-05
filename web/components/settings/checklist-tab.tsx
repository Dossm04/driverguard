"use client";

/* Настройки → Чек-лист: какие фото снимать и какие пункты спрашивать. Каталог v2 остаётся в
   backend, парк хранит только правки (PUT /settings/checklist): скрытые слоты и пункты,
   исправленные тексты/критичность/обязательность, добавленные ракурсы и пункты. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { QueryError } from "@/components/ui/query-error";
import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import {
  api,
  type AiStatusOut,
  type AiTestOut,
  type ChecklistItemCatalog,
  type ChecklistSettingsValue,
  type ChecklistSlot,
  type ChecklistTemplateOut,
  type SettingOut,
} from "@/lib/api";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn, pluralRu } from "@/lib/utils";

const inputCls =
  "h-9 w-full rounded-btn border border-line bg-page px-2.5 text-sm font-normal focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60";
const CRIT_OPTIONS = perLang(() => [
  { value: "", label: t("не влияет") },
  { value: "attention", label: t("внимание") },
  { value: "critical", label: t("критично") },
]);

function toCompact(slots: ChecklistSlot[], items: ChecklistItemCatalog[]): ChecklistSettingsValue {
  const overrides: ChecklistSettingsValue["item_overrides"] = {};
  for (const i of items) {
    if (i.custom) continue;
    const textChanged = i.text !== i.default_text;
    const baseChanged = i.base !== i.default_base;
    const critChanged = (i.criticality ?? null) !== (i.default_criticality ?? null);
    if (textChanged || baseChanged || critChanged) {
      overrides[i.id] = {
        text: textChanged ? i.text : null,
        base: baseChanged ? i.base : null,
        criticality: critChanged ? ((i.criticality as "critical" | "attention" | null) ?? "none") : null,
      };
    }
  }
  return {
    hidden_slots: slots.filter((s) => !s.custom && !s.enabled).map((s) => s.slot),
    custom_slots: slots.filter((s) => s.custom && s.enabled).map(({ slot, label, hint }) => ({ slot, label, hint })),
    hidden_items: items.filter((i) => !i.custom && !i.enabled).map((i) => i.id),
    item_overrides: overrides,
    custom_items: items
      .filter((i) => i.custom && i.enabled)
      .map((i) => ({
        id: i.id,
        text: i.text,
        base: i.base,
        criticality: (i.criticality as "critical" | "attention" | null) ?? null,
        na_allowed: i.na_allowed,
      })),
  };
}

const PROVIDER_LABEL: Record<string, string> = perLang(() => ({
  mock: t("демо-режим (ключ не задан)"),
  openai_compat: t("alem.ai / OpenAI-совместимый API"),
  gemini: "Google Gemini",
}));

/** Карточка «ИИ-проверка фото»: кто проверяет и кнопка «Проверить ключ» (POST /checklists/ai-test). */
export function AiStatusCard({ isAdmin }: { isAdmin: boolean }) {
  useLangVersion();
  const status = useQuery({ queryKey: ["ai-status"], queryFn: () => api<AiStatusOut>("/checklists/ai-status") });
  const [result, setResult] = useState<AiTestOut | null>(null);
  const test = useMutation({
    mutationFn: () => api<AiTestOut>("/checklists/ai-test", { method: "POST" }),
    onSuccess: setResult,
  });
  const s = status.data;
  return (
    <SectionCard
      title={t("ИИ-проверка фото")}
      subtitle={t("какая модель сверяет фары, шины, стекло, зеркала, утечки и кузов")}
      action={
        isAdmin ? (
          <Button variant="outline" size="sm" disabled={test.isPending} onClick={() => test.mutate()} data-testid="ai-test">
            <Bot size={14} /> {test.isPending ? t("Проверяем…") : t("Проверить ИИ")}
          </Button>
        ) : undefined
      }
    >
      {status.isError ? (
        <QueryError error={status.error} onRetry={() => status.refetch()} />
      ) : !s ? (
        <Skeleton className="h-16" />
      ) : (
        <div className="flex flex-col gap-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", s.configured ? "bg-ok/15 text-ok" : "bg-warn/15 text-warn")}>
              {s.configured ? t("подключён") : t("демо-режим")}
            </span>
            <b>{PROVIDER_LABEL[s.provider] ?? s.provider}</b>
            {s.model && <span className="num text-mut">{s.model}{s.host ? ` · ${s.host}` : ""}</span>}
          </div>
          {s.hint && <p className="text-warn">{s.hint}</p>}
          {!s.configured && (
            <p className="text-xs text-mut">
              {t("В демо-режиме каждый чек-лист получает вердикт «допущен» без анализа фото. Для реальной проверки нужен ключ модели с картинками (alem.ai Gemma 4): OPENAI_COMPAT_BASE_URL, OPENAI_COMPAT_API_KEY, OPENAI_COMPAT_MODEL в infra/.env, затем перезапуск backend.")}
            </p>
          )}
          {test.isError && <p role="alert" className="text-danger">{test.error instanceof Error ? test.error.message : t("Проверка не удалась")}</p>}
          {result && (
            <div role="status" className={cn("rounded-btn px-3 py-2 text-sm", result.ok ? "bg-ok/10 text-ok" : "bg-danger/10 text-danger")}>
              {result.ok
                ? result.demo
                  ? t("Ответ получен, но это демо-режим: ключ не задан")
                  : t("Модель {0} ответила за {1} с — вердикт «{2}». Ключ работает.", result.model ?? "", (result.latency_ms / 1000).toFixed(1), result.verdict)
                : t("Ошибка провайдера: {0}", result.error)}
            </div>
          )}
        </div>
      )}
    </SectionCard>
  );
}

export function ChecklistTab({ isAdmin }: { isAdmin: boolean }) {
  useLangVersion();
  const toast = useToast();
  const queryClient = useQueryClient();
  const tpl = useQuery({
    queryKey: ["checklist-template"],
    queryFn: () => api<ChecklistTemplateOut>("/checklists/template"),
  });
  const [slots, setSlots] = useState<ChecklistSlot[] | null>(null);
  const [items, setItems] = useState<ChecklistItemCatalog[] | null>(null);
  useEffect(() => {
    if (tpl.data) {
      setSlots(tpl.data.slots.map((s) => ({ ...s })));
      setItems(tpl.data.items.map((i) => ({ ...i })));
    }
  }, [tpl.data]);

  const save = useMutation({
    mutationFn: (value: ChecklistSettingsValue) =>
      api<SettingOut>("/settings/checklist", { method: "PUT", body: JSON.stringify({ value }) }),
    onSuccess: (saved) => {
      toast(t("Чек-лист сохранён · версия {0}", saved.version));
      for (const k of ["settings", "checklist-template", "checklist-items", "checklist-slots", "checklists"])
        queryClient.invalidateQueries({ queryKey: [k] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось сохранить")),
  });

  if (tpl.isError) return <QueryError error={tpl.error} onRetry={() => tpl.refetch()} />;
  if (!slots || !items) return <Skeleton className="h-[320px] rounded-card" />;

  const updSlot = (idx: number, patch: Partial<ChecklistSlot>) =>
    setSlots(slots.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  const updItem = (id: string, patch: Partial<ChecklistItemCatalog>) =>
    setItems(items.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  const addSlot = () => {
    const n = slots.filter((s) => s.custom).length + 1;
    setSlots([...slots, { slot: `extra_${n}`, label: t("Ракурс {0}", n), hint: "", enabled: true, custom: true }]);
  };
  const addItem = () => {
    const used = new Set(items.filter((i) => i.custom).map((i) => i.id));
    let n = 1;
    while (used.has(`П${n}`)) n += 1;
    setItems([
      ...items,
      {
        id: `П${n}`,
        section: "П",
        section_title: t("Дополнительно (настроено парком)"),
        text: "",
        base: true,
        criticality: "attention",
        method: "answer",
        ai_key: null,
        na_allowed: false,
        enabled: true,
        custom: true,
      },
    ]);
  };
  const sections = new Map<string, ChecklistItemCatalog[]>();
  for (const i of items) sections.set(i.section_title, [...(sections.get(i.section_title) ?? []), i]);
  const enabledSlots = slots.filter((s) => s.enabled).length;
  const invalidItem = items.find((i) => i.custom && i.enabled && i.text.trim().length < 3);

  return (
    <div className="flex flex-col gap-3">
      <AiStatusCard isAdmin={isAdmin} />
      <SectionCard
        title={t("Фото для чек-листа")}
        subtitle={t("водитель снимает {0} {1}; ИИ проверяет фары, шины, стекло, зеркала, утечки и кузов по стандартным", enabledSlots, pluralRu(enabledSlots, t("ракурс"), t("ракурса"), t("ракурсов")))}
        action={<span className="num text-xs text-mut">{t("версия")}{" "}{tpl.data?.version ?? 0}</span>}
      >
        <ul className="flex flex-col gap-2" data-testid="checklist-slots">
          {slots.map((s, idx) => (
            <li key={s.slot} className="grid items-center gap-2 sm:grid-cols-[auto_1fr_2fr_auto]">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={s.enabled}
                  disabled={!isAdmin}
                  onChange={(e) => updSlot(idx, { enabled: e.target.checked })}
                  aria-label={t("Снимать: {0}", s.label)}
                />
                <span className="num w-24 text-xs text-mut">{s.slot}</span>
              </label>
              <input
                className={inputCls}
                value={s.label}
                disabled={!isAdmin || !s.custom}
                onChange={(e) => updSlot(idx, { label: e.target.value })}
                aria-label={t("Название ракурса")}
              />
              <input
                className={inputCls}
                value={s.hint}
                disabled={!isAdmin || !s.custom}
                placeholder={t("Подсказка водителю")}
                onChange={(e) => updSlot(idx, { hint: e.target.value })}
                aria-label={t("Подсказка")}
              />
              {s.custom && isAdmin ? (
                <Button variant="ghost" size="icon" aria-label={t("Удалить ракурс")} onClick={() => setSlots(slots.filter((_, i) => i !== idx))}>
                  <Trash2 size={16} />
                </Button>
              ) : (
                <span />
              )}
            </li>
          ))}
        </ul>
        {isAdmin && (
          <Button variant="outline" size="sm" className="mt-3" onClick={addSlot}>
            <Plus size={14} /> {t("Добавить ракурс")}
          </Button>
        )}
      </SectionCard>

      <SectionCard
        title={t("Анкета водителя")}
        subtitle={t("снимите галочку, чтобы не спрашивать; текст и критичность можно править; «обязательный» — без ответа чек-лист не отправить")}
      >
        <div className="flex flex-col gap-4">
          {Array.from(sections.entries()).map(([title, list]) => (
            <div key={t(title)}>
              <div className="mb-2 text-sm font-bold text-mut">{title}</div>
              <ul className="flex flex-col gap-2">
                {list.map((i) => (
                  <li
                    key={i.id}
                    className={cn("grid items-center gap-2 sm:grid-cols-[auto_1fr_9rem_auto_auto]", !i.enabled && "opacity-60")}
                    data-testid={`checklist-item-${i.id}`}
                  >
                    <label className="flex items-center gap-2 text-sm">
                      {i.method === "auto" ? (
                        <span className="w-4" />
                      ) : (
                        <input
                          type="checkbox"
                          checked={i.enabled ?? true}
                          disabled={!isAdmin}
                          onChange={(e) => updItem(i.id, { enabled: e.target.checked })}
                          aria-label={t("Спрашивать {0}", i.id)}
                        />
                      )}
                      <span className="num w-8 text-xs font-bold text-mut">{i.id}</span>
                    </label>
                    <input
                      className={inputCls}
                      value={i.text}
                      disabled={!isAdmin || i.method === "auto"}
                      placeholder={t("Текст пункта")}
                      onChange={(e) => updItem(i.id, { text: e.target.value })}
                      aria-label={t("Текст {0}", i.id)}
                    />
                    {i.method === "auto" ? (
                      <span className="text-xs text-mut">{t("заполняется системой")}</span>
                    ) : (
                      <select
                        className={inputCls}
                        value={i.criticality ?? ""}
                        disabled={!isAdmin}
                        onChange={(e) => updItem(i.id, { criticality: e.target.value || null })}
                        aria-label={t("Критичность {0}", i.id)}
                      >
                        {CRIT_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                    )}
                    {i.method === "auto" ? (
                      <span />
                    ) : (
                      <label className="flex items-center gap-1.5 whitespace-nowrap text-xs">
                        <input
                          type="checkbox"
                          checked={i.base}
                          disabled={!isAdmin}
                          onChange={(e) => updItem(i.id, { base: e.target.checked })}
                        />
                        {t("обязательный")}
                      </label>
                    )}
                    {i.custom && isAdmin ? (
                      <Button variant="ghost" size="icon" aria-label={t("Удалить {0}", i.id)} onClick={() => setItems(items.filter((x) => x.id !== i.id))}>
                        <Trash2 size={16} />
                      </Button>
                    ) : (
                      <span />
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        {isAdmin && (
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={addItem}>
              <Plus size={14} /> {t("Добавить пункт")}
            </Button>
            <Button
              disabled={save.isPending || enabledSlots === 0 || !!invalidItem}
              onClick={() => save.mutate(toCompact(slots, items))}
              title={invalidItem ? t("Пункт {0}: текст короче 3 символов", invalidItem.id) : undefined}
            >
              <Save size={16} /> {save.isPending ? t("Сохраняем…") : t("Сохранить")}
            </Button>
            <Button
              variant="ghost"
              disabled={save.isPending}
              onClick={() =>
                save.mutate({ hidden_slots: [], custom_slots: [], hidden_items: [], item_overrides: {}, custom_items: [] })
              }
            >
              <RotateCcw size={16} /> {t("Сбросить к стандартному")}
            </Button>
          </div>
        )}
        {enabledSlots === 0 && <p className="mt-2 text-xs text-danger">{t("Нужен хотя бы один ракурс фото.")}</p>}
      </SectionCard>
    </div>
  );
}
