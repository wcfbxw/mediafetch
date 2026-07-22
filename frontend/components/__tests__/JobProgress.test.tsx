import { render, screen } from "@testing-library/react";
import { JobProgress } from "@/components/JobProgress";
import type { Job } from "@/lib/types";

const base: Job = {
  job_id: "job",
  status: "downloading_video",
  progress: 45.5,
  speed: 10 * 1024 * 1024,
  downloaded_bytes: 50 * 1024 * 1024,
  total_bytes: 110 * 1024 * 1024,
  eta: 6,
  message: "正在下载视频轨",
  download_url: null,
  error: null,
};

test("renders live progress details", () => {
  render(<JobProgress job={base} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "46");
  expect(screen.getByText("10 MB/s")).toBeInTheDocument();
  expect(screen.getByText("约 6 秒")).toBeInTheDocument();
});

test("renders a prominent download action when ready", () => {
  render(
    <JobProgress
      job={{
        ...base,
        status: "ready",
        progress: 100,
        message: "文件已准备完成",
        download_url: "/api/v1/files/token",
      }}
    />,
  );
  expect(screen.getByRole("link", { name: "下载最终文件" })).toHaveAttribute(
    "href",
    "/api/v1/files/token",
  );
});
