import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  Bot,
  Clapperboard,
  Cpu,
  Film,
  Loader2,
  Rocket,
  Settings,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { api, subscribeToJob } from "./api";
import { AnalyticsTab } from "./components/AnalyticsTab";
import { ShortsTab } from "./components/ShortsTab";
import { StudioTab } from "./components/StudioTab";
import { SystemTab } from "./components/SystemTab";
import type {
  CutItem,
  HealthInfo,
  InputVideo,
  JobState,
  PresetOption,
  TranscriptMeta,
} from "./types";

type TabId = "studio" | "shorts" | "analytics" | "system";

export function App() {
  const [tab, setTab] = useState<TabId>("studio");
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [videos, setVideos] = useState<InputVideo[]>([]);
  const [cuts, setCuts] = useState<CutItem[]>([]);
  const [transcript, setTranscript] = useState<TranscriptMeta | null>(null);
  const [captionPresets, setCaptionPresets] = useState<PresetOption[]>([]);
  const [layouts, setLayouts] = useState<PresetOption[]>([]);
  const [activeJob, setActiveJob] = useState<JobState | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "ok" | "err" } | null>(null);
  const [showClearModal, setShowClearModal] = useState(false);
  const [clearInputCaches, setClearInputCaches] = useState(false);
  const [clearingRecords, setClearingRecords] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);

  const unsubRef = useRef<(() => void) | null>(null);

  const notify = useCallback((msg: string, type: "ok" | "err" = "ok") => {
    setToast({ msg, type });
    setTimeout(() => {
      setToast((cur) => (cur?.msg === msg ? null : cur));
    }, 4500);
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      const [h, v, p, pr] = await Promise.all([
        api.health(),
        api.listVideos(),
        api.pipelineState(),
        api.presets(),
      ]);
      setHealth(h);
      setVideos(v.videos);
      setCuts(p.cuts);
      setTranscript(p.transcript);
      setCaptionPresets(pr.caption_presets);
      setLayouts(pr.layouts);
      if (p.current_job && !activeJob) {
        setActiveJob(p.current_job);
      }
    } catch {
      // backend starting up
    }
  }, [activeJob]);

  const attachJobStream = useCallback(
    (jobId: string, initialTitle = "Processando...") => {
      if (unsubRef.current) {
        unsubRef.current();
        unsubRef.current = null;
      }

      setActiveJob((prev) => ({
        job_id: jobId,
        kind: prev?.job_id === jobId ? prev.kind : tab === "shorts" ? "upload" : "pipeline",
        title: prev?.job_id === jobId ? prev.title : initialTitle,
        status: "running",
        step: "starting",
        progress: 0,
        logs: [],
        result: null,
        error: null,
        started_at: new Date().toISOString(),
        finished_at: null,
      }));

      void api.currentJob().then((res) => {
        if (res.job && res.job.job_id === jobId) {
          setActiveJob(res.job);
        }
      });

      unsubRef.current = subscribeToJob(jobId, {
        onLogs: (lines) => {
          setActiveJob((prev) =>
            prev
              ? { ...prev, logs: [...prev.logs, ...lines].slice(-400) }
              : prev
          );
        },
        onState: (st) => {
          setActiveJob((prev) => (prev ? { ...prev, ...st } : prev));
          if (st.status === "done") {
            notify("Tarefa concluída com sucesso!");
            void refreshAll();
          } else if (st.status === "error") {
            notify(st.error || "Erro na tarefa", "err");
            void refreshAll();
          }
        },
        onEnd: () => {
          void refreshAll();
        },
      });
    },
    [notify, refreshAll, tab]
  );

  useEffect(() => {
    void refreshAll().then(async () => {
      try {
        const res = await api.currentJob();
        if (res.job) {
          setActiveJob(res.job);
          if (res.job.status === "running") {
            attachJobStream(res.job.job_id, res.job.title);
          }
        }
      } catch {
        // ignore
      }
    });
    return () => {
      if (unsubRef.current) unsubRef.current();
    };
  }, []);

  const handleClearRecords = async () => {
    setClearingRecords(true);
    try {
      const res = await api.clearRecords(clearInputCaches);
      if (activeJob?.status !== "running") {
        setActiveJob(null);
      }
      setShowClearModal(false);
      setClearInputCaches(false);
      setRefreshTick((t) => t + 1);
      await refreshAll();
      notify(res.message);
    } catch (err) {
      notify(err instanceof Error ? err.message : "Erro ao limpar registros", "err");
    } finally {
      setClearingRecords(false);
    }
  };

  const navItems: Array<{ id: TabId; label: string; icon: typeof Zap }> = [
    { id: "studio", label: "Estúdio & Pipeline", icon: Zap },
    { id: "shorts", label: "Shorts & Publicar", icon: Rocket },
    { id: "analytics", label: "Analytics & Coach IA", icon: BarChart3 },
    { id: "system", label: "Sistema & Mídia", icon: Settings },
  ];

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      {/* Sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-800/80 bg-slate-950/90 p-4 md:flex">
        <div className="mb-6 flex items-center gap-3 px-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-indigo-600 shadow-lg shadow-sky-500/20">
            <Clapperboard className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="text-sm font-bold tracking-tight text-white">Hard Cleeps</div>
            <div className="text-[11px] font-medium text-sky-400">Studio 9:16 Standalone</div>
          </div>
        </div>

        <nav className="flex-1 space-y-1.5">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = tab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setTab(item.id)}
                className={`flex w-full items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition ${
                  active
                    ? "bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/30"
                    : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {item.label}
              </button>
            );
          })}

          <div className="pt-2">
            <button
              disabled={activeJob?.status === "running"}
              onClick={() => setShowClearModal(true)}
              className="flex w-full items-center gap-3 rounded-xl border border-rose-500/20 bg-rose-500/5 px-3.5 py-2.5 text-sm font-medium text-rose-300 transition hover:border-rose-500/40 hover:bg-rose-500/15 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Trash2 className="h-4 w-4 shrink-0" />
              Limpar Registros
            </button>
          </div>
        </nav>

        {/* Bottom Status Card */}
        <div className="mt-4 space-y-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs">
          <div className="flex items-center justify-between text-slate-400">
            <span className="flex items-center gap-1.5">
              <Cpu className="h-3.5 w-3.5 text-sky-400" />
              Encoder
            </span>
            <span className="font-mono text-slate-200">{health?.encoder ?? "..."}</span>
          </div>
          <div className="flex items-center justify-between text-slate-400">
            <span className="flex items-center gap-1.5">
              <Bot className="h-3.5 w-3.5 text-indigo-400" />
              Pool IA
            </span>
            <span className={health?.pool_active ? "text-emerald-400" : "text-slate-500"}>
              {health?.pool_active ? "Ativa" : "Offline"}
            </span>
          </div>
          <div className="flex items-center justify-between text-slate-400">
            <span className="flex items-center gap-1.5">
              <Film className="h-3.5 w-3.5 text-amber-400" />
              Shorts Prontos
            </span>
            <span className="font-semibold text-white">{health?.clips_count ?? 0}</span>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top Mobile/Header Bar */}
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 bg-slate-950/80 px-5 py-3 backdrop-blur">
          <div className="flex items-center gap-2 md:hidden">
            {navItems.map((item) => (
              <button
                key={item.id}
                onClick={() => setTab(item.id)}
                className={`rounded-lg px-2.5 py-1.5 text-xs font-medium ${
                  tab === item.id ? "bg-sky-500/20 text-sky-300" : "text-slate-400"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="hidden text-sm font-semibold text-slate-200 md:block">
            {navItems.find((n) => n.id === tab)?.label}
          </div>

          <div className="flex items-center gap-3">
            {activeJob?.status === "running" && (
              <div className="flex items-center gap-2 rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-xs text-sky-300">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span className="max-w-[200px] truncate">{activeJob.title}</span>
                <span className="font-mono font-bold">{activeJob.progress}%</span>
              </div>
            )}
          </div>
        </header>

        <main className="flex-1 p-5">
          <div className="mx-auto max-w-[1440px]">
            {tab === "studio" && (
              <StudioTab
                videos={videos}
                cuts={cuts}
                transcript={transcript}
                captionPresets={captionPresets}
                layouts={layouts}
                activeJob={activeJob}
                onRefresh={refreshAll}
                onStartJob={(id) => attachJobStream(id, "Pipeline 9:16")}
                onNotify={notify}
              />
            )}
            {tab === "shorts" && (
              <ShortsTab
                activeJob={activeJob}
                refreshKey={refreshTick}
                onStartJob={(id) => attachJobStream(id, "Upload YouTube Shorts")}
                onNotify={notify}
              />
            )}
            {tab === "analytics" && <AnalyticsTab onNotify={notify} />}
            {tab === "system" && (
              <SystemTab videos={videos} onRefreshVideos={refreshAll} onNotify={notify} />
            )}
          </div>
        </main>
      </div>

      {/* Clear Records Confirmation Modal */}
      {showClearModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-base font-semibold text-white">
                <AlertTriangle className="h-5 w-5 text-amber-400" />
                Limpar Registros e Outputs
              </div>
              <button
                onClick={() => setShowClearModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs leading-relaxed text-slate-300">
              <p>
                Prepara o estúdio para um novo ciclo baseado nos vídeos atuais da pasta{" "}
                <code className="text-sky-400">input/</code> ({videos.length} vídeo(s) detectado(s)):
              </p>
              <ul className="list-disc space-y-1 pl-4 text-slate-400">
                <li>Remove cortes e thumbnails antigos em <code className="text-slate-300">output/</code>.</li>
                <li>Zera <code className="text-slate-300">projects_index.json</code>, <code className="text-slate-300">youtube_posts_queue.json</code>, <code className="text-slate-300">cuts.json</code> e <code className="text-slate-300">transcript.json</code>.</li>
                <li>Remove caches de projetos que não estão mais em <code className="text-slate-300">input/</code>.</li>
                <li>Preserva modelos Whisper, login do YouTube Studio, analytics e histórico de uploads.</li>
              </ul>

              <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-slate-800 bg-slate-950/70 p-2.5 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={clearInputCaches}
                  onChange={(e) => setClearInputCaches(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-900 text-rose-500"
                />
                Também limpar cache dos vídeos ainda presentes em input/
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setShowClearModal(false)}
                className="rounded-xl border border-slate-700 px-4 py-2 text-xs text-slate-300 hover:text-white"
              >
                Cancelar
              </button>
              <button
                disabled={clearingRecords}
                onClick={() => void handleClearRecords()}
                className="flex items-center gap-1.5 rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
              >
                {clearingRecords ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
                Limpar Agora
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div
          className={`fixed right-5 bottom-5 z-50 max-w-md rounded-xl border px-4 py-3 text-xs font-medium shadow-2xl ${
            toast.type === "err"
              ? "border-rose-500/40 bg-rose-950/95 text-rose-200"
              : "border-emerald-500/40 bg-slate-900/95 text-emerald-200"
          }`}
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}

export default App;
