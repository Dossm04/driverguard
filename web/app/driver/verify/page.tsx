"use client";

import { useEffect, useRef, useState } from "react";
import { ObjectDetector, loadPublishedDetector } from "@/lib/dms/object-runtime";
import { OBJECT_LABELS, OBJECT_CLASSES, type ObjectBox } from "@/lib/dms/objects";

type Observation = { seconds: number; inference_ms: number; boxes: ObjectBox[] };
export default function VerifyVideo() {
  const video = useRef<HTMLVideoElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const detector = useRef<ObjectDetector | null>(null), epoch = useRef(0), mediaUrl = useRef("");
  const [modelFile, setModelFile] = useState<File | null>(null), [metaFile, setMetaFile] = useState<File | null>(null);
  const [clip, setClip] = useState<File | null>(null), [status, setStatus] = useState("Выберите обученную модель или загрузите опубликованную.");
  const [ready, setReady] = useState(false), [busy, setBusy] = useState(false), [report, setReport] = useState<string | null>(null);
  const [source, setSource] = useState("");
  const [progress, setProgress] = useState(0);
  useEffect(() => () => { epoch.current++; detector.current?.close(); if (mediaUrl.current) URL.revokeObjectURL(mediaUrl.current); }, []);
  async function load(published: boolean) {
    setBusy(true); setReady(false); setReport(null);
    const job = ++epoch.current;
    detector.current?.close(); detector.current = null;
    try {
      setStatus("Проверяю контрольную сумму и запускаю модель…");
      let next: ObjectDetector | null;
      if (published) next = await loadPublishedDetector();
      else {
        if (!modelFile || !metaFile) throw new Error("Выберите .onnx и browser-model.json из результата обучения.");
        next = await ObjectDetector.create(await modelFile.arrayBuffer(), JSON.parse(await metaFile.text()));
      }
      if (job !== epoch.current) { next?.close(); return; }
      if (!next) throw new Error("На сайте пока нет обученной модели. Сначала завершите Colab и подключите результат.");
      detector.current = next; setReady(true);
      setStatus(`Модель ${next.manifest.run_id} загружена. Это кандидат для испытаний.`);
    } catch (e) { if (job === epoch.current) setStatus(e instanceof Error ? e.message : String(e)); }
    finally { if (job === epoch.current) setBusy(false); }
  }
  async function checkVideo() {
    const v = video.current, model = detector.current;
    if (!v || !clip || !model) return;
    const job = ++epoch.current;
    setBusy(true); setReport(null); setProgress(0);
    const rows: Observation[] = [];
    try {
      if (!Number.isFinite(v.duration) || v.duration <= 0 || v.duration > 600) throw new Error("Нужно видео длительностью от 1 секунды до 10 минут.");
      setStatus("Проверка кадров — оставьте эту вкладку открытой.");
      const digest = await crypto.subtle.digest("SHA-256", await clip.arrayBuffer());
      const clipSha = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2,"0")).join("");
      v.pause();
      for (let seconds = 0.01; seconds < v.duration; seconds += 0.5) {
        if (epoch.current !== job) return;
        await new Promise<void>((resolve, reject) => {
          const cleanup = () => { clearTimeout(timer); v.removeEventListener("seeked", done); v.removeEventListener("error", fail); };
          const done = () => { cleanup(); resolve(); };
          const fail = () => { cleanup(); reject(new Error("Не удалось прочитать кадр видео.")); };
          const timer = setTimeout(fail, 10000);
          v.addEventListener("seeked", done, { once: true }); v.addEventListener("error", fail, { once: true });
          v.currentTime = seconds;
        });
        if (epoch.current !== job) return;
        const started = performance.now(), boxes = await model.detect(v);
        if (epoch.current !== job) return;
        rows.push({ seconds: Number(seconds.toFixed(2)), inference_ms: Math.round(performance.now()-started), boxes });
        const c = canvas.current;
        if (c) {
          c.width = v.videoWidth; c.height = v.videoHeight;
          const ctx = c.getContext("2d")!;
          ctx.drawImage(v,0,0,c.width,c.height); ctx.lineWidth=3; ctx.font="18px sans-serif";
          for (const b of boxes) {
            ctx.strokeStyle=ctx.fillStyle=b.cls==="seatbelt_on" ? "#2dd4bf" : "#fbbf24";
            ctx.strokeRect(b.x1*c.width,b.y1*c.height,(b.x2-b.x1)*c.width,(b.y2-b.y1)*c.height);
            ctx.fillText(`${OBJECT_LABELS[b.cls]} ${Math.round(b.conf*100)}%`,b.x1*c.width,Math.max(20,b.y1*c.height-5));
          }
        }
        setProgress(Math.round(Math.min(1,seconds/v.duration)*100));
      }
      const result = {
        schema: 1, created_at: new Date().toISOString(), model: model.manifest,
        video: { name: clip.name, sha256: clipSha, bytes: clip.size, duration_seconds:v.duration, source_url:source || null },
        method: { frame_step_seconds:0.5, detection_threshold:0.35, nms_iou:0.45, analysis:"object_boxes_only" },
        frames_checked:rows.length,
        frames_with_class:Object.fromEntries(OBJECT_CLASSES.map((cls) => [cls,rows.filter((r)=>r.boxes.some((b)=>b.cls===cls)).length])),
        human_ground_truth_provided:false, accuracy:null, field_validation:"not_established",
        limitations:["This report records predictions, not correctness.","Frame sampling does not validate live event timing or real-time performance.","A missing seatbelt detection is unknown, not seatbelt_off."],
        observations:rows,
      };
      setReport(JSON.stringify(result,null,2)); setProgress(100);
      setStatus(`Проверено кадров: ${rows.length}. Отчёт готов; правильность обнаружений требует сверки с разметкой.`);
    } catch(e) { if(epoch.current===job) setStatus(e instanceof Error?e.message:String(e)); }
    finally { if(epoch.current===job) setBusy(false); }
  }
  const button="rounded-xl bg-blue-600 px-4 py-3 font-semibold text-white disabled:opacity-40";
  return <main className="mx-auto flex max-w-3xl flex-col gap-5 p-5">
    <a href="/driver/camera" className="text-blue-400">← Камера DriverGuard</a>
    <h1 className="text-2xl font-bold">Проверка на видео</h1>
    <p className="text-sm text-mut">Ремень · телефон · сигарета. Файлы обрабатываются на этом устройстве. Видео на сервер не отправляется.</p>
    <section className="flex flex-col gap-3 rounded-2xl border border-line p-4">
      <h2 className="font-bold">1. Модель из обучения</h2>
      <button disabled={busy} className={button} onClick={()=>void load(true)}>Загрузить модель сайта</button>
      <label>Или выберите driverguard-candidate.onnx<input disabled={busy} type="file" accept=".onnx" className="mt-1 block w-full" onChange={(e)=>setModelFile(e.target.files?.[0]??null)}/></label>
      <label>Файл проверки browser-model.json<input disabled={busy} type="file" accept=".json" className="mt-1 block w-full" onChange={(e)=>setMetaFile(e.target.files?.[0]??null)}/></label>
      <button disabled={busy||!modelFile||!metaFile} className={button} onClick={()=>void load(false)}>Проверить и загрузить файлы</button>
    </section>
    <section className="flex flex-col gap-3 rounded-2xl border border-line p-4">
      <h2 className="font-bold">2. Независимое видео</h2>
      <p className="text-sm text-mut">До 10 минут и 200 МБ. Для оценки качества используйте видео, не входившее в обучение, и отдельно отмечайте верные и ложные обнаружения.</p>
      <input aria-label="Видео для проверки" disabled={busy} type="file" accept="video/*" onChange={(e)=>{
        const f=e.target.files?.[0]; setReport(null); setClip(null);
        if(!f)return;
        if(f.size>200*1024*1024){setStatus("Видео больше 200 МБ.");return;}
        if(mediaUrl.current)URL.revokeObjectURL(mediaUrl.current);
        mediaUrl.current=URL.createObjectURL(f);setClip(f);
        if(video.current){video.current.src=mediaUrl.current;video.current.load();}
      }}/>
      <label>Ссылка на источник видео<input disabled={busy} value={source} onChange={(e)=>setSource(e.target.value)} placeholder="https://…" className="mt-1 w-full rounded border border-line bg-transparent p-2"/></label>
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video ref={video} playsInline muted controls={!busy} preload="auto" className="max-h-64 w-full rounded-lg bg-black"/>
      <div className="flex gap-2"><button disabled={busy||!ready||!clip} className={button} onClick={()=>void checkVideo()}>Проверить видео</button>
      {busy&&<button className="rounded-xl border border-line p-3" onClick={()=>{epoch.current++;setBusy(false);setStatus("Проверка остановлена. Незавершённый отчёт не сохранён.");}}>Остановить</button>}</div>
    </section>
    <p role="status" className="rounded-xl border border-line p-4">{status}</p>
    <progress value={progress} max={100} className="w-full"/>
    <canvas ref={canvas} className="w-full rounded-xl bg-black"/>
    {report&&<button className={button} onClick={()=>{
      const url=URL.createObjectURL(new Blob([report],{type:"application/json"}));
      const a=document.createElement("a");a.href=url;a.download="DriverGuard_video_report.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }}>Скачать отчёт проверки</button>}
    <p className="text-xs text-mut">Процент рядом с рамкой — уверенность модели, а не измеренная точность. Проверка отдельных кадров не подтверждает готовность системы к дорожной эксплуатации.</p>
  </main>;
}
