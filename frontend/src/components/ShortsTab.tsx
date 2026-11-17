import { useEffect, useState } from "react";
import {
  CheckCircle2,
  CheckSquare,
  Chrome,
  Clock,
  Edit3,
  ExternalLink,
  FolderOpen,
  Image as ImageIcon,
  Loader2,
  RefreshCw,
  Rocket,
  Save,
  Square,
  Trophy,
  Upload,
  X,
} from "lucide-react";
import { api } from "../api";
import type { JobState, RenderedClip, ThumbnailItem } from "../types";

interface ShortsTabProps {
  activeJob: JobState | null;
  refreshKey?: number;
  onStartJob: (jobId: string) => void;
  onNotify: (msg: string, type?: "ok" | "err") => void;
}

export function ShortsTab({ activeJob, refreshKey = 0, onStartJob, onNotify }: ShortsTabProps) {
  const [clips, setClips] = useState<RenderedClip[]>([]);
  const [sources, setSources] = useState<string[]>(["Todos"]);
  const [sourceFilter, setSourceFilter] = useState("Todos");
  const [durFilter, setDurFilter] = useState("Todos");
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  const [activeClip, setActiveClip] = useState<RenderedClip | null>(null);
  const [visibility, setVisibility] = useState<"PUBLIC" | "UNLISTED" | "PRIVATE" | "SCHEDULED">("PUBLIC");
  const [scheduleStart, setScheduleStart] = useState(() => {
    const d = new Date(Date.now() + 60 * 60 * 1000);
    d.setMinutes(0, 0, 0);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
  });
  const [scheduleIntervalHours, setScheduleIntervalHours] = useState(8);
  const [schedulePerSlot, setSchedulePerSlot] = useState(1);
  const [skipPosted, setSkipPosted] = useState(true);

  const [chromeReady, setChromeReady] = useState<boolean | null>(null);
  const [chromeMsg, setChromeMsg] = useState<string>("");
  const [syncing, setSyncing] = useState(false);
  const [loadingClips, setLoadingClips] = useState(false);

  // Inline metadata editor
  const [editingClip, setEditingClip] = useState<RenderedClip | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editVis, setEditVis] = useState<"PUBLIC" | "UNLISTED" | "PRIVATE">("PUBLIC");
  const [savingEdit, setSavingEdit] = useState(false);

  // Thumbnails
  const [showThumbs, setShowThumbs] = useState(false);
  const [thumbs, setThumbs] = useState<ThumbnailItem[]>([]);
  const [busyThumb, setBusyThumb] = useState(false);

  const loadClips = async (src = sourceFilter, dur = durFilter) => {
    setLoadingClips(true);
    try {
      const res = await api.listClips(src, dur);
      setClips(res.clips);
      setSources(res.sources);
      if (res.clips.length > 0 && !activeClip) {
        setActiveClip(res.clips[0]);
      } else if (activeClip) {
        const updated = res.clips.find((c) => c.output_path === activeClip.output_path);
        if (updated) setActiveClip(updated);
      }
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao carregar Shorts", "err");
    } finally {
      setLoadingClips(false);
    }
  };

  const loadThumbs = async () => {
    try {
      const res = await api.listThumbnails();
      setThumbs(res.thumbnails);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    void loadClips();
    void loadThumbs();
  }, [refreshKey]);

  useEffect(() => {
    if (activeJob?.kind === "upload" && activeJob.status === "done") {
      void loadClips();
    }
  }, [activeJob?.status, activeJob?.kind]);

  const handleFilterChange = (src: string, dur: string) => {
    setSourceFilter(src);
    setDurFilter(dur);
    void loadClips(src, dur);
  };

  const togglePath = (path: string) => {
    setSelectedPaths((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]
    );
  };

  const selectAll = () => setSelectedPaths(clips.map((c) => c.output_path));
  const selectPending = () =>
    setSelectedPaths(clips.filter((c) => c.youtube_status !== "posted").map((c) => c.output_path));
  const clearSelection = () => setSelectedPaths([]);

  const handleSyncApi = async () => {
    setSyncing(true);
    try {
      const res = await api.syncYouTube();
      onNotify(res.message);
      await loadClips();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao sincronizar", "err");
    } finally {
      setSyncing(false);
    }
  };

  const handleLaunchChrome = async () => {
    try {
      const res = await api.launchChrome();
      setChromeReady(res.ready);
      setChromeMsg(res.message);
      onNotify(res.message);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao abrir Chrome", "err");
    }
  };

  const handleCheckChrome = async () => {
    try {
      const res = await api.chromeStatus();
      setChromeReady(res.ready);
      setChromeMsg(res.message);
      onNotify(res.message, res.ready ? "ok" : "err");
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao verificar Chrome", "err");
    }
  };

  const handleRank = async () => {
    if (selectedPaths.length === 0) {
      onNotify("Selecione pelo menos 1 Short para rankear.", "err");
      return;
    }
    try {
      const { job_id } = await api.rankShorts(selectedPaths);
      onStartJob(job_id);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao iniciar ranking", "err");
    }
  };

  const handlePublish = async () => {
    if (selectedPaths.length === 0) {
      onNotify("Selecione pelo menos 1 Short para publicar.", "err");
      return;
    }
    try {
      const { job_id } = await api.uploadYouTube(
        selectedPaths,
        visibility,
        skipPosted,
        visibility === "SCHEDULED" ? scheduleStart : null,
        scheduleIntervalHours,
        schedulePerSlot
      );
      onStartJob(job_id);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao iniciar publicação", "err");
    }
  };

  const openEditor = (clip: RenderedClip) => {
    setEditingClip(clip);
    setEditTitle(clip.youtube_title || clip.title);
    setEditDesc(clip.youtube_description || "");
    setEditVis(clip.visibility || "PUBLIC");
  };

  const saveEditor = async () => {
    if (!editingClip) return;
    setSavingEdit(true);
    try {
      const res = await api.updateQueueItem({
        video_path: editingClip.output_path,
        youtube_title: editTitle,
        youtube_description: editDesc,
        visibility: editVis,
      });
      onNotify(res.message);
      setEditingClip(null);
      await loadClips();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao salvar metadados", "err");
    } finally {
      setSavingEdit(false);
    }
  };

  const handleGenThumbs = async () => {
    setBusyThumb(true);
    try {
      const res = await api.generateThumbnails(selectedPaths);
      onNotify(res.message);
      await loadThumbs();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao gerar capas", "err");
    } finally {
      setBusyThumb(false);
    }
  };

  const handleUploadThumbs = async () => {
    setBusyThumb(true);
    try {
      const res = await api.uploadThumbnails(selectedPaths);
      onNotify(res.message);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao enviar capas", "err");
    } finally {
      setBusyThumb(false);
    }
  };

  const isUploading = activeJob?.kind === "upload" && activeJob.status === "running";

  return (
    <div className="space-y-5">
      {/* Publish Toolbar */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4 shadow-xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <select
              value={sourceFilter}
              onChange={(e) => handleFilterChange(e.target.value, durFilter)}
              className="max-w-[260px] rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-sky-500"
            >
              {sources.map((s) => (
                <option key={s} value={s}>
                  {s === "Todos" ? "📁 Todos os Projetos" : s}
                </option>
              ))}
            </select>

            <select
              value={durFilter}
              onChange={(e) => handleFilterChange(sourceFilter, e.target.value)}
              className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-sky-500"
            >
              <option value="Todos">Todas Durações</option>
              <option value="30s">30s</option>
              <option value="60s">60s</option>
              <option value="90s">90s</option>
            </select>

            <button
              onClick={() => void loadClips()}
              className="rounded-xl border border-slate-700 bg-slate-950 p-2 text-slate-300 hover:text-white"
              title="Atualizar lista"
            >
              <RefreshCw className={`h-4 w-4 ${loadingClips ? "animate-spin" : ""}`} />
            </button>

            <button
              onClick={() => void api.openOutputFolder()}
              className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-300 hover:text-white"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              output/
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <select
              value={visibility}
              onChange={(e) => setVisibility(e.target.value as "PUBLIC" | "UNLISTED" | "PRIVATE" | "SCHEDULED")}
              className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100"
            >
              <option value="PUBLIC">Público</option>
              <option value="SCHEDULED">Programar (Agendar)</option>
              <option value="UNLISTED">Não listado</option>
              <option value="PRIVATE">Privado</option>
            </select>

            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-300">
              <input
                type="checkbox"
                checked={skipPosted}
                onChange={(e) => setSkipPosted(e.target.checked)}
                className="rounded border-slate-600 bg-slate-950 text-sky-500"
              />
              Pular postados
            </label>

            <button
              disabled={syncing}
              onClick={() => void handleSyncApi()}
              className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-medium text-slate-200 hover:border-sky-500/50 disabled:opacity-50"
            >
              {syncing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Sincronizar Canal
            </button>

            <button
              disabled={isUploading || selectedPaths.length === 0}
              onClick={() => void handleRank()}
              className="flex items-center gap-2 rounded-xl border border-amber-500/40 bg-amber-500/15 px-3.5 py-2 text-xs font-bold text-amber-300 transition hover:bg-amber-500/25 disabled:cursor-not-allowed disabled:opacity-50"
              title="Avaliar cada Short selecionado na Sala de Reunião (0 a 10) e ordenar do melhor para o pior"
            >
              {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trophy className="h-4 w-4" />}
              Rankear ({selectedPaths.length})
            </button>

            <button
              disabled={isUploading || selectedPaths.length === 0}
              onClick={() => void handlePublish()}
              className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 to-orange-500 px-4 py-2 text-xs font-bold text-white shadow-lg shadow-rose-500/20 transition hover:from-rose-400 hover:to-orange-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />}
              {visibility === "SCHEDULED" ? `Agendar (${selectedPaths.length})` : `Publicar (${selectedPaths.length})`}
            </button>
          </div>
        </div>

        {visibility === "SCHEDULED" && (
          <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-violet-500/30 bg-violet-500/10 px-3.5 py-2.5 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-medium text-violet-200">1º Lançamento:</span>
              <input
                type="datetime-local"
                value={scheduleStart}
                onChange={(e) => setScheduleStart(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-white"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-violet-200">Intervalo:</span>
              <select
                value={scheduleIntervalHours}
                onChange={(e) => setScheduleIntervalHours(Number(e.target.value))}
                className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-white"
              >
                <option value={4}>4h (6/dia)</option>
                <option value={6}>6h (4/dia)</option>
                <option value={8}>8h (3/dia — Ideal p/ Notificações)</option>
                <option value={12}>12h (2/dia)</option>
                <option value={24}>24h (1/dia)</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-violet-200">Por horário:</span>
              <select
                value={schedulePerSlot}
                onChange={(e) => setSchedulePerSlot(Number(e.target.value))}
                className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-white"
              >
                <option value={1}>1 Short (Recomendado)</option>
                <option value={2}>2 Shorts</option>
              </select>
            </div>
            <span className="ml-auto text-[11px] text-violet-300">
              {selectedPaths.length} vídeo(s) distribuídos a cada {scheduleIntervalHours}h
            </span>
          </div>
        )}

        {/* Chrome CDP & Quick Select */}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800/80 pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={selectPending}
              className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-amber-300 hover:border-amber-500/50"
            >
              ⏳ Selecionar Pendentes
            </button>
            <button
              onClick={selectAll}
              className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-300 hover:border-slate-600"
            >
              ☑️ Selecionar Todos ({clips.length})
            </button>
            <button
              onClick={clearSelection}
              className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200"
            >
              🧹 Limpar
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {chromeReady !== null && (
              <span
                className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
                  chromeReady
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-amber-500/15 text-amber-300"
                }`}
                title={chromeMsg}
              >
                {chromeReady ? "Chrome Studio Logado" : "Aguardando Login"}
              </span>
            )}
            <button
              onClick={() => void handleLaunchChrome()}
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-200 hover:border-sky-500/50"
            >
              <Chrome className="h-3.5 w-3.5 text-sky-400" />
              Abrir Chrome Studio
            </button>
            <button
              onClick={() => void handleCheckChrome()}
              className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-300 hover:text-white"
            >
              Verificar Sessão
            </button>
            <button
              onClick={() => setShowThumbs((v) => !v)}
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-indigo-300 hover:border-indigo-500/50"
            >
              <ImageIcon className="h-3.5 w-3.5" />
              Capas ({thumbs.length})
            </button>
          </div>
        </div>
      </div>

      {/* Live Upload Logs */}
      {activeJob && activeJob.kind === "upload" && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
          <div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-200">
            <span className="flex items-center gap-2">
              {activeJob.status === "running" && <Loader2 className="h-3.5 w-3.5 animate-spin text-rose-400" />}
              {activeJob.title}
            </span>
            <span className="font-mono text-sky-400">{activeJob.progress}%</span>
          </div>
          <div className="max-h-36 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950 p-3 font-mono text-xs text-slate-300">
            {activeJob.logs.slice(-30).map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        </div>
      )}

      {/* Thumbnails Drawer */}
      {showThumbs && (
        <div className="rounded-2xl border border-indigo-500/30 bg-slate-900/80 p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-white">Capas & Thumbnails com Hook (1080x1920)</h3>
              <p className="text-xs text-slate-400">
                Gera capas com o texto Hook por cima do cover/frame. Se nenhum corte estiver marcado, aplica a todos já postados.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                disabled={busyThumb}
                onClick={() => void handleGenThumbs()}
                className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-indigo-400 disabled:opacity-50"
              >
                {busyThumb ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImageIcon className="h-3.5 w-3.5" />}
                Gerar Capas
              </button>
              <button
                disabled={busyThumb}
                onClick={() => void handleUploadThumbs()}
                className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                <Upload className="h-3.5 w-3.5" />
                Atualizar no YouTube Studio
              </button>
            </div>
          </div>

          {thumbs.length === 0 ? (
            <p className="py-4 text-center text-xs text-slate-500">Nenhuma capa gerada em output/thumbnails/.</p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
              {thumbs.map((t) => (
                <div
                  key={t.path}
                  className="overflow-hidden rounded-xl border border-slate-800 bg-slate-950"
                >
                  <img
                    src={`${t.media_url}?v=1`}
                    alt={t.filename}
                    className="aspect-[9/16] w-full object-cover"
                  />
                  <div className="truncate px-2 py-1 text-[10px] text-slate-400">{t.filename}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Main Split: Clips List + Sticky 9:16 Player */}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
        <div className="space-y-2.5 xl:col-span-8">
          {clips.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-slate-800 py-16 text-center text-sm text-slate-400">
              Nenhum Short encontrado para os filtros selecionados.
            </div>
          ) : (
            clips.map((clip) => {
              const checked = selectedPaths.includes(clip.output_path);
              const isSelected = activeClip?.output_path === clip.output_path;
              const isPosted = clip.youtube_status === "posted";
              return (
                <div
                  key={clip.output_path}
                  onClick={() => setActiveClip(clip)}
                  className={`cursor-pointer rounded-xl border p-3.5 transition ${
                    isSelected
                      ? "border-sky-500/80 bg-slate-900 shadow-lg shadow-sky-500/5"
                      : "border-slate-800 bg-slate-900/60 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        togglePath(clip.output_path);
                      }}
                      className="mt-0.5 text-slate-400 hover:text-sky-400"
                    >
                      {checked ? (
                        <CheckSquare className="h-5 w-5 text-sky-400" />
                      ) : (
                        <Square className="h-5 w-5" />
                      )}
                    </button>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-semibold text-white">
                          {clip.youtube_title || clip.title}
                        </span>
                        <span
                          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                            isPosted
                              ? "bg-emerald-500/15 text-emerald-300"
                              : "bg-amber-500/15 text-amber-300"
                          }`}
                        >
                          {isPosted ? <CheckCircle2 className="h-3 w-3" /> : <Clock className="h-3 w-3" />}
                          {isPosted ? "Postado" : "Pendente"}
                        </span>
                        <span className="rounded-md bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-slate-300">
                          {clip.duration_type} • {clip.duration}s
                        </span>
                        {clip.viral_score !== undefined && clip.viral_score !== null && (
                          <span
                            title={
                              clip.ranking_details
                                ? `Jovem Viral: ${clip.ranking_details.jovem_viral_score} | Cineasta: ${clip.ranking_details.cineasta_score} | Comediante: ${clip.ranking_details.comediante_score}`
                                : "Nota Viral da Sala de Reunião"
                            }
                            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] font-bold ${
                              clip.viral_score >= 8
                                ? "bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40"
                                : clip.viral_score >= 6.5
                                ? "bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/40"
                                : "bg-rose-500/20 text-rose-300 ring-1 ring-rose-500/40"
                            }`}
                          >
                            <Trophy className="h-3 w-3" />
                            {clip.viral_score.toFixed(1)}/10
                          </span>
                        )}
                      </div>

                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
                        <span className="truncate">{clip.filename}</span>
                        <span>•</span>
                        <span>{clip.size_mb.toFixed(1)} MB</span>
                        <span>•</span>
                        <span>{clip.layout_mode}</span>
                      </div>

                      {clip.youtube_description && (
                        <p className="mt-1.5 line-clamp-1 text-xs text-slate-400">
                          {clip.youtube_description}
                        </p>
                      )}
                    </div>

                    <div className="flex shrink-0 items-center gap-1.5">
                      {clip.youtube_url && (
                        <a
                          href={clip.youtube_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="rounded-lg border border-slate-700 bg-slate-950 p-1.5 text-sky-400 hover:border-sky-500"
                          title="Abrir no YouTube"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          openEditor(clip);
                        }}
                        className="rounded-lg border border-slate-700 bg-slate-950 p-1.5 text-slate-300 hover:border-sky-500 hover:text-white"
                        title="Editar título e descrição"
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Sticky Vertical Player */}
        <div className="xl:col-span-4">
          <div className="sticky top-5 rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="truncate text-sm font-semibold text-white">
                {activeClip ? activeClip.title : "Player 9:16"}
              </h3>
              {activeClip && (
                <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-sky-300">
                  {activeClip.encoder}
                </span>
              )}
            </div>

            <div className="flex aspect-[9/16] max-h-[520px] w-full items-center justify-center overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
              {activeClip ? (
                <video
                  key={activeClip.media_url}
                  src={activeClip.media_url}
                  controls
                  className="h-full w-full object-contain"
                />
              ) : (
                <span className="text-xs text-slate-500">Selecione um Short para assistir</span>
              )}
            </div>

            {activeClip && (
              <div className="mt-3 space-y-1.5 text-xs text-slate-400">
                <div>
                  <span className="text-slate-500">Hook:</span>{" "}
                  <span className="font-semibold text-amber-300">{activeClip.hook_text || "—"}</span>
                </div>
                <div>
                  <span className="text-slate-500">Origem:</span> {activeClip.source_video}
                </div>
                {activeClip.context_reason && (
                  <p className="text-[11px] leading-relaxed text-slate-400">
                    {activeClip.context_reason}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Inline Metadata Edit Modal */}
      {editingClip && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-base font-semibold text-white">Editar Metadados YouTube</h3>
              <button
                onClick={() => setEditingClip(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs text-slate-400">Título YouTube Shorts</label>
                <input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-sky-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">Descrição & Hashtags</label>
                <textarea
                  rows={4}
                  value={editDesc}
                  onChange={(e) => setEditDesc(e.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-sky-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-slate-400">Visibilidade</label>
                <select
                  value={editVis}
                  onChange={(e) => setEditVis(e.target.value as "PUBLIC" | "UNLISTED" | "PRIVATE")}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white"
                >
                  <option value="PUBLIC">Público</option>
                  <option value="UNLISTED">Não listado</option>
                  <option value="PRIVATE">Privado</option>
                </select>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setEditingClip(null)}
                className="rounded-xl border border-slate-700 px-4 py-2 text-xs text-slate-300 hover:text-white"
              >
                Cancelar
              </button>
              <button
                disabled={savingEdit}
                onClick={() => void saveEditor()}
                className="flex items-center gap-1.5 rounded-xl bg-sky-600 px-4 py-2 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
              >
                <Save className="h-3.5 w-3.5" />
                Salvar Alterações
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
