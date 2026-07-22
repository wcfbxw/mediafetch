"use client";

import { FormEvent, useState } from "react";
import { extractHttpUrl } from "@/lib/url";

type Props = {
  busy?: boolean;
  onSubmit: (url: string) => void | Promise<void>;
};

export function UrlInput({ busy = false, onSubmit }: Props) {
  const [value, setValue] = useState("");
  const [inputMessage, setInputMessage] = useState("");
  const [isError, setIsError] = useState(false);

  function applySharedText(text: string): string | null {
    const extracted = extractHttpUrl(text);
    if (!extracted) {
      setValue(text.trim());
      setIsError(true);
      setInputMessage("没有找到 http 或 https 视频链接，请检查粘贴内容");
      return null;
    }
    setValue(extracted);
    setIsError(false);
    setInputMessage(text.trim() === extracted ? "" : "已从分享文案中自动提取链接");
    return extracted;
  }

  async function paste() {
    setInputMessage("");
    try {
      applySharedText(await navigator.clipboard.readText());
    } catch {
      setIsError(true);
      setInputMessage("无法读取剪贴板，请长按输入框后粘贴");
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const extracted = applySharedText(value);
    if (extracted) void onSubmit(extracted);
  }

  return (
    <form onSubmit={submit} className="space-y-3" aria-label="视频链接解析">
      <label
        htmlFor="video-url"
        className="block text-sm font-semibold text-slate-700 dark:text-slate-200"
      >
        视频链接或分享文案
      </label>
      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="relative min-w-0 flex-1">
          <input
            id="video-url"
            type="text"
            inputMode="url"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            required
            disabled={busy}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setInputMessage("");
              setIsError(false);
            }}
            placeholder="粘贴链接或整段分享文案"
            className="min-h-12 w-full rounded-xl border border-slate-300 bg-white px-4 pr-20 text-base text-slate-900 shadow-sm transition placeholder:text-slate-400 focus:border-cobalt-500 disabled:opacity-60 dark:border-slate-650 dark:bg-slate-900 dark:text-white"
          />
          <button
            type="button"
            onClick={paste}
            disabled={busy}
            className="absolute right-1.5 top-1.5 min-h-9 rounded-lg px-3 text-sm font-semibold text-cobalt-600 hover:bg-cobalt-50 disabled:opacity-50 dark:text-blue-300 dark:hover:bg-slate-800"
          >
            粘贴
          </button>
        </div>
        <button
          type="submit"
          disabled={busy || !value.trim()}
          className="min-h-12 shrink-0 rounded-xl bg-cobalt-600 px-6 font-semibold text-white shadow-sm transition hover:bg-cobalt-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "正在解析…" : "解析视频"}
        </button>
      </div>
      {inputMessage ? (
        <p
          className={`text-sm ${
            isError
              ? "text-amber-700 dark:text-amber-300"
              : "text-emerald-700 dark:text-emerald-300"
          }`}
          role={isError ? "alert" : "status"}
        >
          {inputMessage}
        </p>
      ) : null}
    </form>
  );
}
