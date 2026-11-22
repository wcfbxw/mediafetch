"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ErrorAlert } from "@/components/ErrorAlert";
import { FormatSelector } from "@/components/FormatSelector";
import { GalleryGrid } from "@/components/GalleryGrid";
import { JobProgress } from "@/components/JobProgress";
import { UrlInput } from "@/components/UrlInput";
import {
  API_BASE,
  cancelJob,
  createDownload,
  getJob,
  inspectUrl,
} from "@/lib/api";
import { formatBytes, formatDuration } from "@/lib/format";
import {
  forgetStoredJob,
  isTerminalJob,
  readStoredJobId,
  rememberJob,
  validJobId,
} from "@/lib/jobStorage";
import type { Inspection, Job, MediaFormat } from "@/lib/types";

const SUPPORTED_PLATFORMS = [
  "抖音",
  "TikTok",
  "小红书 · 视频/实况图集",
  "快手",
  "哔哩哔哩 4K",
  "YouTube",
  "X / Twitter",
  "Instagram",
  "微博",
  "皮皮虾",
  "1000+ 站点",
];

function defaultContainer(format: MediaFormat): string {
  if (!format.has_video) {
    return format.extension === "m4a" ? "m4a" : "mp3";
  }
  const codec = (format.video_codec || "").toLowerCase();
  return codec.includes("vp9") || codec.includes("vp09") ? "webm" : "mp4";
}

const ACCESS_STORAGE_KEY = "mediafetch-access-token";

function resolveHref(pathOrUrl: string): string {
  if (!pathOrUrl) return "";
  if (pathOrUrl.startsWith("http://") || pathOrUrl.startsWith("https://")) {
    return pathOrUrl;
  }
  if (API_BASE.startsWith("http://") || API_BASE.startsWith("https://")) {
    try {
      const parsed = new URL(API_BASE);
      return `${parsed.origin}${pathOrUrl}`;
    } catch {
      return pathOrUrl;
    }
  }
  return pathOrUrl;
}

function Logo() {
  return (
    <Link href="/" className="group flex items-center gap-2.5" aria-label="MediaFetch 首页">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-slate-950 text-[11px] font-black tracking-tighter text-signal shadow-lg shadow-slate-950/15 group-hover:bg-cobalt-600 dark:bg-signal dark:text-slate-950">
        MF
      </span>
      <span className="text-lg font-black tracking-[-0.04em]">MediaFetch</span>
      <span className="rounded-md bg-cobalt-50 px-1.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-cobalt-700 dark:bg-indigo-950 dark:text-indigo-300">
        Pure 2.0
      </span>
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
  const [accessRequired, setAccessRequired] = useState(false);
  const [accessCode, setAccessCode] = useState("");
  const resultRef = useRef<HTMLDivElement>(null);
  const jobRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const savedAccess = window.sessionStorage.getItem(ACCESS_STORAGE_KEY) || "";
    setAccessCode(savedAccess);
    if (typeof window.fetch !== "function") return;
    void Promise.resolve(window.fetch(`${API_BASE}/auth/config`))
      .then((res) => (res && res.ok ? res.json() : null))
      .then((cfg: { access_token_required?: boolean } | null) => {
        if (cfg?.access_token_required) setAccessRequired(true);
      })
      .catch(() => undefined);
  }, []);

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
    source.onerror = () => undefined;
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

  const bestInstantVideo = useMemo(() => {
    if (!inspection) return null;
    return (
      inspection.formats.find((f) => f.preferred && f.delivery_mode === "stream" && f.stream_url) ||
      inspection.formats.find((f) => f.delivery_mode === "stream" && f.stream_url) ||
      null
    );
  }, [inspection]);

  const canDirectStreamSelected = Boolean(
    selected &&
      selected.delivery_mode === "stream" &&
      selected.stream_url &&
      !compatibility &&
      (selected.has_video
        ? container === selected.extension
        : container === "original" || container === selected.extension),
  );

  async function inspect(value: string) {
    setInspecting(true);
    setErrorMessage("");
    try {
      const result = await inspectUrl(value);
      const initial =
        result.formats.find((format) => format.preferred) ||
        result.formats[0] ||
        result.audio_formats.find((format) => format.preferred) ||
        result.audio_formats[0] ||
        null;
      const galleryItems = result.gallery || [];
      if (!initial && !galleryItems.length) {
        throw new Error("这个页面没有可下载的无水印媒体格式");
      }
      setInspection(result);
      setSelected(initial);
      setAudioId(null);
      if (initial) {
        setContainer(defaultContainer(initial));
      }
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

  async function startCloudJob(overrideFormat?: MediaFormat, overrideContainer?: string) {
    const targetFormat = overrideFormat || selected;
    if (!inspection || !targetFormat) return;
    const targetContainer = overrideContainer || container;
    setCreatingJob(true);
    setErrorMessage("");
    try {
      const created = await createDownload({
        inspect_id: inspection.inspect_id,
        video_format_id: targetFormat.id,
        audio_format_id: targetFormat.has_video ? audioId : null,
        output_container: targetContainer,
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
        message: "任务已进入云端处理队列",
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

  const gallery = inspection?.gallery || [];
  const hasMediaFormats = Boolean(
    inspection && (inspection.formats.length > 0 || inspection.audio_formats.length > 0),
  );
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
  const bestAudioFormat = inspection?.audio_formats[0] || null;

  return (
    <main className="min-h-screen">
      <div className="mx-auto max-w-5xl px-4 pb-16 pt-5 sm:px-6 lg:px-8">
        <header className="flex items-center justify-between">
          <Logo />
          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50/80 px-3 py-1.5 text-xs font-bold text-emerald-800 sm:flex dark:border-emerald-900/60 dark:bg-emerald-950/60 dark:text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-mint" />
              纯净无平台水印原流
            </span>
            <Link
              href="/admin"
              className="grid min-h-10 place-items-center rounded-xl border border-slate-200 bg-white/80 px-3.5 text-xs font-bold text-slate-600 hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300"
            >
              平台会话
            </Link>
          </div>
        </header>

        <section className="mx-auto max-w-3xl pb-8 pt-10 text-center sm:pt-14">
          <div className="inline-flex items-center gap-2 rounded-full border border-cobalt-100 bg-white/80 px-3.5 py-1.5 text-xs font-black tracking-wide text-cobalt-600 shadow-sm dark:border-indigo-900 dark:bg-slate-900/80 dark:text-indigo-300">
            多引擎无水印源流提取 · 极速直传 + FFmpeg 无损合并
          </div>
          <h1 className="text-balance mt-5 text-4xl font-black leading-[1.1] tracking-[-0.05em] text-slate-950 sm:text-5xl lg:text-6xl dark:text-white">
            全平台视频与图集，
            <span className="relative isolate whitespace-nowrap text-cobalt-600 dark:text-indigo-300">
              纯净无水印直达
              <span
                aria-hidden="true"
                className="absolute -bottom-1 left-0 -z-10 h-2 w-full -rotate-1 rounded-full bg-signal/80"
              />
            </span>
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-slate-600 sm:text-base sm:leading-7 dark:text-slate-300">
            自动识别整段分享文案与短链重定向，直取平台无水印原始编码流与高清实况图集。单轨源流免排队秒级直下，4K 音画分离流云端自动无损合并。
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-1.5">
            {SUPPORTED_PLATFORMS.map((name) => (
              <span
                key={name}
                className="rounded-full border border-slate-200/90 bg-white/70 px-2.5 py-1 text-[11px] font-bold text-slate-600 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300"
              >
                {name}
              </span>
            ))}
          </div>
        </section>

        {accessRequired ? (
          <section className="mx-auto mb-4 max-w-3xl rounded-2xl border border-amber-200 bg-amber-50/80 p-3.5 dark:border-amber-900/60 dark:bg-amber-950/30">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <label htmlFor="access-passcode" className="text-xs font-bold text-amber-900 dark:text-amber-200">
                当前站点已启用访问口令保护
              </label>
              <input
                id="access-passcode"
                type="password"
                value={accessCode}
                onChange={(event) => {
                  const next = event.target.value;
                  setAccessCode(next);
                  window.sessionStorage.setItem(ACCESS_STORAGE_KEY, next);
                }}
                placeholder="输入访问口令 (ACCESS_TOKEN)"
                className="min-h-10 rounded-xl border border-amber-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-cobalt-500 sm:w-72 dark:border-amber-800 dark:bg-slate-900 dark:text-white"
              />
            </div>
          </section>
        ) : null}

        <section className="glass-panel mx-auto max-w-3xl rounded-[28px] p-4 sm:p-6">
          <UrlInput busy={inspecting} onSubmit={inspect} />
        </section>

        {inspecting ? (
          <section
            className="mx-auto mt-5 max-w-3xl overflow-hidden rounded-2xl border border-cobalt-100 bg-white/85 p-5 dark:border-indigo-900 dark:bg-slate-900/85"
            aria-live="polite"
          >
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="font-black">正在解析无水印原始媒体流…</p>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  还原短链、清洗水印流并探测最高可用画质，通常只需 1–3 秒
                </p>
              </div>
              <span className="h-3 w-3 shrink-0 animate-pulse rounded-full bg-cobalt-500" />
            </div>
            <div className="relative mt-4 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <span className="animate-scan absolute inset-y-0 left-0 w-1/3 rounded-full bg-gradient-to-r from-cobalt-500 to-mint" />
            </div>
          </section>
        ) : null}

        {errorMessage ? (
          <div className="mx-auto mt-5 max-w-3xl">
            <ErrorAlert message={errorMessage} onDismiss={() => setErrorMessage("")} />
          </div>
        ) : null}

        {job ? (
          <div ref={jobRef} className="mt-6 scroll-mt-5">
            <JobProgress job={job} onCancel={activeJobId && !cancelling ? cancel : undefined} />
          </div>
        ) : null}

        {inspection ? (
          <div ref={resultRef} className="mt-7 scroll-mt-5">
            <section className="overflow-hidden rounded-[30px] border border-slate-200/80 bg-white shadow-panel dark:border-slate-800 dark:bg-slate-900">
              <div className="grid border-b border-slate-100 md:grid-cols-[280px_1fr] dark:border-slate-800">
                <div className="relative aspect-video overflow-hidden bg-slate-100 md:aspect-auto md:min-h-[210px] dark:bg-slate-800">
                  {inspection.thumbnail ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={resolveHref(inspection.thumbnail)}
                      alt=""
                      className="h-full w-full object-cover"
                      referrerPolicy="no-referrer"
                    />
                  ) : (
                    <div className="grid h-full min-h-44 place-items-center text-sm font-bold text-slate-400">
                      暂无封面
                    </div>
                  )}
                  {inspection.duration ? (
                    <span className="absolute bottom-3 right-3 rounded-lg bg-black/75 px-2 py-1 text-xs font-bold text-white backdrop-blur">
                      {formatDuration(inspection.duration)}
                    </span>
                  ) : null}
                </div>

                <div className="flex min-w-0 flex-col justify-between gap-4 p-5 sm:p-7">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-cobalt-50 px-2.5 py-1 text-[11px] font-black uppercase tracking-[0.12em] text-cobalt-700 dark:bg-indigo-950 dark:text-indigo-300">
                        {inspection.platform}
                      </span>
                      <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-black text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                        ✓ 纯净无平台水印
                      </span>
                      {gallery.length > 0 ? (
                        <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-bold text-amber-800 dark:bg-amber-950 dark:text-amber-200">
                          高清图集 · {gallery.length} 张
                        </span>
                      ) : null}
                    </div>
                    <h2 className="mt-3 line-clamp-2 text-xl font-black leading-snug tracking-tight sm:text-2xl">
                      {inspection.title}
                    </h2>
                    <div className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-slate-500 dark:text-slate-400">
                      <span>{inspection.uploader || "公开创作者"}</span>
                      {inspection.formats.length > 0 ? (
                        <span>{inspection.formats.length} 个无水印视频流</span>
                      ) : null}
                      {inspection.audio_formats.length > 0 ? (
                        <span>{inspection.audio_formats.length} 个音频流</span>
                      ) : null}
                    </div>
                  </div>

                  {/* Quick One-Click Actions */}
                  <div className="flex flex-wrap gap-2.5 pt-1">
                    {bestInstantVideo && bestInstantVideo.stream_url ? (
                      <a
                        href={resolveHref(bestInstantVideo.stream_url)}
                        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 text-sm font-black text-white shadow-md shadow-emerald-600/20 hover:bg-emerald-700"
                      >
                        ⚡ 极速直下无水印 {bestInstantVideo.label} ({bestInstantVideo.extension.toUpperCase()})
                      </a>
                    ) : null}
                    {bestAudioFormat ? (
                      <button
                        type="button"
                        disabled={creatingJob || hasActiveJob}
                        onClick={() => void startCloudJob(bestAudioFormat, "mp3")}
                        className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-4 text-xs font-black text-slate-700 hover:border-cobalt-400 hover:text-cobalt-600 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                      >
                        🎵 提取纯音频 MP3
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>

              {gallery.length > 0 ? (
                <div className="border-b border-slate-100 p-5 sm:p-7 dark:border-slate-800">
                  <GalleryGrid items={gallery} zipUrl={inspection.gallery_zip_url} />
                </div>
              ) : null}

              {hasMediaFormats && selected ? (
                <div className="grid gap-8 p-5 sm:p-7 lg:grid-cols-[minmax(0,1fr)_320px] lg:p-8">
                  <FormatSelector
                    formats={inspection.formats}
                    audioFormats={inspection.audio_formats}
                    selectedId={selected.id}
                    selectedAudioId={audioId}
                    onSelect={chooseFormat}
                    onAudioSelect={setAudioId}
                  />

                  <aside className="lg:sticky lg:top-5 lg:self-start">
                    <div className="overflow-hidden rounded-[24px] border border-slate-200 bg-slate-50/80 dark:border-slate-700 dark:bg-slate-950/50">
                      <div className="border-b border-slate-200 p-5 dark:border-slate-700">
                        <p className="text-xs font-black uppercase tracking-[0.18em] text-cobalt-600 dark:text-indigo-300">
                          Output & Delivery
                        </p>
                        <h3 className="mt-1 text-xl font-black tracking-tight">下载方案</h3>
                      </div>

                      <div className="space-y-5 p-5">
                        <fieldset>
                          <legend className="text-xs font-bold text-slate-500 dark:text-slate-400">
                            输出容器
                          </legend>
                          <div className="mt-2 grid grid-cols-3 gap-1.5 rounded-xl bg-slate-200/70 p-1.5 dark:bg-slate-800">
                            {outputOptions.map(([value, label]) => (
                              <button
                                key={value}
                                type="button"
                                onClick={() => {
                                  setContainer(value);
                                  if (compatibility && value !== "mp4") setCompatibility(false);
                                }}
                                className={`min-h-10 rounded-lg px-2 text-xs font-black ${
                                  container === value
                                    ? "bg-white text-slate-950 shadow-sm dark:bg-slate-700 dark:text-white"
                                    : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
                                }`}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </fieldset>

                        {!isAudio ? (
                          <label className="flex cursor-pointer items-start gap-3 rounded-2xl border border-slate-200 bg-white p-3.5 dark:border-slate-700 dark:bg-slate-900">
                            <input
                              type="checkbox"
                              checked={compatibility}
                              onChange={(event) => {
                                setCompatibility(event.target.checked);
                                if (event.target.checked) setContainer("mp4");
                              }}
                              className="mt-0.5 h-5 w-5 rounded accent-cobalt-600"
                            />
                            <span>
                              <span className="block text-sm font-black">H.264 兼容转码</span>
                              <span className="mt-1 block text-xs leading-5 text-slate-500 dark:text-slate-400">
                                仅当旧设备无法播放 HEVC/VP9/AV1 时勾选
                              </span>
                            </span>
                          </label>
                        ) : null}

                        <dl className="space-y-2.5 border-y border-slate-200 py-4 text-sm dark:border-slate-700">
                          <div className="flex items-center justify-between gap-3">
                            <dt className="text-slate-500 dark:text-slate-400">已选规格</dt>
                            <dd className="font-black">
                              {selected.label} · {selected.extension.toUpperCase()}
                            </dd>
                          </div>
                          <div className="flex items-center justify-between gap-3">
                            <dt className="text-slate-500 dark:text-slate-400">传输模式</dt>
                            <dd className="font-black text-emerald-600 dark:text-emerald-300">
                              {canDirectStreamSelected
                                ? "⚡ 零落盘极速直传"
                                : compatibility
                                  ? "云端兼容转码"
                                  : selected.requires_merge
                                    ? "云端无损合并"
                                    : "云端封装"}
                            </dd>
                          </div>
                          <div className="flex items-center justify-between gap-3">
                            <dt className="text-slate-500 dark:text-slate-400">预计体积</dt>
                            <dd className="text-base font-black tabular-nums">
                              {formatBytes(estimatedSize)}
                            </dd>
                          </div>
                        </dl>

                        {canDirectStreamSelected && selected.stream_url ? (
                          <a
                            href={resolveHref(selected.stream_url)}
                            className="flex min-h-14 w-full items-center justify-center rounded-2xl bg-emerald-600 px-6 font-black text-white shadow-lg shadow-emerald-600/20 hover:bg-emerald-700"
                          >
                            ⚡ 立即下载无水印原片 ↓
                          </a>
                        ) : (
                          <button
                            type="button"
                            disabled={creatingJob || hasActiveJob}
                            onClick={() => void startCloudJob()}
                            className="min-h-14 w-full rounded-2xl bg-slate-950 px-6 font-black text-white shadow-lg shadow-slate-950/15 hover:bg-cobalt-600 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-signal dark:text-slate-950 dark:hover:bg-lime-300"
                          >
                            {creatingJob
                              ? "正在创建任务…"
                              : hasActiveJob
                                ? "当前任务处理中"
                                : "开始云端无损合并 →"}
                          </button>
                        )}
                      </div>
                    </div>
                  </aside>
                </div>
              ) : null}
            </section>
          </div>
        ) : null}

        <footer className="mt-12 flex flex-col gap-2 border-t border-slate-200/80 py-6 text-xs leading-5 text-slate-500 sm:flex-row sm:items-center sm:justify-between dark:border-slate-800 dark:text-slate-400">
          <span>© MediaFetch 2.0 · 自托管多平台无水印解析与下载系统</span>
          <span>仅用于下载您拥有权利或获得授权的公开媒体内容，不绕过付费墙或 DRM。</span>
        </footer>
      </div>
    </main>
  );
}
