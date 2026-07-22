import { formatBytes, formatEta } from "@/lib/format";
import type { Job } from "@/lib/types";

const STATUS_LABELS: Record<Job["status"], string> = {
  queued: "排队中",
  inspecting: "正在解析",
  downloading: "正在下载",
  downloading_video: "正在下载视频轨",
  downloading_audio: "正在下载音频轨",
  merging: "正在无损合并",
  processing: "正在转换格式",
  ready: "下载已准备好",
  failed: "任务失败",
  cancelled: "任务已取消",
  expired: "文件已过期",
};

type Props = {
  job: Job;
  onCancel?: () => void;
};

export function JobProgress({ job, onCancel }: Props) {
  const active = !["ready", "failed", "cancelled", "expired"].includes(job.status);
  return (
    <section
      aria-labelledby="progress-heading"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-cobalt-600 dark:text-blue-300">
            下载任务
          </p>
          <h2 id="progress-heading" className="mt-1 text-xl font-bold">
            {STATUS_LABELS[job.status]}
          </h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{job.message}</p>
        </div>
        {active && onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            className="min-h-11 shrink-0 rounded-xl border border-slate-300 px-4 text-sm font-semibold hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            取消任务
          </button>
        ) : null}
      </div>

      <div className="mt-6">
        <div className="mb-2 flex justify-between text-sm font-semibold">
          <span>总进度</span>
          <span>{Math.round(job.progress)}%</span>
        </div>
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(job.progress)}
          className="h-3 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"
        >
          <div
            className="h-full rounded-full bg-gradient-to-r from-cobalt-500 to-emerald-500 transition-[width] duration-500"
            style={{ width: `${job.progress}%` }}
          />
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
          <dt className="text-xs text-slate-500 dark:text-slate-400">下载速度</dt>
          <dd className="mt-1 font-semibold">{job.speed ? `${formatBytes(job.speed)}/s` : "—"}</dd>
        </div>
        <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
          <dt className="text-xs text-slate-500 dark:text-slate-400">已下载</dt>
          <dd className="mt-1 font-semibold">{formatBytes(job.downloaded_bytes)}</dd>
        </div>
        <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
          <dt className="text-xs text-slate-500 dark:text-slate-400">总大小</dt>
          <dd className="mt-1 font-semibold">{formatBytes(job.total_bytes)}</dd>
        </div>
        <div className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
          <dt className="text-xs text-slate-500 dark:text-slate-400">剩余时间</dt>
          <dd className="mt-1 font-semibold">{active ? formatEta(job.eta) : "—"}</dd>
        </div>
      </dl>

      {job.error ? (
        <div role="alert" className="mt-5 rounded-xl bg-red-50 p-4 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-200">
          {job.error.message}
        </div>
      ) : null}

      {job.status === "ready" && job.download_url ? (
        <a
          href={job.download_url}
          className="mt-6 flex min-h-14 w-full items-center justify-center rounded-xl bg-emerald-600 px-6 text-base font-bold text-white shadow-lg shadow-emerald-600/20 transition hover:bg-emerald-700"
        >
          下载最终文件
        </a>
      ) : null}
    </section>
  );
}
