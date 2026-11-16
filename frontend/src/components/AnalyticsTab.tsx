import { useEffect, useState } from "react";
import {
  BarChart3,
  Brain,
  ExternalLink,
  Eye,
  Loader2,
  Monitor,
  Radio,
  Users,
  Video,
} from "lucide-react";
import { api } from "../api";
import type { AnalyticsPayload } from "../types";

interface AnalyticsTabProps {
  onNotify: (msg: string, type?: "ok" | "err") => void;
}

export function AnalyticsTab({ onNotify }: AnalyticsTabProps) {
  const [payload, setPayload] = useState<AnalyticsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [coachText, setCoachText] = useState<string>("");
  const [busyCoach, setBusyCoach] = useState(false);

  const load = async () => {
    try {
      const res = await api.getAnalytics();
      setPayload(res);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao carregar analytics", "err");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const handleFetchApi = async () => {
    setLoading(true);
    try {
      const res = await api.fetchAnalyticsApi("", "");
      setPayload(res);
      if (res.message) onNotify(res.message);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro na YouTube Data API", "err");
    } finally {
      setLoading(false);
    }
  };

  const handleScrapeStudio = async () => {
    setLoading(true);
    try {
      const res = await api.scrapeStudioAnalytics();
      setPayload(res);
      if (res.message) onNotify(res.message);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro ao ler Studio CDP", "err");
    } finally {
      setLoading(false);
    }
  };

  const handleAiCoach = async () => {
    setBusyCoach(true);
    try {
      const res = await api.runAiCoach();
      setCoachText(res.advice);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : "Erro no Coach IA", "err");
    } finally {
      setBusyCoach(false);
    }
  };

  const data = payload?.data;
  const ch = data?.channel;
  const buckets = data?.bucket_summary ?? {};
  const videos = data?.videos ?? [];

  return (
    <div className="space-y-5">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
        <div>
          <h2 className="text-base font-semibold text-white">
            {ch?.title ? `📺 ${ch.title}` : "Analytics do Canal"}
          </h2>
          <p className="text-xs text-slate-400">
            {data
              ? `Última coleta: ${data.updated_at || data.fetched_at || "—"} • Fonte: ${data.source || "API v3"}`
              : "Conecte sua YouTube Data API v3 na aba Sistema ou use o Chrome Studio CDP."}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            disabled={loading}
            onClick={() => void handleFetchApi()}
            className="flex items-center gap-1.5 rounded-xl bg-sky-600 px-4 py-2 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Radio className="h-3.5 w-3.5" />}
            Atualizar Métricas (API v3)
          </button>
          <button
            disabled={loading}
            onClick={() => void handleScrapeStudio()}
            className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3.5 py-2 text-xs text-slate-200 hover:border-sky-500/50 disabled:opacity-50"
          >
            <Monitor className="h-3.5 w-3.5" />
            Ler Studio (CDP)
          </button>
          <button
            disabled={busyCoach}
            onClick={() => void handleAiCoach()}
            className="flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {busyCoach ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Brain className="h-3.5 w-3.5" />}
            Coach IA
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      {ch && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Inscritos</span>
              <Users className="h-4 w-4 text-sky-400" />
            </div>
            <div className="mt-2 text-2xl font-bold text-white">
              {(ch.subscribers ?? 0).toLocaleString("pt-BR")}
            </div>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Visualizações Totais</span>
              <Eye className="h-4 w-4 text-emerald-400" />
            </div>
            <div className="mt-2 text-2xl font-bold text-white">
              {(ch.total_views ?? 0).toLocaleString("pt-BR")}
            </div>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Vídeos no Canal</span>
              <Video className="h-4 w-4 text-indigo-400" />
            </div>
            <div className="mt-2 text-2xl font-bold text-white">
              {(ch.video_count ?? 0).toLocaleString("pt-BR")}
            </div>
          </div>
        </div>
      )}

      {/* Duration Buckets */}
      {Object.keys(buckets).length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
            <BarChart3 className="h-4 w-4 text-sky-400" />
            Desempenho por Faixa de Duração
          </h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {(["30s", "60s", "90s", "Longo"] as const).map((key) => {
              const b = buckets[key];
              if (!b) return null;
              return (
                <div
                  key={key}
                  className="rounded-xl border border-slate-800 bg-slate-950/70 p-3.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-sky-400">{key}</span>
                    <span className="text-xs text-slate-400">{b.count} vídeo(s)</span>
                  </div>
                  <div className="mt-2 text-lg font-semibold text-white">
                    {b.avg_views.toFixed(0)} <span className="text-xs font-normal text-slate-400">views/média</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
                    <span>{b.avg_likes.toFixed(1)} likes</span>
                    <span className="text-emerald-400">{b.avg_engagement_pct.toFixed(2)}% eng.</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* AI Coach Output */}
      {coachText && (
        <div className="rounded-2xl border border-indigo-500/30 bg-indigo-950/20 p-5">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-indigo-300">
            <Brain className="h-4 w-4" />
            Recomendações do Coach IA
          </h3>
          <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
            {coachText}
          </div>
        </div>
      )}

      {/* Videos Table */}
      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/70">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-800 bg-slate-950/70 text-slate-400">
              <tr>
                <th className="px-4 py-3 font-medium">Título</th>
                <th className="px-3 py-3 font-medium">Faixa</th>
                <th className="px-3 py-3 font-medium">Duração</th>
                <th className="px-3 py-3 font-medium">Views</th>
                <th className="px-3 py-3 font-medium">Likes</th>
                <th className="px-3 py-3 font-medium">Engaj.</th>
                <th className="px-3 py-3 font-medium">Link</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70 text-slate-200">
              {videos.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-slate-500">
                    Nenhum vídeo coletado ainda.
                  </td>
                </tr>
              ) : (
                videos.map((v, i) => (
                  <tr key={i} className="hover:bg-slate-800/40">
                    <td className="max-w-xs truncate px-4 py-2.5 font-medium text-white">
                      {v.title}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className="rounded bg-slate-800 px-2 py-0.5 text-[11px] text-sky-300">
                        {v.bucket}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 font-mono text-slate-400">{v.duration_sec}s</td>
                    <td className="px-3 py-2.5 font-semibold">{v.views.toLocaleString("pt-BR")}</td>
                    <td className="px-3 py-2.5">{v.likes}</td>
                    <td className="px-3 py-2.5 text-emerald-400">{v.engagement_pct}%</td>
                    <td className="px-3 py-2.5">
                      {v.url && (
                        <a
                          href={v.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex text-sky-400 hover:text-sky-300"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
