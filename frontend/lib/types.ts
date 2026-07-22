export type MediaFormat = {
  id: string;
  label: string;
  width: number | null;
  height: number | null;
  fps: number | null;
  extension: string;
  video_codec: string | null;
  audio_codec: string | null;
  bitrate: number | null;
  estimated_size: number | null;
  has_video: boolean;
  has_audio: boolean;
  requires_merge: boolean;
  preferred: boolean;
};

export type Inspection = {
  inspect_id: string;
  title: string;
  thumbnail: string | null;
  duration: number | null;
  uploader: string | null;
  platform: string;
  parser_hook: string | null;
  formats: MediaFormat[];
  audio_formats: MediaFormat[];
};

export type JobStatus =
  | "queued"
  | "inspecting"
  | "downloading"
  | "downloading_video"
  | "downloading_audio"
  | "merging"
  | "processing"
  | "ready"
  | "failed"
  | "cancelled"
  | "expired";

export type Job = {
  job_id: string;
  status: JobStatus;
  progress: number;
  speed: number | null;
  downloaded_bytes: number;
  total_bytes: number | null;
  eta: number | null;
  message: string;
  download_url: string | null;
  error: { code: string; message: string } | null;
};

export type ApiError = {
  error: {
    code: string;
    message: string;
    request_id: string;
  };
};

export type PlatformSessionStatus = {
  configured: boolean;
  updated_at: number | null;
  expires_at: number | null;
};

export type OperatorPlatform = "douyin" | "instagram" | "youtube";

export type BilibiliLoginStart = {
  login_id: string;
  qr_image: string;
  expires_in: number;
};

export type BilibiliLoginPoll = {
  status: "waiting_scan" | "waiting_confirm" | "ready" | "expired";
  message: string;
  expires_in: number;
};
