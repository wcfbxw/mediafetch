"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ErrorAlert } from "@/components/ErrorAlert";
import { FormatSelector } from "@/components/FormatSelector";
import { JobProgress } from "@/components/JobProgress";
import { UrlInput } from "@/components/UrlInput";
import { API_BASE, cancelJob, createDownload, getJob, inspectUrl } from "@/lib/api";
import { formatBytes, formatDuration } from "@/lib/format";
import {
  forgetStoredJob,
  isTerminalJob,
  readStoredJobId,
  rememberJob,
  validJobId,
} from "@/lib/jobStorage";
import type { Inspection, Job, MediaFormat } from "@/lib/types";

function defaultContainer(format: MediaFormat): string {
  if (!format.has_video) return "mp3";
  const codec = (format.video_codec || "").toLowerCase();
  return codec.includes("vp9") || codec.includes("vp09") ? "webm" : "mp4";
}

function Logo() {
  return (
    <Link href="/" className="group flex items-center gap-2.5" aria-label="MediaFetch 首页">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-slate-950 text-[11px] font-black tracking-tighter text-signal shadow-lg shadow-slate-950/15 group-hover:bg-cobalt-600 dark:bg-signal dark:text-slate-950">
        MF
      </span>
      <span className="text-lg font-black tracking-[-0.04em]">MediaFetch</span>
    </Link>
  );
}

export default function Home() {
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [selected, setSelected] = useState<MediaFormat | null>(null);
  const [audioId, setAudioId] = useState<string | null>(null);
  const [container, setContainer] = useState("mp4");
  const [compatibility, setCompatibility] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [creatingJob, setCreatingJob] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const resultRef = useRef<HTMLDivElement>(null);
  const jobRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const hashJobId = validJobId(
      new URLSearchParams(window.location.hash.slice(1)).get("job"),
    );
    const savedJobId = hashJobId || readStoredJobId();
    if (!savedJobId) return;
    let mounted = true;
    const restoring: Job = {
      job_id: savedJobId,
      status: "queued",
      progress: 0,
      speed: null,
      downloaded_bytes: 0,
      total_bytes: null,
      eta: null,
      message: "正在恢复上次任务…",
      download_url: null,
      error: null,
    };
    rememberJob(restoring);
    setJob(restoring);
    if (hashJobId) {
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}${window.location.search}`,
      );
    }
    void getJob(savedJobId)
      .then((latest) => {
        if (!mounted) return;
        rememberJob(latest);
        setJob(latest);
      })
      .catch(() => {
        if (!mounted) return;
        forgetStoredJob(savedJobId);
        setJob((current) => (current?.job_id === savedJobId ? null : current));
      });
    return () => {
      mounted = false;
    };
  }, []);

  const activeJobId = job && !isTerminalJob(job.status) ? job.job_id : null;

  useEffect(() => {
    if (!activeJobId) return;
    const source = new EventSource(
      `${API_BASE}/jobs/${encodeURIComponent(activeJobId)}/events`,
    );
    const update = (event: MessageEvent<string>) => {
      try {
        const next = JSON.parse(event.data) as Job;
        rememberJob(next);
        setJob(next);
        if (isTerminalJob(next.status)) source.close();
      } catch {
        // Keep the stream alive when a malformed frame is received.
      }
    };
    source.addEventListener("progress", update as EventListener);
    source.addEventListener("completed", update as EventListener);
    source.onerror = () => {
      // EventSource reconnects automatically. Timed polling below is the fallback.
    };
    return () => source.close();
  }, [activeJobId]);

  useEffect(() => {
    if (!activeJobId) return;
    let mounted = true;
    let refreshing = false;
    const refresh = () => {
      if (refreshing || document.visibilityState !== "visible") return;
      refreshing = true;
      void getJob(activeJobId)
        .then((latest) => {
          if (!mounted) return;
          rememberJob(latest);
          setJob(latest);
        })
        .catch(() => undefined)
        .finally(() => {
          refreshing = false;
        });
    };
    const timer = window.setInterval(refresh, 8000);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("pageshow", refresh);
    return () => {
      mounted = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("pageshow", refresh);
    };
  }, [activeJobId]);

  const estimatedSize = useMemo(() => {
    if (!selected) return null;
    const audio = inspection?.audio_formats.find((format) => format.id === audioId);
    const values = [selected.estimated_size, audio?.estimated_size].filter(
      (value): value is number => typeof value === "number",
    );
    return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
  }, [audioId, inspection, selected]);

  async function inspect(value: string) {
    setInspecting(true);
    setErrorMessage("");
    try {
      const result = await inspectUrl(value);
      const initial =
        result.formats.find((format) => format.preferred) ||
        result.formats[0] ||
        result.audio_formats.find((format) => format.preferred) ||
        result.audio_formats[0];
      if (!initial) throw new Error("这个页面没有可下载的媒体格式");
      setInspection(result);
      setSelected(initial);
      setAudioId(null);
      setContainer(defaultContainer(initial));
      setCompatibility(false);
      window.setTimeout(
        () => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
        80,
      );
    } catch (error) {
      setInspection(null);
      setSelected(null);
      setErrorMessage(error instanceof Error ? error.message : "解析失败");
    } finally {
      setInspecting(false);
    }
  }

  function chooseFormat(format: MediaFormat) {
    setSelected(format);
    setAudioId(null);
    setContainer(defaultContainer(format));
    setCompatibility(false);
  }

  async function startDownload() {
    if (!inspection || !selected) return;
    setCreatingJob(true);
    setErrorMessage("");
    try {
      const created = await createDownload({
        inspect_id: inspection.inspect_id,
        video_format_id: selected.id,
        audio_format_id: audioId,
        output_container: container,
        postprocess_preset: compatibility ? "transcode" : "remux",
        compatibility_mode: compatibility,
      });
      const queuedJob: Job = {
        job_id: created.job_id,
        status: "queued",
        progress: 0,
        speed: null,
        downloaded_bytes: 0,
        total_bytes: estimatedSize,
        eta: null,
        message: "任务已进入队列",
        download_url: null,
        error: null,
      };
      rememberJob(queuedJob);
      setJob(queuedJob);
      window.setTimeout(
        () => jobRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
        80,
      );
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "无法创建下载任务");
    } finally {
      setCreatingJob(false);
    }
  }

  async function cancel() {
    if (!job || cancelling) return;
    setCancelling(true);
    try {
      const cancelled = await cancelJob(job.job_id);
      rememberJob(cancelled);
      setJob(cancelled);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "取消任务失败");
    } finally {
      setCancelling(false);
    }
  }

  const isAudio = selected ? !selected.has_video : false;
  const outputOptions = isAudio
    ? [
        ["original", "原始音频"],
        ["m4a", "M4A"],
        ["mp3", "MP3"],
      ]
    : [
        ["mp4", "MP4"],
        ["webm", "WebM"],
        ["mkv", "MKV"],
      ];
  const hasActiveJob = Boolean(job && !isTerminalJob(job.status));
  const currentStep = job ? (job.status === "ready" ? 4 : 3) : inspection ? 2 : 1;

  return (
    <main className="min-h-screen">
      <div className="mx-auto max-w-7xl px-4 pb-14 pt-5 sm:px-6 lg:px-8">
        <header className="flex items-center justify-between">
          <Logo />
          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-2 rounded-full border border-slate-200 bg-white/70 px-3 py-2 text-xs font-bold text-slate-600 sm:flex dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
              <span className="h-2 w-2 rounded-full bg-mint shadow-[0_0_0_4px_rgba(24,185,129,.12)]" />
              无需注册
            </span>
            <Link href="/admin" className="grid min-h-11 place-items-center rounded-xl border border-slate-200 bg-white/70 px-3.5 text-xs font-bold text-slate-600 hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
              平台会话
            </Link>
          </div>
        </header>

        <section className="grid items-center gap-10 pb-10 pt-14 lg:grid-cols-[minmax(0,1fr)_420px] lg:pb-12 lg:pt-20">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-cobalt-100 bg-white/70 px-3 py-1.5 text-xs font-black uppercase tracking-[0.18em] text-cobalt-600 dark:border-indigo-900 dark:bg-slate-900/70 dark:text-indigo-300">
              Media workflow, simplified
            </div>
            <h1 className="text-balance mt-5 max-w-4xl text-4xl font-black leading-[1.08] tracking-[-0.055em] text-slate-950 sm:text-6xl lg:text-7xl dark:text-white">
              一个链接，
              <span className="relative isolate whitespace-nowrap text-cobalt-600 dark:text-indigo-300">
                拿到需要的格式
                <span aria-hidden="true" className="absolute -bottom-1 left-0 -z-10 h-2 w-full -rotate-1 rounded-full bg-signal/80" />
              </span>
            </h1>
            <p className="mt-6 max-w-2xl text-base leading-7 text-slate-600 sm:text-lg sm:leading-8 dark:text-slate-300">
              自动识别分享文案，透明展示清晰度与编码。音视频轨在云端安全合并，处理进度随时恢复。
            </p>
            <div className="mt-7 flex flex-wrap gap-x-6 gap-y-3 text-sm font-bold text-slate-500 dark:text-slate-400">
              {["格式透明可选", "高画质自动合并", "文件限时清理"].map((item) => (
                <span key={item} className="flex items-center gap-2">
                  <span className="grid h-5 w-5 place-items-center rounded-full bg-emerald-100 text-[11px] text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">✓</span>
                  {item}
                </span>
              ))}
            </div>
          </div>

          <div className="relative hidden lg:block" aria-hidden="true">
            <div className="absolute -inset-10 -z-10 rounded-full bg-gradient-to-br from-cobalt-500/20 to-mint/10 blur-3xl" />
            <div className="rotate-2 rounded-[30px] border border-slate-800 bg-slate-950 p-6 text-white shadow-2xl shadow-slate-950/20">
              <div className="flex items-center justify-between">
                <span className="text-xs font-black uppercase tracking-[0.2em] text-signal">Smart pipeline</span>
                <span className="rounded-full bg-white/10 px-2.5 py-1 text-[10px] font-bold">LIVE</span>
              </div>
              <div className="mt-8 space-y-3">
                {[
                  ["01", "读取页面信息", "标题、封面、格式"],
                  ["02", "获取媒体轨", "并行、安全、可恢复"],
                  ["03", "合并与封装", "FFmpeg 后台处理"],
                ].map(([number, title, detail], index) => (
                  <div key={number} className="flex items-center gap-4 rounded-2xl border border-white/10 bg-white/[0.06] p-4">
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl text-xs font-black ${index === 0 ? "bg-signal text-slate-950" : "bg-white/10 text-white"}`}>{number}</span>
                    <span className="min-w-0">
                      <span className="block font-bold">{title}</span>
                      <span className="mt-0.5 block text-xs text-slate-400">{detail}</span>
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-6 flex items-center gap-3 rounded-2xl bg-white p-3 text-slate-950">
                <span className="h-10 w-14 rounded-xl bg-gradient-to-br from-cobalt-500 to-mint" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-black">final-video.mp4</span>
                  <span className="block text-[11px] text-slate-500">准备下载 · 临时签名链接</span>
                </span>
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-slate-950 font-black text-white">↓</span>
              </div>
            </div>
          </div>
        </section>

        <nav aria-label="下载流程" className="mb-5 grid grid-cols-4 overflow-hidden rounded-2xl border border-slate-200 bg-white/65 p-1.5 dark:border-slate-800 dark:bg-slate-900/65">
          {["粘贴链接", "选择格式", "云端处理", "保存文件"].map((label, index) => {
            const step = index + 1;
            return (
              <span key={label} className={`flex min-h-10 items-center justify-center gap-2 rounded-xl px-2 text-[11px] font-bold sm:text-sm ${currentStep === step ? "bg-slate-950 text-white shadow-md dark:bg-signal dark:text-slate-950" : step < currentStep ? "text-emerald-600 dark:text-emerald-300" : "text-slate-400"}`}>
                <span className="hidden tabular-nums sm:inline">0{step}</span>
                {label}
              </span>
            );
          })}
        </nav>

        <section className="glass-panel rounded-[28px] p-4 sm:p-6 lg:p-7">
          <div className="mb-5 flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-cobalt-100 text-xs font-black text-cobalt-700 dark:bg-indigo-950 dark:text-indigo-300">01</span>
            <div>
              <h2 className="font-black tracking-tight">粘贴公开视频页面</h2>
              <p className="text-xs text-slate-500 dark:text-slate-400">媒体真实地址与敏感参数不会返回浏览器</p>
            </div>
          </div>
          <UrlInput busy={inspecting} onSubmit={inspect} />
          <div className="mt-5 grid gap-2 border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500 sm:grid-cols-2 dark:border-slate-800 dark:text-slate-400">
            <span>支持可公开访问且未受 DRM 保护的平台页面</span>
            <span className="sm:text-right">仅下载你拥有、获授权或平台允许下载的内容</span>
          </div>
        </section>

        {inspecting ? (
          <section className="mt-5 overflow-hidden rounded-2xl border border-cobalt-100 bg-white/80 p-5 dark:border-indigo-900 dark:bg-slate-900/80" aria-live="polite">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="font-black">正在读取视频信息</p>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">检查页面、格式与媒体限制，通常只需几秒</p>
              </div>
              <span className="h-3 w-3 shrink-0 animate-pulse rounded-full bg-cobalt-500" />
            </div>
            <div className="relative mt-4 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <span className="animate-scan absolute inset-y-0 left-0 w-1/3 rounded-full bg-gradient-to-r from-cobalt-500 to-mint" />
            </div>
          </section>
        ) : null}

        {errorMessage ? (
          <div className="mt-5">
            <ErrorAlert message={errorMessage} onDismiss={() => setErrorMessage("")} />
          </div>
        ) : null}

        {job ? (
          <div ref={jobRef} className="mt-6 scroll-mt-5">
            <JobProgress job={job} onCancel={activeJobId && !cancelling ? cancel : undefined} />
          </div>
        ) : null}

        {inspection && selected ? (
          <div ref={resultRef} className="mt-6 scroll-mt-5">
            <section className="overflow-hidden rounded-[30px] border border-slate-200/80 bg-white shadow-panel dark:border-slate-800 dark:bg-slate-900">
              <div className="grid border-b border-slate-100 md:grid-cols-[300px_1fr] dark:border-slate-800">
                <div className="relative aspect-video overflow-hidden bg-slate-100 md:aspect-auto md:min-h-[220px] dark:bg-slate-800">
                  {inspection.thumbnail ? (
                    // The backend only exposes a validated public thumbnail URL.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={inspection.thumbnail} alt="" className="h-full w-full object-cover" referrerPolicy="no-referrer" />
                  ) : (
                    <div className="grid h-full min-h-44 place-items-center text-sm font-bold text-slate-400">暂无封面</div>
                  )}
                  <span className="absolute bottom-3 right-3 rounded-lg bg-black/75 px-2 py-1 text-xs font-bold text-white backdrop-blur">
                    {formatDuration(inspection.duration)}
                  </span>
                </div>
                <div className="flex min-w-0 flex-col justify-center p-5 sm:p-7">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-cobalt-50 px-2.5 py-1 text-[11px] font-black uppercase tracking-[0.14em] text-cobalt-700 dark:bg-indigo-950 dark:text-indigo-300">{inspection.platform}</span>
                    <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-bold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">解析完成</span>
                  </div>
                  <h2 className="mt-3 line-clamp-2 text-xl font-black leading-snug tracking-tight sm:text-2xl">{inspection.title}</h2>
                  <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-slate-500 dark:text-slate-400">
                    <span>{inspection.uploader || "未知作者"}</span>
                    <span>{inspection.formats.length} 个视频格式</span>
                    <span>{inspection.audio_formats.length} 个音频格式</span>
                  </div>
                </div>
              </div>

              <div className="grid gap-8 p-5 sm:p-7 lg:grid-cols-[minmax(0,1fr)_330px] lg:p-8">
                <FormatSelector formats={inspection.formats} audioFormats={inspection.audio_formats} selectedId={selected.id} selectedAudioId={audioId} onSelect={chooseFormat} onAudioSelect={setAudioId} />

                <aside className="lg:sticky lg:top-5 lg:self-start">
                  <div className="overflow-hidden rounded-[24px] border border-slate-200 bg-slate-50/80 dark:border-slate-700 dark:bg-slate-950/50">
                    <div className="border-b border-slate-200 p-5 dark:border-slate-700">
                      <p className="text-xs font-black uppercase tracking-[0.18em] text-cobalt-600 dark:text-indigo-300">Step 03</p>
                      <h3 className="mt-1 text-xl font-black tracking-tight">确认输出方案</h3>
                    </div>

                    <div className="space-y-5 p-5">
                      <fieldset>
                        <legend className="text-xs font-bold text-slate-500 dark:text-slate-400">文件容器</legend>
                        <div className="mt-2 grid grid-cols-3 gap-1.5 rounded-xl bg-slate-200/70 p-1.5 dark:bg-slate-800">
                          {outputOptions.map(([value, label]) => (
                            <button key={value} type="button" onClick={() => { setContainer(value); if (compatibility && value !== "mp4") setCompatibility(false); }} className={`min-h-10 rounded-lg px-2 text-xs font-black ${container === value ? "bg-white text-slate-950 shadow-sm dark:bg-slate-700 dark:text-white" : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"}`}>
                              {label}
                            </button>
                          ))}
                        </div>
                      </fieldset>

                      {!isAudio ? (
                        <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-slate-200 bg-white p-3.5 dark:border-slate-700 dark:bg-slate-900">
                          <input type="checkbox" checked={compatibility} onChange={(event) => { setCompatibility(event.target.checked); if (event.target.checked) setContainer("mp4"); }} className="mt-0.5 h-5 w-5 rounded accent-cobalt-600" />
                          <span>
                            <span className="block text-sm font-black">MP4 兼容模式</span>
                            <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">仅在必要时转换为 H.264 + AAC，处理会更久</span>
                          </span>
                        </label>
                      ) : null}

                      <dl className="space-y-3 border-y border-slate-200 py-4 text-sm dark:border-slate-700">
                        <div className="flex items-center justify-between gap-3"><dt className="text-slate-500 dark:text-slate-400">当前格式</dt><dd className="font-black">{selected.label} · {selected.extension.toUpperCase()}</dd></div>
                        <div className="flex items-center justify-between gap-3"><dt className="text-slate-500 dark:text-slate-400">处理方式</dt><dd className="font-black">{compatibility ? "兼容转码" : selected.requires_merge ? "无损合并" : "直接封装"}</dd></div>
                        <div className="flex items-center justify-between gap-3"><dt className="text-slate-500 dark:text-slate-400">预计大小</dt><dd className="text-lg font-black tabular-nums">{formatBytes(estimatedSize)}</dd></div>
                      </dl>

                      <button type="button" disabled={creatingJob || hasActiveJob} onClick={startDownload} className="min-h-14 w-full rounded-2xl bg-slate-950 px-6 font-black text-white shadow-lg shadow-slate-950/15 hover:bg-cobalt-600 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-signal dark:text-slate-950 dark:hover:bg-lime-300">
                        {creatingJob ? "正在创建任务…" : hasActiveJob ? "当前任务处理中" : "开始云端处理 →"}
                      </button>
                      <p className="text-center text-[11px] leading-4 text-slate-400">完成后生成限时签名下载链接，服务器会自动清理文件</p>
                    </div>
                  </div>
                </aside>
              </div>
            </section>
          </div>
        ) : null}

        <section className="mt-10 grid gap-4 md:grid-cols-3">
          {[
            ["01", "透明选择", "清晰度、编码、容器、帧率与预计体积全部可见。"],
            ["02", "后台处理", "下载、合并与转换由服务器执行，离开页面也不会中断。"],
            ["03", "安全交付", "真实媒体地址不暴露，最终文件通过短期签名链接交付。"],
          ].map(([number, title, text]) => (
            <article key={title} className="rounded-2xl border border-slate-200/80 bg-white/65 p-5 dark:border-slate-800 dark:bg-slate-900/60">
              <span className="text-xs font-black tracking-[0.18em] text-cobalt-600 dark:text-indigo-300">{number}</span>
              <h2 className="mt-3 text-lg font-black tracking-tight">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{text}</p>
            </article>
          ))}
        </section>

        <footer className="mt-10 flex flex-col gap-3 border-t border-slate-200 py-7 text-xs leading-5 text-slate-500 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800 dark:text-slate-400">
          <span>© MediaFetch · 自托管媒体处理工具</span>
          <span>不绕过登录、访问控制、付费权益或 DRM；请确认你拥有下载权限。</span>
        </footer>
      </div>
    </main>
  );
}
