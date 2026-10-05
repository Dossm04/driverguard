"use client";

/* Страница «Чек-листы» (ШАГ 10, WEB-7, US-5): карточки осмотров с вердиктом ИИ,
   7 фото с тегами ИИ, таблица пунктов с confidence, анкета v2 и расхождения,
   действия координатора. Данные — GET /checklists, действия — POST approve. */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ClipboardCheck, Wrench } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { formatEventTime } from "@/components/event-modal";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { QueryError } from "@/components/ui/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import {
  api,
  currentUser,
  type AiStatusOut,
  type AiTag,
  type ChecklistAiItem,
  type ChecklistListOut,
  type ChecklistOut,
  type ChecklistStatus,
} from "@/lib/api";
import { translateDiscrepancy } from "@/lib/checklist-text";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn, pluralRu } from "@/lib/utils";

const STATUS_CHIPS: { value: "" | ChecklistStatus; label: string }[] = perLang(() => [
  { value: "", label: t("Все") },
  { value: "pending", label: t("Ожидают") },
  { value: "approved", label: t("Согласованы") },
  { value: "approved_with_note", label: t("С отметкой") },
  { value: "sent_to_repair", label: t("На устранении") },
]);

const VERDICT_BADGE: Record<ChecklistOut["verdict"], { text: string; cls: string }> = perLang(() => ({
  допущен: { text: t("✓ ДОПУЩЕН"), cls: "bg-ok/15 text-ok" },
  требует_внимания: { text: t("⚠ ТРЕБУЕТ ВНИМАНИЯ"), cls: "bg-warn/15 text-warn" },
  не_допущен: { text: t("✕ НЕ ДОПУЩЕН"), cls: "bg-danger/15 text-danger" },
}));

const STATUS_PILL: Record<ChecklistStatus, { label: string; tone: PillTone }> = perLang(() => ({
  pending: { label: t("Ожидает решения"), tone: "accent" },
  approved: { label: t("Выезд согласован"), tone: "ok" },
  approved_with_note: { label: t("Согласован с отметкой"), tone: "warn" },
  sent_to_repair: { label: t("На устранении"), tone: "danger" },
}));

const AI_TAG: Record<AiTag, { text: string; cls: string } | null> = perLang(() => ({
  ok: { text: t("✓ ИИ"), cls: "bg-ok/15 text-ok" },
  warn: { text: t("⚠ ИИ"), cls: "bg-warn/15 text-warn" },
  fail: { text: t("✕ ИИ"), cls: "bg-danger/15 text-danger" },
  not_visible: { text: t("? ИИ"), cls: "bg-offline/15 text-offline" },
  none: null,
}));

const AI_STATUS_TEXT: Record<AiTag, string> = {
  ok: "text-txt",
  warn: "text-warn",
  fail: "text-danger",
  not_visible: "italic text-mut",
  none: "text-mut",
};

const SLOT_EMOJI: Record<string, string> = {
  front_lights: "🔦",
  rear_lights: "🔴",
  left_side: "◀️",
  right_side: "▶️",
  tires: "🛞",
  windshield: "🪟",
  under_engine: "🛢",
};

type Action = "approve" | "approve_with_note" | "send_to_repair";
const ACTION_TOAST: Record<Action, string> = perLang(() => ({
  approve: t("Выезд согласован"),
  approve_with_note: t("Согласовано с отметкой координатора"),
  send_to_repair: t("Заявка на устранение создана"),
}));

function aiMetaLabel(meta: ChecklistOut["ai_meta"]): string {
  if (meta.provider === "gemini") {
    const secs = meta.latency_ms != null ? t(" · {0} с", (meta.latency_ms / 1000).toFixed(1)) : "";
    return t("ИИ: {0}{1}", meta.model ?? "Gemini", secs);
  }
  if (meta.provider === "openai_compat") {
    const secs = meta.latency_ms ? t(" · {0} с", (meta.latency_ms / 1000).toFixed(1)) : "";
    return t("ИИ: {0} · {1}{2}", meta.model ?? "модель", meta.host ?? "OpenAI-совместимый API", secs);
  }
  if (meta.provider === "mock") return t("ИИ: демо-режим (ключ не задан)");
  if (meta.provider === "unavailable") return t("ИИ: недоступен — фото проверены вручную");
  if (meta.provider === "demo") return t("ИИ: демо-данные seed");
  return t("ИИ");
}

export default function ChecklistsPage() {
  useLangVersion();
  const [status, setStatus] = useState<"" | ChecklistStatus>("");
  const [canManage, setCanManage] = useState(false);
  useEffect(() => {
    const role = currentUser()?.role;
    setCanManage(role === "admin" || role === "coordinator");
  }, []);

  const PAGE_SIZE = 20;
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [status]); // смена фильтра — с первой страницы
  const list = useQuery({
    queryKey: ["checklists", status, page],
    queryFn: () =>
      api<ChecklistListOut>(
        `/checklists?page_size=${PAGE_SIZE}&page=${page}${status ? `&status=${status}` : ""}`,
      ),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / PAGE_SIZE)) : 1;
  // Статус ИИ-провайдера: без ключа фото не анализируются (демо-режим) — предупредим.
  const aiStatus = useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api<AiStatusOut>("/checklists/ai-status"),
    enabled: canManage,
    staleTime: 5 * 60_000,
  });

  return (
    <div className="flex flex-col gap-3">
      {canManage && aiStatus.data && !aiStatus.data.configured && (
        <div
          role="status"
          data-testid="ai-demo-banner"
          className="flex flex-wrap items-center gap-2 rounded-card border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-txt"
        >
          <AlertTriangle size={16} className="text-warn" aria-hidden />
          <span>
            {t("ИИ работает в демо-режиме: фото не анализируются, вердикт строится только по анкете.")}
          </span>
          <Link href="/settings?tab=checklist" className="ml-auto font-bold text-accent hover:underline">
            {t("Подключить ключ →")}
          </Link>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2.5 rounded-card border border-line bg-card p-3">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label={t("Статус чек-листа")}>
          {STATUS_CHIPS.map((chip) => (
            <button
              key={chip.value}
              role="tab"
              aria-selected={status === chip.value}
              onClick={() => setStatus(chip.value)}
              className={cn(
                "rounded-btn border border-line px-3 py-1.5 text-xs font-bold text-mut transition-colors hover:text-txt",
                status === chip.value && "border-accent bg-accent/10 text-accent",
              )}
            >
              {chip.label}
            </button>
          ))}
        </div>
        {list.data && (
          <span className="num ml-auto flex items-center gap-2 text-xs text-mut">
            {list.data.total} {pluralRu(list.data.total, t("осмотр"), t("осмотра"), t("осмотров"))}
            {pages > 1 && (
              <>
                <Button variant="outline" size="sm" aria-label={t("Предыдущая страница")} disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  ‹
                </Button>
                <span>
                  {page} / {pages}
                </span>
                <Button variant="outline" size="sm" aria-label={t("Следующая страница")} disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
                  ›
                </Button>
              </>
            )}
          </span>
        )}
      </div>

      {list.isError ? (
        <QueryError error={list.error} onRetry={() => list.refetch()} />
      ) : list.isLoading || !list.data ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-[320px] rounded-card" />
          ))}
        </div>
      ) : list.data.items.length === 0 ? (
        <EmptyState
          icon={ClipboardCheck}
          title={t("Осмотров нет")}
          description={t("По выбранному статусу чек-листов пока нет.")}
        />
      ) : (
        list.data.items.map((c) => <ChecklistCard key={c.id} checklist={c} canManage={canManage} />)
      )}
    </div>
  );
}

function ChecklistCard({ checklist: c, canManage }: { checklist: ChecklistOut; canManage: boolean }) {
  useLangVersion();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState("");

  const review = useMutation({
    mutationFn: (body: { action: Action; note?: string }) =>
      api<ChecklistOut>(`/checklists/${c.id}/approve`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (_updated, vars) => {
      toast(`${ACTION_TOAST[vars.action]}: ${c.vehicle_plate ?? ""}`);
      setNoteOpen(false);
      queryClient.invalidateQueries({ queryKey: ["checklists"] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось обработать чек-лист")),
  });

  const badge = VERDICT_BADGE[c.verdict];
  const statusPill = STATUS_PILL[c.status];

  const columns: Column<ChecklistAiItem>[] = [
    {
      key: "title",
      header: t("Пункт"),
      render: (i) => (
        <span className="whitespace-nowrap">
          <b>{t(i.title)}</b>
          {i.critical && <span className="ml-1.5 text-[10px] font-bold uppercase text-mut">{t("критично")}</span>}
        </span>
      ),
    },
    {
      key: "verdict",
      header: t("Вердикт ИИ"),
      render: (i) => <span className={AI_STATUS_TEXT[i.status]}>{i.comment || i.status}</span>,
    },
    {
      key: "conf",
      header: "Conf.",
      render: (i) => (
        <span
          className="block h-1.5 w-[70px] overflow-hidden rounded-full bg-cardh"
          title={`${Math.round(i.confidence * 100)}%`}
        >
          <span
            className={cn(
              "block h-full rounded-full",
              i.status === "fail" ? "bg-danger" : i.status === "warn" ? "bg-warn" : "bg-accent",
            )}
            style={{ width: `${Math.round(i.confidence * 100)}%` }}
          />
        </span>
      ),
    },
  ];

  return (
    <article
      data-testid="checklist-card"
      className="flex flex-col gap-4 rounded-card border border-line bg-card p-4"
    >
      {/* Шапка: водитель, машина, время, вердикт */}
      <div className="flex flex-wrap items-center gap-3">
        <Avatar name={c.driver_name ?? "—"} size={40} />
        <div className="min-w-0">
          <b className="block truncate text-[15px]">{c.driver_name ?? "—"}</b>
          <span className="block text-xs text-mut">
            <span className="num">{c.vehicle_plate ?? "—"}</span>
            {c.vehicle_model ? ` · ${c.vehicle_model}` : ""}
          </span>
        </div>
        <span className="num text-sm text-mut">{formatEventTime(c.created_at)}</span>
        <span className="text-xs text-mut">{aiMetaLabel(c.ai_meta)}</span>
        <span
          data-testid="verdict"
          className={cn("ml-auto rounded-btn px-3 py-1.5 text-[13px] font-extrabold", badge.cls)}
        >
          {badge.text}
        </span>
      </div>

      {/* 7 фото с тегами ИИ */}
      <div className="grid grid-cols-4 gap-2 md:grid-cols-7">
        {c.photos.map((p) => {
          const tag = AI_TAG[p.ai];
          const tile = (
            <div className="relative grid aspect-[4/3] place-items-center overflow-hidden rounded-btn border border-line bg-cardh">
              {p.url ? (
                // presigned-ссылка MinIO (10 мин); next/image требует remotePatterns — здесь <img>
                // eslint-disable-next-line @next/next/no-img-element
                <img src={p.url} alt={t(p.label)} className="h-full w-full object-cover" />
              ) : (
                <span className="text-2xl" aria-hidden>
                  {SLOT_EMOJI[p.slot] ?? "📷"}
                </span>
              )}
              <span className="absolute bottom-1 left-1.5 rounded px-1 text-[10px] font-bold text-mut">
                {t(p.label)}
              </span>
              {tag && (
                <span
                  className={cn(
                    "absolute right-1 top-1 rounded-full px-1.5 py-0.5 text-[10px] font-extrabold",
                    tag.cls,
                  )}
                >
                  {tag.text}
                </span>
              )}
            </div>
          );
          return p.url ? (
            <a key={p.slot} href={p.url} target="_blank" rel="noreferrer" title={t(p.label)}>
              {tile}
            </a>
          ) : (
            <div key={p.slot} title={t("{0} — фото демо", t(p.label))}>
              {tile}
            </div>
          );
        })}
      </div>

      {/* Таблица пунктов ИИ */}
      <div className="grid gap-4 xl:grid-cols-[3fr_2fr]">
        <div>
          <DataTable columns={columns} rows={c.ai_items} rowKey={(i) => i.key} />
          {c.body_damage.length > 0 && (
            <p className="mt-2 text-xs text-warn">
              {t("Повреждения кузова:")}{" "}
              {c.body_damage.map((d) => `${d.описание} — ${d.зона}`).join("; ")}
            </p>
          )}
        </div>

        {/* Анкета v2 и расхождения */}
        <div className="rounded-btn border border-line bg-cardh/60 p-3 text-sm">
          <div className="flex items-center gap-2">
            <ClipboardCheck size={16} className="text-accent" />
            <b>{t("Анкета водителя")}</b>
            <span className="num ml-auto text-xs text-mut">
              {c.answered} {pluralRu(c.answered, t("пункт"), t("пункта"), t("пунктов"))}
            </span>
          </div>
          {c.answer_issues.length === 0 ? (
            <p className="mt-1.5 text-xs text-mut">{t("Замечаний по анкете нет — все пункты «да».")}</p>
          ) : (
            <ul className="mt-1.5 flex flex-col gap-1">
              {c.answer_issues.map((i) => (
                <li key={i.id} className="flex items-start gap-2 text-xs">
                  <StatusPill tone={i.criticality === "critical" ? "danger" : "warn"}>
                    {i.criticality === "critical" ? t("критично") : t("внимание")}
                  </StatusPill>
                  <span>
                    <b>{i.id}</b> · {i.text} {t("— ответ «нет»")}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {c.discrepancies.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1 rounded-btn bg-warn/10 p-2 text-xs text-warn">
              {c.discrepancies.map((d) => (
                <li key={translateDiscrepancy(d)} className="flex items-start gap-1.5">
                  <AlertTriangle size={14} className="mt-0.5 flex-none" /> {d}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Действия координатора / итоговый статус */}
      <div className="flex flex-wrap items-center gap-2 border-t border-line/60 pt-3">
        {c.status !== "pending" ? (
          <>
            <StatusPill tone={statusPill.tone}>{statusPill.label}</StatusPill>
            <span className="text-xs text-mut">
              {c.reviewed_by_name ?? "—"}
              {c.reviewed_at ? ` · ${formatEventTime(c.reviewed_at)}` : ""}
              {c.note ? ` · «${c.note}»` : ""}
            </span>
          </>
        ) : !canManage ? (
          <StatusPill tone="accent">{statusPill.label}</StatusPill>
        ) : c.verdict === "допущен" ? (
          <Button variant="ok" disabled={review.isPending} onClick={() => review.mutate({ action: "approve" })}>
            <Check size={16} /> {t("Согласовать выезд")}
          </Button>
        ) : (
          <>
            <Button
              variant="danger"
              disabled={review.isPending}
              onClick={() => review.mutate({ action: "send_to_repair" })}
            >
              <Wrench size={16} /> {t("Отправить на устранение")}
            </Button>
            {noteOpen ? (
              <span className="flex flex-wrap items-center gap-2">
                <input
                  aria-label={t("Отметка координатора")}
                  className="h-9 w-72 rounded-btn border border-line bg-page px-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
                  placeholder={t("Отметка: что проверено лично, условия выезда")}
                  value={note}
                  maxLength={500}
                  onChange={(e) => setNote(e.target.value)}
                />
                <Button
                  disabled={review.isPending || !note.trim()}
                  onClick={() => review.mutate({ action: "approve_with_note", note: note.trim() })}
                >
                  {t("Подтвердить")}
                </Button>
                <Button variant="ghost" onClick={() => setNoteOpen(false)}>
                  {t("Отмена")}
                </Button>
              </span>
            ) : (
              <Button variant="outline" disabled={review.isPending} onClick={() => setNoteOpen(true)}>
                {t("Согласовать с отметкой")}
              </Button>
            )}
          </>
        )}
      </div>
    </article>
  );
}
