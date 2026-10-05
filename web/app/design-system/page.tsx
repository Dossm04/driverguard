"use client";

/* Витрина дизайн-системы: каждый компонент в светлой и тёмной теме одновременно.
   Страница служебная (не в сайдбаре), открывается по /design-system. */

import { Clock3, Eye, GraduationCap, Truck, TriangleAlert } from "lucide-react";

import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { KpiCard } from "@/components/ui/kpi-card";
import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";

const demoRows = [
  { id: 1, name: "Иванов А.С.", plate: "KZ 4521 AB", score: 41 },
  { id: 2, name: "Петров Д.В.", plate: "KZ 2290 EF", score: 53 },
  { id: 3, name: "Ким С.В.", plate: "KZ 9051 TA", score: 95 },
];

function Showcase() {
  useLangVersion();
  return (
    <div className="flex flex-col gap-4">
      <SectionCard title={t("Кнопки")} subtitle={t("варианты Button")}>
        <div className="flex flex-wrap items-center gap-2">
          <Button>{t("Основная")}</Button>
          <Button variant="outline">
            <Eye size={16} /> {t("Открыть")}
          </Button>
          <Button variant="ok">{t("✓ Подтвердить")}</Button>
          <Button variant="danger">{t("✗ Ложное")}</Button>
          <Button variant="ghost">Ghost</Button>
          <Button disabled>{t("Недоступна")}</Button>
        </div>
      </SectionCard>

      <SectionCard title={t("Статус-пилюли")} subtitle={t("фон 15% + цветной текст")}>
        <div className="flex flex-wrap gap-2">
          <StatusPill tone="ok">{t("Норма")}</StatusPill>
          <StatusPill tone="warn">{t("Внимание")}</StatusPill>
          <StatusPill tone="danger">{t("Критично")}</StatusPill>
          <StatusPill tone="accent">{t("Новое")}</StatusPill>
          <StatusPill tone="offline">{t("Нет связи")}</StatusPill>
        </div>
      </SectionCard>

      <div className="grid grid-cols-2 gap-3">
        <KpiCard
          title={t("Машин на линии")}
          icon={Truck}
          iconTone="accent"
          value="5/6"
          sub={t("1 офлайн")}
          pill={{ label: t("Внимание"), tone: "warn" }}
        />
        <KpiCard
          title={t("Событий сегодня")}
          icon={TriangleAlert}
          iconTone="warn"
          value="14"
          trend={{ value: "+3", tone: "ok" }}
          sub={t("vs. вчера 11")}
          pill={{ label: t("Внимание"), tone: "warn" }}
        />
      </div>

      <SectionCard
        title={t("Таблица")}
        subtitle="DataTable + Avatar"
        action={<StatusPill tone="danger">Score &lt;60</StatusPill>}
      >
        <DataTable
          columns={[
            {
              key: "driver",
              header: t("Водитель"),
              render: (r: (typeof demoRows)[0]) => (
                <span className="flex items-center gap-2">
                  <Avatar name={r.name} ring={r.score < 60 ? "danger" : "ok"} />
                  <b>{r.name}</b>
                </span>
              ),
            },
            { key: "plate", header: t("Машина"), render: (r) => <span className="num">{r.plate}</span> },
            {
              key: "score",
              header: "Score",
              render: (r) => (
                <b className={`num text-lg ${r.score < 60 ? "text-danger" : "text-ok"}`}>{r.score}</b>
              ),
            },
            {
              key: "act",
              header: "",
              render: () => (
                <Button variant="danger" size="sm">
                  <GraduationCap size={14} /> {t("Назначить обучение")}
                </Button>
              ),
            },
          ]}
          rows={demoRows}
          rowKey={(r) => r.id}
        />
      </SectionCard>

      <div className="grid grid-cols-2 gap-3">
        <EmptyState icon={Clock3} title={t("Пусто")} description={t("Пример пустого состояния.")} />
        <SectionCard title={t("Скелетоны")} subtitle={t("загрузка")}>
          <div className="flex flex-col gap-2">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-6 w-full" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

export default function DesignSystemPage() {
  useLangVersion();
  return (
    <div className="grid min-h-screen grid-cols-1 xl:grid-cols-2">
      <div className="light bg-page p-6 text-txt">
        <h1 className="mb-4 text-lg font-extrabold">{t("Светлая тема")}</h1>
        <Showcase />
      </div>
      <div className="dark bg-page p-6 text-txt">
        <h1 className="mb-4 text-lg font-extrabold">{t("Тёмная тема")}</h1>
        <Showcase />
      </div>
    </div>
  );
}
