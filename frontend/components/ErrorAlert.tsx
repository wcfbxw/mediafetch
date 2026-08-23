type Props = {
  message: string;
  onDismiss?: () => void;
};

export function ErrorAlert({ message, onDismiss }: Props) {
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-4 rounded-2xl border border-red-200 bg-red-50/90 p-4 text-sm text-red-800 shadow-sm dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-200"
    >
      <div className="flex min-w-0 gap-3">
        <span aria-hidden="true" className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-red-100 font-black text-red-700 dark:bg-red-900/60 dark:text-red-200">!</span>
        <div className="min-w-0">
          <p className="font-black">操作未完成</p>
          <p className="mt-1 leading-5">{message}</p>
        </div>
      </div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="min-h-11 shrink-0 rounded-xl px-3 font-bold hover:bg-red-100 dark:hover:bg-red-900/50"
          aria-label="关闭错误提示"
        >
          关闭
        </button>
      ) : null}
    </div>
  );
}
