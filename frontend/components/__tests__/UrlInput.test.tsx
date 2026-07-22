import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { UrlInput } from "@/components/UrlInput";

test("submits a trimmed public URL", async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn();
  render(<UrlInput onSubmit={onSubmit} />);
  await user.type(
    screen.getByLabelText("视频链接或分享文案"),
    "https://example.com/video",
  );
  await user.click(screen.getByRole("button", { name: "解析视频" }));
  expect(onSubmit).toHaveBeenCalledWith("https://example.com/video");
});

test("extracts a URL when the full Bilibili share text is submitted", async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn();
  render(<UrlInput onSubmit={onSubmit} />);
  const input = screen.getByLabelText("视频链接或分享文案");
  await user.type(
    input,
    "【第1集：外卖小哥穿越修仙世界，变成了一头猪-哔哩哔哩】 https://b23.tv/V6TfblR",
  );
  await user.click(screen.getByRole("button", { name: "解析视频" }));
  expect(onSubmit).toHaveBeenCalledWith("https://b23.tv/V6TfblR");
  expect(input).toHaveValue("https://b23.tv/V6TfblR");
  expect(screen.getByRole("status")).toHaveTextContent("已从分享文案中自动提取链接");
});

test("extracts a URL from share text read from the clipboard", async () => {
  const user = userEvent.setup();
  vi.spyOn(navigator.clipboard, "readText").mockResolvedValue(
    "视频分享：https://example.com/pasted。",
  );
  render(<UrlInput onSubmit={() => undefined} />);
  await user.click(screen.getByRole("button", { name: "粘贴" }));
  expect(screen.getByLabelText("视频链接或分享文案")).toHaveValue(
    "https://example.com/pasted",
  );
});

test("shows an error when share text contains no web URL", async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn();
  render(<UrlInput onSubmit={onSubmit} />);
  await user.type(screen.getByLabelText("视频链接或分享文案"), "只有标题没有链接");
  await user.click(screen.getByRole("button", { name: "解析视频" }));
  expect(onSubmit).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("没有找到 http 或 https 视频链接");
});
