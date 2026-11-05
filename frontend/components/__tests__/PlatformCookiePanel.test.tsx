import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { PlatformCookiePanel } from "@/components/PlatformCookiePanel";
import { getPlatformSession, uploadPlatformCookies } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getPlatformSession: vi.fn(),
  uploadPlatformCookies: vi.fn(),
  clearPlatformSession: vi.fn(),
}));

test("offers Xiaohongshu cookie import and updates its session state", async () => {
  const user = userEvent.setup();
  window.sessionStorage.setItem("mediafetch-admin-token", "a".repeat(64));
  vi.mocked(getPlatformSession).mockResolvedValue({
    configured: false,
    updated_at: null,
    expires_at: null,
  });
  vi.mocked(uploadPlatformCookies).mockResolvedValue({
    configured: true,
    updated_at: 1_800_000_000,
    expires_at: null,
  });

  try {
    render(<PlatformCookiePanel />);
    const row = screen.getByRole("heading", { name: "小红书" }).closest("article")!;
    await waitFor(() => expect(getPlatformSession).toHaveBeenCalledWith("a".repeat(64), "xiaohongshu"));
    const input = within(row).getByLabelText("导入 Cookie") as HTMLInputElement;
    await waitFor(() => expect(input).toBeEnabled());
    const file = new File(
      ["# Netscape HTTP Cookie File\n.xiaohongshu.com\tTRUE\t/\tTRUE\t0\tweb_session\ttest-only\n"],
      "cookies.txt",
      { type: "text/plain" },
    );

    await user.upload(input, file);

    expect(uploadPlatformCookies).toHaveBeenCalledWith("a".repeat(64), "xiaohongshu", file);
    expect(await screen.findByText("小红书 会话已安全更新")).toBeInTheDocument();
    expect(within(row).getByText("已配置")).toBeInTheDocument();
  } finally {
    window.sessionStorage.removeItem("mediafetch-admin-token");
  }
});
