"use client";

import { useEffect, useState } from "react";
import {
  beginBilibiliLogin,
  clearBilibiliSession,
  getBilibiliSession,
  pollBilibiliLogin,
} from "@/lib/api";
import type { BilibiliLoginStart, PlatformSessionStatus } from "@/lib/types";

const TOKEN_STORAGE_KEY = "mediafetch-admin-token";

function dateText(value: number | null): string {
  return value ? new Date(value * 1000).toLocaleString("zh-CN") : "未知";
}

export function BilibiliLoginPanel() {
  const [token, setToken] = useState("");
  const [authorizedToken, setAuthorizedToken] = useState("");
  const [session, setSession] = useState<PlatformSessionStatus | null>(null);
  const [login, setLogin] = useState<BilibiliLoginStart | null>(null);
  const [loginMessage, setLoginMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const saved = window.sessionStorage.getItem(TOKEN_STORAGE_KEY) || "";
    setToken(saved);
  }, []);

  useEffect(() => {
    if (!login || !authorizedToken) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const result = await pollBilibiliLogin(authorizedToken, login.login_id);
        if (stopped) return;
        setLoginMessage(result.message);
        if (result.status === "ready") {
          setLogin(null);
          setSession(await getBilibiliSession(authorizedToken));
          return;
        }
        if (result.status === "expired") {
          setLogin(null);
          return;
        }
        timer = setTimeout(poll, 2000);
      } catch (error) {
        if (stopped) return;
        setLogin(null);
        setErrorMessage(error instanceof Error ? error.message : "登录状态查询失败");
      }
    };
    timer = setTimeout(poll, 1200);
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [authorizedToken, login]);

  async function authorize() {
    const value = token.trim();
    if (!value) {
      setErrorMessage("请输入管理员令牌");
      return;
    }
    setBusy(true);
    setErrorMessage("");
    try {
      const current = await getBilibiliSession(value);
      window.sessionStorage.setItem(TOKEN_STORAGE_KEY, value);
      window.dispatchEvent(new Event("mediafetch-admin-authorized"));
      setAuthorizedToken(value);
      setSession(current);
    } catch (error) {
      setAuthorizedToken("");
      setSession(null);
      setErrorMessage(error instanceof Error ? error.message : "管理员验证失败");
    } finally {
      setBusy(false);
    }
  }

  async function startLogin() {
    setBusy(true);
    setErrorMessage("");
    setLoginMessage("请使用哔哩哔哩 App 扫码");
    try {
      setLogin(await beginBilibiliLogin(authorizedToken));
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "无法生成登录二维码");
    } finally {
      setBusy(false);
    }
  }

  async function clearSession() {
    if (!window.confirm("确定删除服务器上的哔哩哔哩登录会话吗？")) return;
    setBusy(true);
    setErrorMessage("");
    try {
      setSession(await clearBilibiliSession(authorizedToken));
      setLogin(null);
      setLoginMessage("");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "删除会话失败");
    } finally {
      setBusy(false);
    }
  }

  if (!authorizedToken) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft sm:p-7 dark:border-slate-800 dark:bg-slate-900">
        <h1 className="text-2xl font-black">平台登录管理</h1>
        <p className="mt-2 text-sm leading-6 text-slate-500 dark:text-slate-400">
          管理令牌只保存在当前浏览器标签的会话存储中，不会写入 URL。
        </p>
        <label className="mt-6 block text-sm font-bold" htmlFor="admin-token">
          管理员令牌
        </label>
        <div className="mt-2 flex flex-col gap-3 sm:flex-row">
          <input
            id="admin-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void authorize();
            }}
            className="min-h-12 min-w-0 flex-1 rounded-xl border border-slate-300 bg-transparent px-4 dark:border-slate-700"
          />
          <button
            type="button"
            disabled={busy}
            onClick={authorize}
            className="min-h-12 rounded-xl bg-cobalt-600 px-6 font-bold text-white disabled:opacity-50"
          >
            验证并进入
          </button>
        </div>
        {errorMessage ? <p role="alert" className="mt-4 text-sm text-red-600">{errorMessage}</p> : null}
      </section>
    );
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-soft sm:p-7 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-cobalt-600 dark:text-blue-300">Bilibili</p>
          <h1 className="mt-2 text-2xl font-black">服务器平台会话</h1>
        </div>
        <span className={`rounded-full px-3 py-1.5 text-xs font-bold ${session?.configured ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}>
          {session?.configured ? "已登录" : "未登录"}
        </span>
      </div>

      {session?.configured ? (
        <dl className="mt-5 grid gap-3 rounded-xl bg-slate-50 p-4 text-sm sm:grid-cols-2 dark:bg-slate-800/70">
          <div><dt className="text-slate-500 dark:text-slate-400">保存时间</dt><dd className="mt-1 font-semibold">{dateText(session.updated_at)}</dd></div>
          <div><dt className="text-slate-500 dark:text-slate-400">预计过期</dt><dd className="mt-1 font-semibold">{dateText(session.expires_at)}</dd></div>
        </dl>
      ) : null}

      {login ? (
        <div className="mt-6 text-center">
          {/* The image is generated locally by the API from the official QR-login URL. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={login.qr_image} alt="哔哩哔哩登录二维码" className="mx-auto h-60 w-60 rounded-2xl bg-white p-3" />
          <p aria-live="polite" className="mt-3 text-sm font-semibold">{loginMessage}</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">二维码约 3 分钟内有效，请在 App 中确认登录。</p>
        </div>
      ) : (
        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <button type="button" disabled={busy} onClick={startLogin} className="min-h-12 rounded-xl bg-cobalt-600 px-6 font-bold text-white disabled:opacity-50">
            {session?.configured ? "重新扫码登录" : "生成登录二维码"}
          </button>
          {session?.configured ? (
            <button type="button" disabled={busy} onClick={clearSession} className="min-h-12 rounded-xl border border-red-300 px-6 font-bold text-red-700 disabled:opacity-50 dark:border-red-900 dark:text-red-300">
              删除平台会话
            </button>
          ) : null}
        </div>
      )}

      {errorMessage ? <p role="alert" className="mt-4 text-sm text-red-600">{errorMessage}</p> : null}
      <p className="mt-6 border-t border-slate-100 pt-5 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400">
        MediaFetch 不保存账号或密码。会话仅用于解析、下载你拥有或获授权的内容；会员权益和版权限制仍以平台规则为准，不处理 DRM 内容。
      </p>
    </section>
  );
}
