import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Cpu,
  Film,
  KeyRound,
  Loader2,
  Play,
  Save,
  Sparkles,
  Trash2,
  Upload,
  Wrench,
  XCircle,
} from "lucide-react";
import { api } from "../api";
import type { DiagnosticsInfo, InputVideo } from "../types";

interface SystemTabProps {
  videos: InputVideo[];
  onRefreshVideos: () => Promise<void>;
  onNotify: (msg: string, type?: "ok" | "err") => void;
}

export function SystemTab({ videos, onRefreshVideos, onNotify }: SystemTabProps) {
  const [diag, setDiag] = useState<DiagnosticsInfo | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [channelRef, setChannelRef] = useState("");
  const [maskedKey, setMaskedKey] = useState("");
  const [uploading, setUploading] = useState(false);
  const [generatingDemo, setGeneratingDemo] = useState(false);
  const [demoLang, setDemoLang] = useState("pt");
  const [demoDur, setDemoDur] = useState(36);
  const [previewVideo, setPreviewVideo] = useState<InputVideo | null>(null);

  useEffect(() => {
    void api.diagnostics().then(setDiag).catch(() => {});
    void api
      .getAnalytics()
      .then((res) => {
        setMaskedKey(res.api_key_masked);
        setChannelRef(res.channel_ref);
      })
      .catch(() => {});
  }, []);

  const handleUpload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const res = await api.uploadVideo(file);
      onNotify(res.message);
      await onRefreshVideos();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro no upload", "err");
    } finally {
      setUploading(false);
    }
  };

  const handleDemo = async () => {
    setGeneratingDemo(true);
    try {
      const res = await api.generateDemo(demoLang, demoDur);
      onNotify(res.message);
      await onRefreshVideos();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao gerar demo", "err");
    } finally {
      setGeneratingDemo(false);
    }
  };

  const handleDelete = async (filename: string) => {
    try {
      const res = await api.deleteVideo(filename);
      onNotify(res.message);
      if (previewVideo?.filename === filename) setPreviewVideo(null);
      await onRefreshVideos();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao remover vídeo", "err");
    }
  };

  const handleSaveConfig = async () => {
    try {
      const res = await api.saveAnalyticsConfig(apiKey, channelRef);
      onNotify(res.message);
      setApiKey("");
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao salvar .env", "err");
    }
  };

  return (
    <div className="space-y-5">
      {/* Input Video Bank */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold text-white">
              <Film className="h-4 w-4 text-sky-400" />
              Banco de Vídeos (input/)
            </h2>
            <p className="text-xs text-slate-400">
              Envie gameplays 16:9 ou gere um vídeo demo sintético para testar o pipeline.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label className="flex cursor-pointer items-center gap-1.5 rounded-xl bg-sky-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-sky-500">
              {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              {uploading ? "Enviando..." : "Enviar Vídeo"}
              <input
                type="file"
                accept=".mp4,.mkv,.mov,.avi,.webm"
                className="hidden"
                onChange={(e) => void handleUpload(e.target.files?.[0])}
              />
            </label>

            <div className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-2.5 py-1">
              <select
                value={demoLang}
                onChange={(e) => setDemoLang(e.target.value)}
                className="bg-transparent text-xs text-slate-200 outline-none"
              >
                <option value="pt">PT-BR</option>
                <option value="en">EN</option>
              </select>
              <input
                type="number"
                min={20}
                max={95}
                value={demoDur}
                onChange={(e) => setDemoDur(Number(e.target.value))}
                className="w-12 bg-transparent text-center font-mono text-xs text-slate-200 outline-none"
              />
              <button
                disabled={generatingDemo}
                onClick={() => void handleDemo()}
                className="flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {generatingDemo ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                Demo
              </button>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-800 bg-slate-950/70 text-slate-400">
              <tr>
                <th className="px-4 py-2.5 font-medium">Arquivo</th>
                <th className="px-3 py-2.5 font-medium">Resolução</th>
                <th className="px-3 py-2.5 font-medium">Duração</th>
                <th className="px-3 py-2.5 font-medium">FPS</th>
                <th className="px-3 py-2.5 font-medium">Tamanho</th>
                <th className="px-3 py-2.5 font-medium">Cache</th>
                <th className="px-3 py-2.5 text-right font-medium">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70 text-slate-200">
              {videos.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                    Nenhum vídeo em input/.
                  </td>
                </tr>
              ) : (
                videos.map((v) => (
                  <tr key={v.filename} className="hover:bg-slate-800/30">
                    <td className="px-4 py-2.5 font-medium text-white">{v.filename}</td>
                    <td className="px-3 py-2.5 font-mono text-slate-400">
                      {v.width}x{v.height}
                    </td>
                    <td className="px-3 py-2.5 font-mono">{v.duration}s</td>
                    <td className="px-3 py-2.5 font-mono">{v.fps}</td>
                    <td className="px-3 py-2.5">{v.size_mb} MB</td>
                    <td className="px-3 py-2.5">
                      {v.cached ? (
                        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-300">
                          Em Cache
                        </span>
                      ) : (
                        <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[11px] text-slate-400">
                          Pendente
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <div className="inline-flex items-center gap-1.5">
                        <button
                          onClick={() => setPreviewVideo(previewVideo?.filename === v.filename ? null : v)}
                          className="rounded-lg border border-slate-700 bg-slate-950 p-1.5 text-sky-400 hover:border-sky-500"
                          title="Assistir 16:9"
                        >
                          <Play className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => void handleDelete(v.filename)}
                          className="rounded-lg border border-slate-700 bg-slate-950 p-1.5 text-slate-400 hover:border-rose-500 hover:text-rose-400"
                          title="Remover vídeo"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {previewVideo && (
          <div className="mt-4 overflow-hidden rounded-xl border border-slate-800 bg-slate-950 p-3">
            <div className="mb-2 flex items-center justify-between text-xs text-slate-300">
              <span>Preview Original 16:9: {previewVideo.filename}</span>
              <button onClick={() => setPreviewVideo(null)} className="text-slate-400 hover:text-white">
                Fechar
              </button>
            </div>
            <video src={previewVideo.media_url} controls className="max-h-80 w-full rounded-lg" />
          </div>
        )}
      </div>

      {/* YouTube API Config + Remotion */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <KeyRound className="h-4 w-4 text-amber-400" />
            Credenciais YouTube Data API (.env)
          </h3>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs text-slate-400">
                YouTube Data API v3 Key {maskedKey ? `(Atual: ${maskedKey})` : ""}
              </label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="AIzaSy... (deixe em branco para manter a atual)"
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-slate-400">Canal (@handle, UC... ou URL)</label>
              <input
                value={channelRef}
                onChange={(e) => setChannelRef(e.target.value)}
                placeholder="@hardcleeps"
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-white outline-none focus:border-sky-500"
              />
            </div>
            <button
              onClick={() => void handleSaveConfig()}
              className="flex items-center gap-1.5 rounded-xl bg-sky-600 px-4 py-2 text-xs font-semibold text-white hover:bg-sky-500"
            >
              <Save className="h-3.5 w-3.5" />
              Salvar no .env
            </button>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <Wrench className="h-4 w-4 text-indigo-400" />
            Remotion Studio & Diagnóstico
          </h3>
          {diag && (
            <div className="mb-4 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-2.5">
                <div className="text-slate-400">Encoder H.264</div>
                <div className="font-mono font-semibold text-sky-400">{diag.best_h264_encoder}</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-2.5">
                <div className="text-slate-400">Whisper Device</div>
                <div className="font-mono font-semibold text-emerald-400">{diag.whisper_device}</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-2.5">
                <div className="text-slate-400">MediaPipe</div>
                <div className="font-mono text-slate-200">{diag.mediapipe_version}</div>
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-950 p-2.5">
                <div className="text-slate-400">libass (subtitles)</div>
                <div className="font-mono text-slate-200">
                  {diag.has_subtitles_filter ? "Disponível" : "Ausente"}
                </div>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              onClick={() =>
                void api
                  .exportRemotionProps()
                  .then((r) => onNotify(r.message))
                  .catch((e) => onNotify(e.message, "err"))
              }
              className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 hover:border-sky-500/50"
            >
              📦 Exportar 1º Corte → Remotion
            </button>
            <button
              onClick={() =>
                void api
                  .launchRemotionStudio()
                  .then((r) => onNotify(r.message))
                  .catch((e) => onNotify(e.message, "err"))
              }
              className="rounded-xl bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500"
            >
              🚀 Abrir Remotion Studio
            </button>
          </div>
        </div>
      </div>

      {/* Repos Table */}
      {diag && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <Cpu className="h-4 w-4 text-sky-400" />
            Ecossistema Local Integrado
          </h3>
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {diag.repos.map((r) => (
              <div
                key={r.folder}
                className="flex items-start gap-2.5 rounded-xl border border-slate-800 bg-slate-950/70 p-3"
              >
                {r.installed ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
                )}
                <div>
                  <div className="text-xs font-semibold text-white">{r.name}</div>
                  <div className="text-[11px] text-slate-400">{r.role}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
