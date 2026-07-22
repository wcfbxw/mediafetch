"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
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

export default function Home() {
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [selected, setSelected] = useState<MediaFormat | null>(null);
  const [audioId, setAudioId] = useState<string | null>(null);
  const [container, setContainer] = useState("mp4");
  const [compatibility, setCompatibility] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

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
        // Ignore a malformed SSE frame and keep the connection alive.
      }
    };
    source.addEventListener("progress", update as EventListener);
    source.addEventListener("completed", update as EventListener);
    source.onerror = () => {
      // EventSource reconnects automatically while the task is active.
    };
    return () => source.close();
  }, [activeJobId]);

  useEffect(() => {
    if (!activeJobId) return;
    let mounted = true;
    const refresh = () => {
      if (document.visibilityState !== "visible") return;
      void getJob(activeJobId)
        .then((latest) => {
          if (!mounted) return;
          rememberJob(latest);
          setJob(latest);
        })
        .catch(() => undefined);
    };
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("pageshow", refresh);
    return () => {
      mounted = false;
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
    setBusy(true);
    setErrorMessage("");
    try {
      const result = await inspectUrl(value);
      const initial =
        result.formats.find((format) => format.preferred) ||
        result.formats[0] ||
        result.audio_formats.find((format) => format.preferred) ||
        result.audio_formats[0];
      setInspection(result);
      setSelected(initial);
      setAudioId(null);
      setContainer(defaultContainer(initial));
      setCompatibility(false);
    } catch (error) {
      setInspection(null);
      setSelected(null);
      setErrorMessage(error instanceof Error ? error.message : "解析失败");
    } finally {
      setBusy(false);
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
    setBusy(true);
    setErrorMessage("");
    try {
      const created = await createDownload({
        inspect_id: inspection.inspect_id,
        video_format_id: selected.id,
        audio_format_id: audioId,
        output_container: container,
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
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "无法创建下载任务");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!job) return;
    try {
      const cancelled = await cancelJob(job.job_id);
      rememberJob(cancelled);
      setJob(cancelled);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "取消任务失败");
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

  return (
    <main className="min-h-screen px-4 py-6 sm:px-6 sm:py-10">
      <div className="mx-auto max-w-5xl">
        <header className="flex items-center justify-between">
          <Link href="/" className="text-xl font-black tracking-tight">
            <span className="text-cobalt-600 dark:text-blue-400">Media</span>Fetch
          </Link>
          <span className="rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-xs font-semibold text-slate-600 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">
            无需注册
          </span>
        </header>

        <section className="pb-8 pt-12 text-center sm:pb-10 sm:pt-16">
          <p className="text-sm font-bold uppercase tracking-[0.2em] text-cobalt-600 dark:text-blue-300">
            清晰 · 安全 · 可控
          </p>
          <h1 className="mx-auto mt-4 max-w-3xl text-4xl font-black tracking-tight sm:text-5xl">
            把公开视频，保存成你需要的格式
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-base leading-7 text-slate-600 dark:text-slate-300 sm:text-lg">
            粘贴视频页面链接，选择清晰度。MediaFetch 会处理音视频轨、实时显示进度，并生成限时下载文件。
          </p>
        </section>

        <section className="rounded-2xl border border-white/80 bg-white/90 p-5 shadow-soft backdrop-blur sm:p-7 dark:border-slate-800 dark:bg-slate-900/90">
          <UrlInput busy={busy} onSubmit={inspect} />
          <div className="mt-4 flex flex-col gap-2 border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800 dark:text-slate-400">
            <span>支持 yt-dlp 可解析且未受 DRM 保护的公开页面</span>
            <span className="font-semibold text-amber-700 dark:text-amber-300">
              仅下载您拥有、获授权或平台允许下载的内容
            </span>
          </div>
        </section>

        {errorMessage ? (
          <div className="mt-5">
            <ErrorAlert message={errorMessage} onDismiss={() => setErrorMessage("")} />
          </div>
        ) : null}

        {inspection && selected ? (
          <section className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-soft dark:border-slate-800 dark:bg-slate-900">
            <div className="grid md:grid-cols-[260px_1fr]">
              <div className="aspect-video bg-slate-100 md:aspect-auto md:min-h-[210px] dark:bg-slate-800">
                {inspection.thumbnail ? (
                  // The URL is produced by the backend after public-address validation.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={inspection.thumbnail}
                    alt=""
                    className="h-full w-full object-cover"
                    referrerPolicy="no-referrer"
                  />
                ) : (
                  <div className="flex h-full min-h-44 items-center justify-center text-sm text-slate-500">
                    暂无封面
                  </div>
                )}
              </div>
              <div className="min-w-0 p-5 sm:p-6">
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-cobalt-600 dark:text-blue-300">
                  {inspection.platform}
                </p>
                <h2 className="mt-2 line-clamp-2 text-xl font-bold sm:text-2xl">
                  {inspection.title}
                </h2>
                <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-500 dark:text-slate-400">
                  <div>
                    <dt className="sr-only">作者</dt>
                    <dd>{inspection.uploader || "未知作者"}</dd>
                  </div>
                  <div>
                    <dt className="sr-only">时长</dt>
                    <dd>{formatDuration(inspection.duration)}</dd>
                  </div>
                </dl>
              </div>
            </div>

            <div className="border-t border-slate-100 p-5 sm:p-7 dark:border-slate-800">
              <FormatSelector
                formats={inspection.formats}
                audioFormats={inspection.audio_formats}
                selectedId={selected.id}
                selectedAudioId={audioId}
                onSelect={chooseFormat}
                onAudioSelect={setAudioId}
              />

              <div className="mt-7 grid gap-6 border-t border-slate-100 pt-6 md:grid-cols-2 dark:border-slate-800">
                <fieldset>
                  <legend className="text-sm font-bold">输出格式</legend>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {outputOptions.map(([value, label]) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => {
                          setContainer(value);
                          if (compatibility && value !== "mp4") {
                            setCompatibility(false);
                          }
                        }}
                        className={`min-h-11 rounded-xl border px-4 text-sm font-semibold ${
                          container === value
                            ? "border-cobalt-500 bg-cobalt-50 text-cobalt-700 dark:bg-blue-950/40 dark:text-blue-200"
                            : "border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </fieldset>

                {!isAudio ? (
                  <label className="flex min-h-14 cursor-pointer items-start gap-3 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
                    <input
                      type="checkbox"
                      checked={compatibility}
                      onChange={(event) => {
                        setCompatibility(event.target.checked);
                        if (event.target.checked) setContainer("mp4");
                      }}
                      className="mt-1 h-5 w-5 rounded accent-cobalt-600"
                    />
                    <span>
                      <span className="block text-sm font-bold">MP4 兼容模式</span>
                      <span className="mt-0.5 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                        仅在编码不兼容时转换为 H.264 + AAC；已兼容会自动跳过转码
                      </span>
                    </span>
                  </label>
                ) : null}
              </div>

              <div className="mt-6 flex flex-col gap-4 rounded-xl bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between dark:bg-slate-800/70">
                <div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">预计文件大小</p>
                  <p className="mt-1 text-lg font-bold">{formatBytes(estimatedSize)}</p>
                </div>
                <button
                  type="button"
                  disabled={busy || Boolean(job && !isTerminalJob(job.status))}
                  onClick={startDownload}
                  className="min-h-12 rounded-xl bg-cobalt-600 px-7 font-bold text-white transition hover:bg-cobalt-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {busy ? "正在创建任务…" : "开始下载"}
                </button>
              </div>
            </div>
          </section>
        ) : null}

        {job ? (
          <div className="mt-6">
            <JobProgress job={job} onCancel={cancel} />
          </div>
        ) : null}

        <section className="mt-10 grid gap-4 sm:grid-cols-3">
          {[
            ["格式透明", "展示编码、容器和预计大小，高级格式也可查看。"],
            ["进度实时", "下载、合并和转换阶段通过 SSE 实时更新。"],
            ["自动过期", "任务文件与下载令牌会在设定时间后自动清理。"],
          ].map(([title, text]) => (
            <article
              key={title}
              className="rounded-2xl border border-slate-200/80 bg-white/60 p-5 dark:border-slate-800 dark:bg-slate-900/50"
            >
              <h2 className="font-bold">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">{text}</p>
            </article>
          ))}
        </section>

        <footer className="pb-6 pt-10 text-center text-xs leading-5 text-slate-500 dark:text-slate-400">
          MediaFetch 不绕过访问控制、登录或 DRM。使用者应自行确认下载权限及当地法律要求。
        </footer>
      </div>
    </main>
  );
}
