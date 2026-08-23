"use client";

import { useMemo, useState } from "react";
import { formatBytes } from "@/lib/format";
import type { MediaFormat } from "@/lib/types";

type Props = {
  formats: MediaFormat[];
  audioFormats: MediaFormat[];
  selectedId: string;
  selectedAudioId: string | null;
  onSelect: (format: MediaFormat) => void;
  onAudioSelect: (id: string | null) => void;
};

function FormatCard({
  format,
  selected,
  onClick,
}: {
  format: MediaFormat;
  selected: boolean;
  onClick: () => void;
}) {
  const codec = format.has_video ? format.video_codec : format.audio_codec;
  const dimensions =
    format.width && format.height ? `${format.width} × ${format.height}` : null;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      className={`group relative min-h-[118px] overflow-hidden rounded-2xl border p-4 text-left ${
        selected
          ? "border-cobalt-500 bg-cobalt-50 shadow-[0_12px_28px_rgba(91,95,239,.14)] ring-2 ring-cobalt-500/15 dark:bg-indigo-950/40"
          : "border-slate-200 bg-white/80 hover:-translate-y-0.5 hover:border-slate-400 hover:shadow-lg dark:border-slate-700 dark:bg-slate-900/80 dark:hover:border-slate-500"
      }`}
    >
      {selected ? <span aria-hidden="true" className="absolute right-0 top-0 h-1 w-full bg-cobalt-500" /> : null}
      <span className="flex items-start justify-between gap-2">
        <span>
          <span className="block text-lg font-black tracking-tight text-slate-950 dark:text-white">
            {format.label}
          </span>
          {dimensions ? (
            <span className="mt-0.5 block text-[11px] font-medium text-slate-400">{dimensions}</span>
          ) : null}
        </span>
        {format.preferred ? (
          <span className="rounded-full bg-signal px-2 py-1 text-[10px] font-black text-slate-900">
            推荐
          </span>
        ) : null}
      </span>
      <span className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px] font-bold uppercase text-slate-500 dark:text-slate-400">
        <span className="rounded-md bg-slate-100 px-1.5 py-1 dark:bg-slate-800">{format.extension}</span>
        <span className="max-w-[8rem] truncate rounded-md bg-slate-100 px-1.5 py-1 normal-case dark:bg-slate-800">
          {codec || "未知编码"}
        </span>
        {format.fps ? <span>{Math.round(format.fps)} FPS</span> : null}
      </span>
      <span className="mt-2 flex items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span>{formatBytes(format.estimated_size)}</span>
        <span className={format.requires_merge ? "text-cobalt-600 dark:text-indigo-300" : ""}>
          {format.requires_merge ? "含自动合并" : format.has_audio ? "音画一体" : "独立媒体轨"}
        </span>
      </span>
    </button>
  );
}

export function FormatSelector({
  formats,
  audioFormats,
  selectedId,
  selectedAudioId,
  onSelect,
  onAudioSelect,
}: Props) {
  const [advanced, setAdvanced] = useState(false);
  const all = useMemo(() => [...formats, ...audioFormats], [formats, audioFormats]);
  const visible = advanced
    ? all
    : all.filter((format) => format.preferred || format.id === selectedId);
  const selected = all.find((format) => format.id === selectedId);
  const advancedCount = all.length - all.filter((format) => format.preferred).length;

  return (
    <section aria-labelledby="format-heading">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-black uppercase tracking-[0.18em] text-cobalt-600 dark:text-indigo-300">
            Step 02
          </p>
          <h3 id="format-heading" className="mt-1 text-xl font-black tracking-tight">
            选择清晰度
          </h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            已按画质、编码和容器推荐最佳方案，高画质会自动配对音频
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAdvanced((value) => !value)}
          aria-label={advanced ? "收起高级格式" : "显示高级格式"}
          className="min-h-11 self-start rounded-xl border border-slate-200 bg-white px-3.5 text-sm font-bold text-cobalt-600 hover:border-cobalt-300 hover:bg-cobalt-50 sm:self-auto dark:border-slate-700 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-slate-800"
        >
          {advanced ? "收起高级格式" : `显示高级格式${advancedCount > 0 ? ` · ${advancedCount}` : ""}`}
        </button>
      </div>
      <div
        role="radiogroup"
        aria-label="视频清晰度和音频格式"
        className="mt-5 grid grid-cols-1 gap-3 min-[390px]:grid-cols-2 lg:grid-cols-3"
      >
        {visible.map((format) => (
          <FormatCard
            key={format.id}
            format={format}
            selected={selectedId === format.id}
            onClick={() => onSelect(format)}
          />
        ))}
      </div>

      {selected?.requires_merge && audioFormats.length ? (
        <label className="mt-5 block rounded-2xl border border-slate-200 bg-slate-50/70 p-4 text-sm font-bold text-slate-700 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-200">
          配套音频轨
          <span className="ml-2 text-xs font-normal text-slate-400">不确定时保持自动即可</span>
          <select
            value={selectedAudioId || ""}
            onChange={(event) => onAudioSelect(event.target.value || null)}
            className="mt-3 min-h-12 w-full rounded-xl border border-slate-300 bg-white px-3 font-normal text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-white"
          >
            <option value="">自动选择最佳兼容音轨</option>
            {audioFormats.map((audio) => (
              <option key={audio.id} value={audio.id}>
                {audio.extension.toUpperCase()} · {audio.audio_codec || "未知编码"} ·{" "}
                {formatBytes(audio.estimated_size)}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </section>
  );
}
