type Props = {
  message: string;
  onDismiss?: () => void;
};

export function ErrorAlert({ message, onDismiss }: Props) {
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900/70 dark:bg-red-950/40 dark:text-red-200"
    >
      <div>
        <p className="font-semibold">操作未完成</p>
        <p className="mt-1">{message}</p>
      </div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="min-h-11 shrink-0 rounded-lg px-3 font-semibold hover:bg-red-100 dark:hover:bg-red-900/50"
          aria-label="关闭错误提示"
        >
          关闭
        </button>
      ) : null}
    </div>
  );
}
