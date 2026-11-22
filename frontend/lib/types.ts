export type DeliveryMode = "stream" | "async_merge";
export type MediaType = "video" | "gallery" | "audio";

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
  watermark_free?: boolean;
  delivery_mode?: DeliveryMode;
  stream_url?: string | null;
};

export type GalleryItem = {
  index: number;
  extension: string;
  width: number | null;
  height: number | null;
  preview_url: string;
  download_url: string;
  live_video_url: string | null;
};

export type Inspection = {
  inspect_id: string;
  title: string;
  thumbnail: string | null;
  duration: number | null;
  uploader: string | null;
  platform: string;
  engine?: string | null;
  media_type?: MediaType;
  watermark_free?: boolean;
  parser_hook: string | null;
  formats: MediaFormat[];
  audio_formats: MediaFormat[];
  gallery?: GalleryItem[];
  gallery_zip_url?: string | null;
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

export type AuthConfig = {
  access_token_required: boolean;
};

export type PlatformSessionStatus = {
  configured: boolean;
  updated_at: number | null;
  expires_at: number | null;
};

export type OperatorPlatform =
  | "douyin"
  | "tiktok"
  | "xiaohongshu"
  | "kuaishou"
  | "weibo"
  | "twitter"
  | "instagram"
  | "youtube";

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
