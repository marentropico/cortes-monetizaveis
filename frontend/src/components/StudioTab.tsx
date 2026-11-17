import { useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Code2,
  Crosshair,
  Download,
  ExternalLink,
  Eye,
  Film,
  Link2,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Save,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  Terminal,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../api";
import type {
  CutItem,
  DownloaderStatus,
  InputVideo,
  JobState,
  PinFrameInfo,
  PinnedFaceStatus,
  PresetOption,
  TranscriptMeta,
} from "../types";

interface StudioTabProps {
  videos: InputVideo[];
  cuts: CutItem[];
  transcript: TranscriptMeta | null;
  captionPresets: PresetOption[];
  layouts: PresetOption[];
  activeJob: JobState | null;
  onRefresh: () => Promise<void>;
  onStartJob: (jobId: string) => void;
  onNotify: (msg: string, type?: "ok" | "err") => void;
}

const STEPS = [
  { id: "transcribe", label: "Transcrição" },
  { id: "analyze", label: "Análise IA" },
  { id: "preview", label: "Preview" },
  { id: "render", label: "Render 9:16" },
  { id: "done", label: "Concluído" },
];

export function StudioTab({
  videos,
  cuts,
  transcript,
  captionPresets,
  layouts,
  activeJob,
  onRefresh,
  onStartJob,
  onNotify,
}: StudioTabProps) {
  const [selectedVideo, setSelectedVideo] = useState<string>(videos[0]?.filename ?? "");
  const [durationMode, setDurationMode] = useState("mix");
  const [language, setLanguage] = useState("pt");
  const [modelSize, setModelSize] = useState("base");
  const [layoutMode, setLayoutMode] = useState("auto");
  const [captionPreset, setCaptionPreset] = useState("hormozi");
  const [wordsPerLine, setWordsPerLine] = useState(3);
  const [maxCuts, setMaxCuts] = useState(0);
  const [burnCaptions, setBurnCaptions] = useState(true);
  const [useCache, setUseCache] = useState(true);
  const [distribute, setDistribute] = useState(true);
  const [skipExisting, setSkipExisting] = useState(false);
  const [useLlmPool, setUseLlmPool] = useState(true);
  const [precisionRetranscribe, setPrecisionRetranscribe] = useState(true);
  const [refineCaptions, setRefineCaptions] = useState(true);
  const [dynamicFaceTracking, setDynamicFaceTracking] = useState(true);
  const [faceTrackMode, setFaceTrackMode] = useState<"pinned" | "quick_detect">("pinned");

  // Streamer Face Pin
  const [pinnedStatus, setPinnedStatus] = useState<PinnedFaceStatus | null>(null);
  const [showPinModal, setShowPinModal] = useState(false);
  const [pinFrame, setPinFrame] = useState<PinFrameInfo | null>(null);
  const [pinTimestamp, setPinTimestamp] = useState(60);
  const [loadingPinFrame, setLoadingPinFrame] = useState(false);
  const [savingPin, setSavingPin] = useState(false);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showLogs, setShowLogs] = useState(true);
  const [showRawJson, setShowRawJson] = useState(false);
  const [localCuts, setLocalCuts] = useState<CutItem[]>(cuts);
  const [rawJson, setRawJson] = useState(JSON.stringify(cuts, null, 2));
  const [previewImgUrl, setPreviewImgUrl] = useState<string | null>(null);
  const [selectedRenderedUrl, setSelectedRenderedUrl] = useState<string | null>(null);
  const [busyPreview, setBusyPreview] = useState(false);
  const [savingCuts, setSavingCuts] = useState(false);

  // YouTube URL Downloader (YtoWave yt-dlp)
  const [dlStatus, setDlStatus] = useState<DownloaderStatus | null>(null);
  const [checkingDl, setCheckingDl] = useState(false);
  const [ytUrl, setYtUrl] = useState("");
  const [ytQuality, setYtQuality] = useState("1080p");

  const checkDownloader = async () => {
    setCheckingDl(true);
    try {
      const st = await api.downloaderStatus();
      setDlStatus(st);
    } catch {
      // ignore
    } finally {
      setCheckingDl(false);
    }
  };

  useEffect(() => {
    void checkDownloader();
  }, []);

  useEffect(() => {
    if (!selectedVideo && videos.length > 0) {
      setSelectedVideo(videos[0].filename);
    }
  }, [videos, selectedVideo]);

  useEffect(() => {
    if (!selectedVideo) {
      setPinnedStatus(null);
      return;
    }
    void api
      .getPinnedFace(selectedVideo)
      .then(setPinnedStatus)
      .catch(() => setPinnedStatus(null));
  }, [selectedVideo]);

  const loadPinFrameAt = async (ts: number) => {
    if (!selectedVideo) return;
    setLoadingPinFrame(true);
    try {
      const info = await api.loadPinFrame(selectedVideo, ts);
      setPinFrame(info);
      setPinTimestamp(info.timestamp);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao carregar frame", "err");
    } finally {
      setLoadingPinFrame(false);
    }
  };

  const openPinModal = () => {
    if (!selectedVideo) return;
    setShowPinModal(true);
    const vObj = videos.find((v) => v.filename === selectedVideo);
    const defaultTs = vObj && vObj.duration > 20 ? Math.min(60, Math.round(vObj.duration * 0.15)) : 5;
    void loadPinFrameAt(defaultTs);
  };

  const handlePinClick = async (normX: number, normY: number) => {
    if (!selectedVideo || !pinFrame) return;
    setSavingPin(true);
    try {
      const res = await api.pinFace(selectedVideo, pinFrame.timestamp, normX, normY);
      setPinnedStatus({ pinned: res.pinned, thumb_url: res.thumb_url, timestamp: res.timestamp });
      setShowPinModal(false);
      onNotify(res.message);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao pinnar rosto", "err");
    } finally {
      setSavingPin(false);
    }
  };

  const handleClearPin = async () => {
    if (!selectedVideo) return;
    try {
      const res = await api.clearPinnedFace(selectedVideo);
      setPinnedStatus({ pinned: false, thumb_url: null, timestamp: null });
      onNotify(res.message);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao remover pin", "err");
    }
  };

  useEffect(() => {
    setLocalCuts(cuts);
    setRawJson(JSON.stringify(cuts, null, 2));
  }, [cuts]);

  useEffect(() => {
    const res = activeJob?.result as
      | {
          preview_url?: string;
          rendered?: Array<{ media_url: string; title: string }>;
          downloaded_filename?: string;
        }
      | null
      | undefined;
    if (res?.preview_url) setPreviewImgUrl(res.preview_url);
    if (res?.rendered && res.rendered.length > 0) {
      setSelectedRenderedUrl(res.rendered[0].media_url);
    }
    if (res?.downloaded_filename) {
      setSelectedVideo(res.downloaded_filename);
      setYtUrl("");
    }
  }, [activeJob?.result]);

  const handleDownloadUrl = async () => {
    if (!ytUrl.trim()) {
      onNotify("Cole o link do vídeo do YouTube.", "err");
      return;
    }
    try {
      const { job_id } = await api.downloadYoutubeUrl(ytUrl.trim(), ytQuality);
      onStartJob(job_id);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao iniciar download", "err");
    }
  };

  const isRunning = activeJob?.status === "running";
  const renderedList =
    ((activeJob?.result as { rendered?: Array<{ media_url: string; title: string; duration: number }> } | null)
      ?.rendered ?? []);

  const runMode = async (mode: "full" | "transcribe" | "analyze" | "render") => {
    try {
      const { job_id } = await api.runPipeline({
        mode,
        video_name: selectedVideo || null,
        language,
        duration_mode: durationMode,
        max_cuts: maxCuts,
        model_size: modelSize,
        layout_mode: layoutMode,
        caption_preset: captionPreset,
        words_per_line: wordsPerLine,
        burn_captions: burnCaptions,
        use_cache: useCache,
        distribute_across_video: distribute,
        skip_existing: skipExisting,
        use_llm_pool: useLlmPool,
        precision_retranscribe: precisionRetranscribe,
        refine_captions_with_llm: refineCaptions,
        dynamic_face_tracking: dynamicFaceTracking,
        face_track_mode: faceTrackMode,
      });
      onStartJob(job_id);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao iniciar pipeline", "err");
    }
  };

  const handlePreviewLayout = async () => {
    if (!selectedVideo) return;
    setBusyPreview(true);
    try {
      const res = await api.previewLayout(selectedVideo, layoutMode);
      setPreviewImgUrl(res.preview_url);
      setSelectedRenderedUrl(null);
      onNotify(res.message);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro no preview", "err");
    } finally {
      setBusyPreview(false);
    }
  };

  const handleSaveCuts = async () => {
    setSavingCuts(true);
    try {
      let payload = localCuts;
      if (showRawJson) {
        const parsed = JSON.parse(rawJson);
        if (!Array.isArray(parsed)) throw new Error("O JSON precisa ser uma lista de cortes.");
        payload = parsed;
      }
      const res = await api.saveCuts(payload);
      setLocalCuts(res.cuts);
      setRawJson(JSON.stringify(res.cuts, null, 2));
      onNotify(res.message);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao salvar cortes", "err");
    } finally {
      setSavingCuts(false);
    }
  };

  const updateCutField = (idx: number, field: keyof CutItem, value: string | number) => {
    setLocalCuts((prev) =>
      prev.map((c, i) => (i === idx ? { ...c, [field]: value } : c))
    );
  };

  const addEmptyCut = () => {
    const nextId = localCuts.length > 0 ? Math.max(...localCuts.map((c) => Number(c.id) || 0)) + 1 : 1;
    setLocalCuts((prev) => [
      ...prev,
      {
        id: nextId,
        title: `novo_corte_${nextId}_60s`,
        start: 0,
        end: 60,
        duration_type: "60s",
        hook_text: "OLHA ESSE MOMENTO!",
        context_reason: "Adicionado manualmente",
      },
    ]);
  };

  const removeCut = (idx: number) => {
    setLocalCuts((prev) => prev.filter((_, i) => i !== idx));
  };

  const activeStepIdx = activeJob ? STEPS.findIndex((s) => s.id === activeJob.step) : -1;

  return (
    <div className="space-y-5">
      {/* Main Control Card */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 shadow-xl">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <div className="lg:col-span-6">
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-slate-400">
              Vídeo de Entrada (input/)
            </label>
            <div className="flex gap-2">
              <select
                value={selectedVideo}
                onChange={(e) => setSelectedVideo(e.target.value)}
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2.5 text-sm text-slate-100 outline-none focus:border-sky-500"
              >
                {videos.length === 0 && <option value="">Nenhum vídeo em input/</option>}
                {videos.map((v) => (
                  <option key={v.filename} value={v.filename}>
                    {v.filename} ({v.duration}s • {v.width}x{v.height}) {v.cached ? "✓ Cache" : ""}
                  </option>
                ))}
              </select>
              <button
                onClick={() => void onRefresh()}
                title="Atualizar lista"
                className="rounded-xl border border-slate-700 bg-slate-950 px-3 text-slate-300 transition hover:border-slate-600 hover:text-white"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="lg:col-span-3">
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-slate-400">
              Range de Duração
            </label>
            <select
              value={durationMode}
              onChange={(e) => setDurationMode(e.target.value)}
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2.5 text-sm text-slate-100 outline-none focus:border-sky-500"
            >
              <option value="mix">Mix Inteligente (30s + 60s + 90s)</option>
              <option value="30s">30s (Rápido / Punchline)</option>
              <option value="60s">60s (Padrão Contextual)</option>
              <option value="90s">90s (Storytelling / Partida)</option>
            </select>
          </div>

          <div className="flex items-end lg:col-span-3">
            <button
              disabled={isRunning || !selectedVideo}
              onClick={() => void runMode("full")}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-sky-500 to-indigo-600 px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-sky-500/20 transition hover:from-sky-400 hover:to-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isRunning ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Processando...
                </>
              ) : (
                <>
                  <Sparkles className="h-4 w-4" />
                  Gerar Cortes 1-Click
                </>
              )}
            </button>
          </div>
        </div>

        {/* YouTube URL Downloader via YtoWave yt-dlp */}
        <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-3.5">
          {dlStatus?.available ? (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="flex flex-1 items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2">
                <Link2 className="h-4 w-4 shrink-0 text-rose-400" />
                <input
                  value={ytUrl}
                  onChange={(e) => setYtUrl(e.target.value)}
                  placeholder="Cole o link do YouTube para baixar direto em input/ (ex: https://youtube.com/watch?v=...)"
                  className="w-full bg-transparent text-xs text-slate-100 placeholder-slate-500 outline-none"
                />
              </div>
              <select
                value={ytQuality}
                onChange={(e) => setYtQuality(e.target.value)}
                className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none"
              >
                <option value="1080p">1080p (MP4)</option>
                <option value="best">Máxima (MP4)</option>
                <option value="720p">720p (MP4)</option>
              </select>
              <button
                disabled={isRunning || !ytUrl.trim()}
                onClick={() => void handleDownloadUrl()}
                title={`Usando: ${dlStatus.yt_dlp_path}`}
                className="flex items-center justify-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {activeJob?.kind === "download" && isRunning ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                Baixar para input/
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-xs text-slate-300">
                <span className="font-semibold text-amber-300">YtoWave / yt-dlp.exe não encontrado.</span>{" "}
                Instale o YtoWave para baixar vídeos do YouTube direto na pasta{" "}
                <code className="text-sky-400">input/</code> e depois reabra o programa ou clique em verificar.
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={dlStatus?.download_page_url || "https://marentropico.github.io/ytowave/"}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1.5 rounded-xl bg-rose-600 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-rose-500"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  Baixar YtoWave
                </a>
                <button
                  disabled={checkingDl}
                  onClick={() => void checkDownloader()}
                  className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 hover:border-sky-500/50 disabled:opacity-50"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${checkingDl ? "animate-spin" : ""}`} />
                  Verificar Novamente
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Advanced Settings Toggle */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800/80 pt-3">
          <button
            onClick={() => setShowAdvanced((v) => !v)}
            className="flex items-center gap-2 text-xs font-medium text-slate-300 transition hover:text-sky-400"
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Configurações Avançadas (Whisper, Pool IA, Legendas, Enquadramento)
            {showAdvanced ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={faceTrackMode}
              onChange={(e) => setFaceTrackMode(e.target.value as "pinned" | "quick_detect")}
              title="Modo de rastreamento do Circle Crop"
              className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-200 outline-none focus:border-sky-500"
            >
              <option value="pinned">🎯 Streamer Pinnado</option>
              <option value="quick_detect">🎲 Quick Detect (Memes / Vários Rostos)</option>
            </select>
            {faceTrackMode === "pinned" && pinnedStatus?.pinned && pinnedStatus.thumb_url && (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-200">
                <img
                  src={pinnedStatus.thumb_url}
                  alt="Streamer pinnado"
                  className="h-5 w-5 rounded-full object-cover"
                />
                <span>Rosto pinnado</span>
                <button
                  onClick={() => void handleClearPin()}
                  title="Remover pin"
                  className="text-emerald-300/70 hover:text-white"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
            {faceTrackMode === "pinned" && (
              <button
                disabled={isRunning || !selectedVideo}
                onClick={openPinModal}
                className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-amber-300 transition hover:border-amber-500/60 disabled:opacity-50"
              >
                <Crosshair className="h-3.5 w-3.5" />
                {pinnedStatus?.pinned ? "Trocar Rosto Pinnado" : "Pinnar Streamer"}
              </button>
            )}
            <button
              disabled={isRunning || !selectedVideo}
              onClick={() => void handlePreviewLayout()}
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:border-sky-500/60 disabled:opacity-50"
            >
              {busyPreview ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}
              Preview 9:16
            </button>
          </div>
        </div>

        {showAdvanced && (
          <div className="mt-4 space-y-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <div>
                <label className="mb-1 block text-xs text-slate-400">Idioma</label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-xs text-slate-100"
                >
                  <option value="pt">Português (PT-BR)</option>
                  <option value="en">Inglês (EN)</option>
                  <option value="auto">Automático</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">Whisper (Passada 1)</label>
                <select
                  value={modelSize}
                  onChange={(e) => setModelSize(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-xs text-slate-100"
                >
                  <option value="tiny">tiny</option>
                  <option value="base">base</option>
                  <option value="small">small</option>
                  <option value="medium">medium</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">Enquadramento 9:16</label>
                <select
                  value={layoutMode}
                  onChange={(e) => setLayoutMode(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-xs text-slate-100"
                >
                  {layouts.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">Estilo da Legenda</label>
                <select
                  value={captionPreset}
                  onChange={(e) => setCaptionPreset(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-xs text-slate-100"
                >
                  {captionPresets.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">
                  Palavras/Bloco ({wordsPerLine}) | Teto ({maxCuts === 0 ? "Max" : maxCuts})
                </label>
                <div className="flex items-center gap-2 pt-1">
                  <input
                    type="range"
                    min={2}
                    max={5}
                    value={wordsPerLine}
                    onChange={(e) => setWordsPerLine(Number(e.target.value))}
                    className="w-1/2 accent-sky-500"
                  />
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={maxCuts}
                    onChange={(e) => setMaxCuts(Number(e.target.value))}
                    className="w-1/2 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs"
                    title="0 = Ilimitado"
                  />
                </div>
              </div>
            </div>

            <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-300">
              {[
                ["Queimar Legendas (.ass)", burnCaptions, setBurnCaptions],
                ["Usar Cache", useCache, setUseCache],
                ["Distribuir no VOD (+1h)", distribute, setDistribute],
                ["Pular já renderizados", skipExisting, setSkipExisting],
                ["Curadoria Pool IA", useLlmPool, setUseLlmPool],
                ["Passada 2 (Whisper small)", precisionRetranscribe, setPrecisionRetranscribe],
                ["Lapidar Legendas Pool IA", refineCaptions, setRefineCaptions],
                ["Tracking Dinâmico + Auto-Fade Círculo", dynamicFaceTracking, setDynamicFaceTracking],
              ].map(([label, val, setter]) => (
                <label key={String(label)} className="flex cursor-pointer items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={Boolean(val)}
                    onChange={(e) => (setter as (v: boolean) => void)(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-900 text-sky-500"
                  />
                  {String(label)}
                </label>
              ))}
            </div>

            <div className="flex flex-wrap gap-2 border-t border-slate-800 pt-3">
              <span className="self-center text-xs text-slate-400">Etapas manuais:</span>
              <button
                disabled={isRunning || !selectedVideo}
                onClick={() => void runMode("transcribe")}
                className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs hover:border-sky-500/50 disabled:opacity-50"
              >
                1. Transcrever Áudio
              </button>
              <button
                disabled={isRunning}
                onClick={() => void runMode("analyze")}
                className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs hover:border-sky-500/50 disabled:opacity-50"
              >
                2. Analisar Contexto
              </button>
              <button
                disabled={isRunning || !selectedVideo}
                onClick={() => void runMode("render")}
                className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs hover:border-sky-500/50 disabled:opacity-50"
              >
                3. Renderizar Cortes
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Live Download Progress */}
      {activeJob && activeJob.kind === "download" && (
        <div className="rounded-2xl border border-rose-500/30 bg-slate-900/70 p-4">
          <div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-200">
            <span className="flex items-center gap-2">
              {activeJob.status === "running" ? (
                <Loader2 className="h-4 w-4 animate-spin text-rose-400" />
              ) : activeJob.status === "done" ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              ) : (
                <span className="h-2.5 w-2.5 rounded-full bg-rose-500" />
              )}
              {activeJob.title}
            </span>
            <span className="font-mono text-sky-400">{activeJob.progress}%</span>
          </div>
          <div className="mb-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full bg-gradient-to-r from-rose-500 to-orange-400 transition-all"
              style={{ width: `${activeJob.progress}%` }}
            />
          </div>
          <div className="max-h-28 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950 p-2.5 font-mono text-[11px] text-slate-300">
            {activeJob.logs.slice(-15).map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        </div>
      )}

      {/* Live Progress & Logs */}
      {activeJob && activeJob.kind === "pipeline" && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              {activeJob.status === "running" ? (
                <Loader2 className="h-4 w-4 animate-spin text-sky-400" />
              ) : activeJob.status === "done" ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              ) : (
                <span className="h-2.5 w-2.5 rounded-full bg-rose-500" />
              )}
              <span className="text-sm font-semibold text-slate-100">{activeJob.title}</span>
              <span className="rounded-full bg-slate-800 px-2.5 py-0.5 text-xs font-mono text-sky-300">
                {activeJob.progress}%
              </span>
            </div>
            <button
              onClick={() => setShowLogs((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <Terminal className="h-3.5 w-3.5" />
              {showLogs ? "Ocultar logs" : "Ver logs"}
            </button>
          </div>

          {/* Stepper */}
          <div className="mb-3 grid grid-cols-5 gap-2">
            {STEPS.map((st, idx) => {
              const done = activeJob.status === "done" || idx < activeStepIdx;
              const current = activeJob.status === "running" && idx === activeStepIdx;
              return (
                <div key={st.id} className="space-y-1">
                  <div
                    className={`h-1.5 rounded-full transition-all ${
                      done
                        ? "bg-emerald-500"
                        : current
                        ? "animate-pulse bg-sky-500"
                        : "bg-slate-800"
                    }`}
                  />
                  <div
                    className={`text-[11px] font-medium ${
                      done ? "text-emerald-400" : current ? "text-sky-400" : "text-slate-500"
                    }`}
                  >
                    {st.label}
                  </div>
                </div>
              );
            })}
          </div>

          {showLogs && (
            <div className="max-h-44 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-300">
              {activeJob.logs.slice(-40).map((line, i) => (
                <div key={i} className="whitespace-pre-wrap">
                  {line}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Cuts Editor + Preview Split */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        {/* Left: Visual Cuts Editor */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 xl:col-span-8">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="flex items-center gap-2 text-base font-semibold text-white">
                <Scissors className="h-4 w-4 text-sky-400" />
                Cortes Planejados ({localCuts.length})
              </h2>
              {transcript && (
                <p className="text-xs text-slate-400">
                  Transcrição ativa: <span className="text-slate-200">{transcript.video_file}</span> ({transcript.language} • {transcript.segments_count} segmentos)
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  if (!showRawJson) setRawJson(JSON.stringify(localCuts, null, 2));
                  setShowRawJson((v) => !v);
                }}
                className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-300 hover:text-white"
              >
                <Code2 className="h-3.5 w-3.5" />
                {showRawJson ? "Modo Visual" : "JSON"}
              </button>
              {!showRawJson && (
                <button
                  onClick={addEmptyCut}
                  className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200 hover:border-sky-500/50"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Adicionar
                </button>
              )}
              <button
                disabled={savingCuts}
                onClick={() => void handleSaveCuts()}
                className="flex items-center gap-1.5 rounded-lg bg-sky-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
              >
                <Save className="h-3.5 w-3.5" />
                Salvar Cortes
              </button>
            </div>
          </div>

          {showRawJson ? (
            <textarea
              value={rawJson}
              onChange={(e) => setRawJson(e.target.value)}
              rows={16}
              className="w-full rounded-xl border border-slate-700 bg-slate-950 p-3 font-mono text-xs text-slate-200 outline-none focus:border-sky-500"
            />
          ) : localCuts.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-800 py-12 text-center text-sm text-slate-400">
              Nenhum corte planejado em <code className="text-sky-400">temp/cuts.json</code>. Clique em{" "}
              <strong className="text-slate-200">Gerar Cortes 1-Click</strong> acima.
            </div>
          ) : (
            <div className="max-h-[540px] space-y-3 overflow-y-auto pr-1">
              {localCuts.map((cut, idx) => {
                const dur = Math.max(0, Number(cut.end) - Number(cut.start)).toFixed(1);
                return (
                  <div
                    key={`${cut.id}-${idx}`}
                    className="rounded-xl border border-slate-800 bg-slate-950/70 p-3.5 transition hover:border-slate-700"
                  >
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="rounded-md bg-sky-500/15 px-2 py-0.5 font-mono text-xs font-bold text-sky-400">
                          #{cut.id}
                        </span>
                        <span className="rounded-md bg-indigo-500/15 px-2 py-0.5 text-xs font-medium text-indigo-300">
                          {cut.duration_type} ({dur}s)
                        </span>
                      </div>
                      <button
                        onClick={() => removeCut(idx)}
                        className="text-slate-500 transition hover:text-rose-400"
                        title="Remover corte"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>

                    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-12">
                      <div className="sm:col-span-6">
                        <label className="text-[11px] text-slate-400">Título do Arquivo</label>
                        <input
                          value={cut.title}
                          onChange={(e) => updateCutField(idx, "title", e.target.value)}
                          className="mt-0.5 w-full rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-100 outline-none focus:border-sky-500"
                        />
                      </div>
                      <div className="sm:col-span-3">
                        <label className="text-[11px] text-slate-400">Início (s)</label>
                        <input
                          type="number"
                          step="0.1"
                          value={cut.start}
                          onChange={(e) => updateCutField(idx, "start", Number(e.target.value))}
                          className="mt-0.5 w-full rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-100 outline-none focus:border-sky-500"
                        />
                      </div>
                      <div className="sm:col-span-3">
                        <label className="text-[11px] text-slate-400">Fim (s)</label>
                        <input
                          type="number"
                          step="0.1"
                          value={cut.end}
                          onChange={(e) => updateCutField(idx, "end", Number(e.target.value))}
                          className="mt-0.5 w-full rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-100 outline-none focus:border-sky-500"
                        />
                      </div>
                      <div className="sm:col-span-12">
                        <label className="text-[11px] text-slate-400">Hook Visual (Topo do Short)</label>
                        <input
                          value={cut.hook_text}
                          onChange={(e) => updateCutField(idx, "hook_text", e.target.value)}
                          className="mt-0.5 w-full rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 text-xs font-semibold text-amber-300 outline-none focus:border-sky-500"
                        />
                      </div>
                    </div>
                    {cut.context_reason && (
                      <p className="mt-2 text-[11px] text-slate-400">{cut.context_reason}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Right: 9:16 Preview */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5 xl:col-span-4">
          <h2 className="mb-3 flex items-center gap-2 text-base font-semibold text-white">
            <Film className="h-4 w-4 text-indigo-400" />
            Preview 9:16
          </h2>

          {renderedList.length > 0 && (
            <div className="mb-3 space-y-1.5">
              {renderedList.map((r) => (
                <button
                  key={r.media_url}
                  onClick={() => setSelectedRenderedUrl(r.media_url)}
                  className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-xs transition ${
                    selectedRenderedUrl === r.media_url
                      ? "border-sky-500 bg-sky-500/10 text-sky-200"
                      : "border-slate-800 bg-slate-950 text-slate-300 hover:border-slate-700"
                  }`}
                >
                  <span className="flex items-center gap-2 truncate">
                    <Play className="h-3.5 w-3.5 shrink-0 text-sky-400" />
                    <span className="truncate">{r.title}</span>
                  </span>
                  <span className="ml-2 shrink-0 text-slate-400">{r.duration}s</span>
                </button>
              ))}
            </div>
          )}

          <div className="flex aspect-[9/16] max-h-[500px] w-full items-center justify-center overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
            {selectedRenderedUrl ? (
              <video
                key={selectedRenderedUrl}
                src={selectedRenderedUrl}
                controls
                className="h-full w-full object-contain"
              />
            ) : previewImgUrl ? (
              <img
                src={previewImgUrl}
                alt="Preview 9:16"
                className="h-full w-full object-contain"
              />
            ) : (
              <div className="px-6 text-center text-xs text-slate-500">
                Clique em <strong className="text-slate-300">Preview 9:16</strong> ou execute o pipeline para visualizar o enquadramento vertical aqui.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Streamer Face Pin Modal */}
      {showPinModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-3xl rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="flex items-center gap-2 text-base font-semibold text-white">
                  <Crosshair className="h-4 w-4 text-amber-400" />
                  Pinnar Rosto do Streamer
                </h3>
                <p className="text-xs text-slate-400">
                  Navegue até um momento onde o streamer apareça bem e clique em cima do rosto dele.
                </p>
              </div>
              <button
                onClick={() => setShowPinModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-slate-800 bg-slate-950/70 p-3">
              <span className="text-xs text-slate-400">Momento (s):</span>
              <input
                type="range"
                min={0}
                max={pinFrame?.duration || 300}
                step={1}
                value={pinTimestamp}
                onChange={(e) => setPinTimestamp(Number(e.target.value))}
                className="flex-1 accent-amber-400"
              />
              <input
                type="number"
                min={0}
                max={pinFrame?.duration || 99999}
                value={pinTimestamp}
                onChange={(e) => setPinTimestamp(Number(e.target.value))}
                className="w-20 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-white"
              />
              <button
                disabled={loadingPinFrame}
                onClick={() => void loadPinFrameAt(pinTimestamp)}
                className="flex items-center gap-1.5 rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
              >
                {loadingPinFrame ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Carregar Frame
              </button>
            </div>

            <div className="relative overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
              {loadingPinFrame || savingPin ? (
                <div className="flex h-80 items-center justify-center gap-2 text-xs text-slate-400">
                  <Loader2 className="h-5 w-5 animate-spin text-amber-400" />
                  {savingPin ? "Extraindo assinatura facial..." : "Carregando frame..."}
                </div>
              ) : pinFrame ? (
                <div className="relative inline-block w-full cursor-crosshair">
                  <img
                    src={pinFrame.frame_url}
                    alt="Selecionar rosto"
                    onClick={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      const nx = (e.clientX - rect.left) / rect.width;
                      const ny = (e.clientY - rect.top) / rect.height;
                      void handlePinClick(nx, ny);
                    }}
                    className="block w-full select-none"
                  />
                  {pinFrame.faces.map((f, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handlePinClick(f.cx, f.cy);
                      }}
                      style={{
                        left: `${f.x * 100}%`,
                        top: `${f.y * 100}%`,
                        width: `${f.w * 100}%`,
                        height: `${f.h * 100}%`,
                      }}
                      title="Clique para pinnar este rosto"
                      className="absolute rounded-md border-2 border-emerald-400 bg-emerald-400/10 transition hover:border-amber-400 hover:bg-amber-400/20"
                    />
                  ))}
                </div>
              ) : null}
            </div>

            <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
              <span>
                {pinFrame
                  ? `${pinFrame.faces.length} rosto(s) detectado(s) em ${pinFrame.timestamp}s`
                  : ""}
              </span>
              <span>Clique em qualquer retângulo verde (ou diretamente no rosto) para pinnar.</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
