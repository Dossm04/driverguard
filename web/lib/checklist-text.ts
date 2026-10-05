import { t } from "@/lib/i18n";

/* Расхождения «ответ водителя vs вердикт ИИ» приходят из backend готовыми строками по двум
   шаблонам (routers/checklists.py::_discrepancies). Переводим шаблон, комментарий модели
   оставляем как есть. */
const RE_YES = /^(\S+): водитель ответил «да», ИИ видит неисправность — ([\s\S]*)$/;
const RE_NO = /^(\S+): водитель ответил «нет», ИИ проблемы не увидел — проверьте лично$/;

export function translateDiscrepancy(text: string): string {
  const yes = RE_YES.exec(text);
  if (yes) return t("{0}: водитель ответил «да», ИИ видит неисправность — {1}", yes[1], yes[2]);
  const no = RE_NO.exec(text);
  if (no) return t("{0}: водитель ответил «нет», ИИ проблемы не увидел — проверьте лично", no[1]);
  return text;
}
