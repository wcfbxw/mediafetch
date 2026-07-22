import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { FormatSelector } from "@/components/FormatSelector";
import type { MediaFormat } from "@/lib/types";

const formats: MediaFormat[] = [
  {
    id: "1080",
    label: "1080P",
    width: 1920,
    height: 1080,
    fps: 30,
    extension: "mp4",
    video_codec: "avc1",
    audio_codec: null,
    bitrate: 2000,
    estimated_size: 1000,
    has_video: true,
    has_audio: false,
    requires_merge: true,
    preferred: true,
  },
  {
    id: "1080-advanced",
    label: "1080P",
    width: 1920,
    height: 1080,
    fps: 60,
    extension: "webm",
    video_codec: "vp9",
    audio_codec: null,
    bitrate: 2500,
    estimated_size: 1200,
    has_video: true,
    has_audio: false,
    requires_merge: true,
    preferred: false,
  },
];

test("shows recommended formats and reveals advanced alternatives", async () => {
  const user = userEvent.setup();
  const onSelect = vi.fn();
  render(
    <FormatSelector
      formats={formats}
      audioFormats={[]}
      selectedId="1080"
      selectedAudioId={null}
      onSelect={onSelect}
      onAudioSelect={() => undefined}
    />,
  );
  expect(screen.getAllByRole("radio")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "显示高级格式" }));
  expect(screen.getAllByRole("radio")).toHaveLength(2);
  await user.click(screen.getAllByRole("radio")[1]);
  expect(onSelect).toHaveBeenCalledWith(formats[1]);
});
