import type {
  AnalyticsPayload,
  CutItem,
  DiagnosticsInfo,
  HealthInfo,
  InputVideo,
  JobState,
  PresetOption,
  RenderedClip,
  ThumbnailItem,
  TranscriptMeta,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = `Erro HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) detail = String(data.detail);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthInfo>("/api/health"),

  presets: () =>
    request<{ caption_presets: PresetOption[]; layouts: PresetOption[] }>("/api/presets"),

  diagnostics: () => request<DiagnosticsInfo>("/api/diagnostics"),

  openOutputFolder: () =>
    request<{ message: string }>("/api/system/open-output", { method: "POST" }),

  clearRecords: (clear_input_caches = false) =>
    request<{
      message: string;
      input_videos: string[];
      removed_outputs: number;
      removed_temp_files: number;
      removed_project_caches: number;
    }>("/api/system/clear-records", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clear_input_caches }),
    }),

  exportRemotionProps: () =>
    request<{ message: string }>("/api/remotion/export", { method: "POST" }),

  launchRemotionStudio: () =>
    request<{ message: string }>("/api/remotion/launch", { method: "POST" }),

  listVideos: () => request<{ videos: InputVideo[] }>("/api/videos"),

  uploadVideo: async (file: File): Promise<{ filename: string; message: string }> => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/videos/upload", { method: "POST", body: fd });
  },

  generateDemo: (language: string, duration: number) =>
    request<{ filename: string; message: string }>("/api/videos/demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language, duration }),
    }),

  deleteVideo: (filename: string) =>
    request<{ message: string }>(`/api/videos/${encodeURIComponent(filename)}`, {
      method: "DELETE",
    }),

  pipelineState: () =>
    request<{
      cuts: CutItem[];
      transcript: TranscriptMeta | null;
      current_job: JobState | null;
    }>("/api/pipeline/state"),

  saveCuts: (cuts: CutItem[]) =>
    request<{ cuts: CutItem[]; message: string }>("/api/pipeline/cuts", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cuts }),
    }),

  previewLayout: (video_name: string, layout_mode: string) =>
    request<{ preview_url: string; message: string }>("/api/pipeline/preview-layout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_name, layout_mode }),
    }),

  runPipeline: (payload: Record<string, unknown>) =>
    request<{ job_id: string }>("/api/pipeline/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  currentJob: () => request<{ job: JobState | null }>("/api/jobs/current"),

  listClips: (source = "Todos", duration = "Todos") =>
    request<{ clips: RenderedClip[]; sources: string[] }>(
      `/api/clips?source=${encodeURIComponent(source)}&duration=${encodeURIComponent(duration)}`
    ),

  updateQueueItem: (payload: {
    video_path: string;
    youtube_title: string;
    youtube_description: string;
    visibility: string;
  }) =>
    request<{ message: string }>("/api/youtube/queue/item", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  syncYouTube: () => request<{ message: string }>("/api/youtube/sync", { method: "POST" }),

  launchChrome: () =>
    request<{ port: number; ready: boolean; message: string }>("/api/youtube/chrome/launch", {
      method: "POST",
    }),

  chromeStatus: () =>
    request<{ ready: boolean; message: string }>("/api/youtube/chrome/status"),

  uploadYouTube: (selected_paths: string[], visibility: string, skip_posted: boolean) =>
    request<{ job_id: string }>("/api/youtube/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_paths, visibility, skip_posted }),
    }),

  listThumbnails: () => request<{ thumbnails: ThumbnailItem[] }>("/api/thumbnails"),

  generateThumbnails: (selected_paths: string[]) =>
    request<{ count: number; message: string }>("/api/thumbnails/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_paths }),
    }),

  uploadThumbnails: (selected_paths: string[]) =>
    request<{ updated: number; total: number; message: string }>("/api/thumbnails/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ selected_paths }),
    }),

  getAnalytics: () => request<AnalyticsPayload>("/api/analytics"),

  saveAnalyticsConfig: (api_key: string, channel_ref: string) =>
    request<{ message: string }>("/api/analytics/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key, channel_ref }),
    }),

  fetchAnalyticsApi: (api_key: string, channel_ref: string) =>
    request<AnalyticsPayload>("/api/analytics/fetch-api", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key, channel_ref }),
    }),

  scrapeStudioAnalytics: () =>
    request<AnalyticsPayload>("/api/analytics/scrape-studio", { method: "POST" }),

  runAiCoach: () =>
    request<{ advice: string }>("/api/analytics/ai-coach", { method: "POST" }),
};

export function subscribeToJob(
  jobId: string,
  handlers: {
    onLogs: (lines: string[]) => void;
    onState: (state: Partial<JobState>) => void;
    onEnd: () => void;
  }
): () => void {
  const es = new EventSource(`/api/jobs/${jobId}/stream`);
  es.addEventListener("logs", (ev) => {
    try {
      const data = JSON.parse((ev as MessageEvent).data);
      if (Array.isArray(data.lines)) handlers.onLogs(data.lines);
    } catch {
      // ignore
    }
  });
  es.addEventListener("state", (ev) => {
    try {
      const data = JSON.parse((ev as MessageEvent).data) as Partial<JobState>;
      handlers.onState(data);
      if (data.status === "done" || data.status === "error") {
        es.close();
        handlers.onEnd();
      }
    } catch {
      // ignore
    }
  });
  es.onerror = () => {
    es.close();
    handlers.onEnd();
  };
  return () => es.close();
}
