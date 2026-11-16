export interface JobState {
  job_id: string;
  kind: "pipeline" | "upload" | "download";
  title: string;
  status: "running" | "done" | "error";
  step: string;
  progress: number;
  queue_index?: number;
  queue_total?: number;
  current_video?: string | null;
  logs: string[];
  result: Record<string, unknown> | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface HealthInfo {
  ok: boolean;
  encoder: string;
  pool_active: boolean;
  clips_count: number;
  current_job: JobState | null;
}

export interface DownloaderStatus {
  available: boolean;
  yt_dlp_path: string;
  download_page_url: string;
}

export interface PresetOption {
  id: string;
  label: string;
}

export interface InputVideo {
  filename: string;
  width: number;
  height: number;
  duration: number;
  fps: number;
  size_mb: number;
  has_audio: boolean;
  cached: boolean;
  media_url: string;
}

export interface CutItem {
  id: number;
  title: string;
  start: number;
  end: number;
  duration_type: string;
  hook_text: string;
  context_reason: string;
}

export interface TranscriptMeta {
  video_file: string;
  language: string;
  segments_count: number;
  duration: number;
  preview_segments: Array<{ start: number; end: number; text: string }>;
}

export interface RenderedClip {
  id: number;
  title: string;
  source_video: string;
  source_stem: string;
  output_path: string;
  media_url: string;
  filename: string;
  start: number;
  end: number;
  duration: number;
  duration_type: string;
  size_mb: number;
  layout_mode: string;
  encoder: string;
  hook_text: string;
  context_reason: string;
  youtube_status: "posted" | "pending";
  youtube_url: string;
  youtube_title: string;
  youtube_description: string;
  visibility: "PUBLIC" | "UNLISTED" | "PRIVATE";
}

export interface ThumbnailItem {
  path: string;
  filename: string;
  media_url: string;
}

export interface AnalyticsVideo {
  title: string;
  bucket: string;
  duration_sec: number;
  views: number;
  likes: number;
  comments: number;
  engagement_pct: number;
  studio_cells?: string[];
  url: string;
}

export interface AnalyticsBucket {
  count: number;
  avg_views: number;
  avg_likes: number;
  avg_engagement_pct: number;
}

export interface AnalyticsData {
  channel: {
    id?: string;
    channel_id?: string;
    title?: string;
    subscribers?: number;
    total_views?: number;
    video_count?: number;
  };
  updated_at?: string;
  fetched_at?: string;
  source?: string;
  bucket_summary?: Record<string, AnalyticsBucket>;
  videos: AnalyticsVideo[];
}

export interface AnalyticsPayload {
  has_data: boolean;
  api_key_masked: string;
  has_api_key: boolean;
  channel_ref: string;
  data: AnalyticsData | null;
  message?: string;
}

export interface DiagnosticsInfo {
  ffmpeg_path: string;
  ffprobe_path: string;
  has_subtitles_filter: boolean;
  best_h264_encoder: string;
  cuda_count: number;
  whisper_device: string;
  mediapipe_version: string;
  mediapipe_mode: string;
  remotion_available: boolean;
  remotion_template: boolean;
  repos: Array<{
    name: string;
    folder: string;
    installed: boolean;
    role: string;
  }>;
}
