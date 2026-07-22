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
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      className={`min-h-[92px] rounded-xl border p-3 text-left transition ${
        selected
          ? "border-cobalt-500 bg-cobalt-50 ring-2 ring-cobalt-500/20 dark:bg-blue-950/40"
          : "border-slate-200 bg-white hover:border-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-500"
      }`}
    >
      <span className="flex items-start justify-between gap-2">
        <span className="font-bold text-slate-900 dark:text-white">{format.label}</span>
        {format.preferred ? (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-bold text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
            推荐
          </span>
        ) : null}
      </span>
      <span className="mt-2 block truncate text-xs uppercase text-slate-500 dark:text-slate-400">
        {format.extension} · {codec || "未知编码"}
        {format.fps ? ` · ${format.fps} FPS` : ""}
      </span>
      <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">
        {formatBytes(format.estimated_size)}
        {format.requires_merge ? " · 自动合并音频" : ""}
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

  return (
    <section aria-labelledby="format-heading">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 id="format-heading" className="text-lg font-bold">
            选择清晰度
          </h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            高画质缺少音频时会自动无损合并
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAdvanced((value) => !value)}
          className="min-h-11 shrink-0 rounded-lg px-3 text-sm font-semibold text-cobalt-600 hover:bg-cobalt-50 dark:text-blue-300 dark:hover:bg-slate-800"
        >
          {advanced ? "收起高级格式" : "显示高级格式"}
        </button>
      </div>
      <div
        role="radiogroup"
        aria-label="视频清晰度和音频格式"
        className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
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
        <label className="mt-4 block text-sm font-semibold text-slate-700 dark:text-slate-200">
          音频轨
          <select
            value={selectedAudioId || ""}
            onChange={(event) => onAudioSelect(event.target.value || null)}
            className="mt-2 min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3 font-normal text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
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
