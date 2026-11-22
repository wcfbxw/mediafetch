import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { GalleryGrid } from "@/components/GalleryGrid";
import type { GalleryItem } from "@/lib/types";

const items: GalleryItem[] = [
  {
    index: 1,
    extension: "png",
    width: 1440,
    height: 1920,
    preview_url: "/api/v1/stream/token-1?inline=true",
    download_url: "/api/v1/stream/token-1",
    live_video_url: "/api/v1/stream/token-1-live",
  },
  {
    index: 2,
    extension: "jpg",
    width: 1080,
    height: 1440,
    preview_url: "/api/v1/stream/token-2?inline=true",
    download_url: "/api/v1/stream/token-2",
    live_video_url: null,
  },
];

test("renders clean gallery items, live photo link, and zip pack button", () => {
  render(<GalleryGrid items={items} zipUrl="/api/v1/gallery/zip-token" />);

  expect(screen.getByText(/共提取 2 张无水印高清原图/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /一键打包下载全部/ })).toHaveAttribute(
    "href",
    "/api/v1/gallery/zip-token",
  );
  expect(screen.getByRole("link", { name: "实况 MP4" })).toHaveAttribute(
    "href",
    "/api/v1/stream/token-1-live",
  );
  expect(screen.getByRole("link", { name: "下载原图 (PNG)" })).toHaveAttribute(
    "href",
    "/api/v1/stream/token-1",
  );
});
