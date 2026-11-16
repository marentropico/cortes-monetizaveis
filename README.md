# Hard Cleeps Studio — Shorts 9:16

Plataforma **standalone** (Desktop App local via **FastAPI + React/Vite**) para transformar vídeos longos de gameplay (`16:9`) em **YouTube Shorts / Reels verticais (`1080x1920`)**, com transcrição por palavra, análise contextual bilíngue (**PT-BR / EN**), detecção automática de facecam, legendas dinâmicas `.ass`, geração de capas com hook, publicação em lote no YouTube Studio e painel de Analytics com Coach IA.

---

## Principais Recursos

- **Interface Standalone (Sem abas de navegador):** abre em janela desktop dedicada via `launcher.py` (Edge/Chrome `--app` com perfil isolado).
- **Pipeline 1-Click com Progresso em Tempo Real (SSE):**
  1. **Transcrição** local com `faster-whisper` (word-level timestamps + cache por vídeo).
  2. **Análise Contextual** (`TextTiling` + heurística PT/EN ou curadoria opcional via **Pool de LLMs** em `.env`) para cortes de **30s / 60s / 90s** ou **Mix Inteligente**.
  3. **Detecção de Facecam & Enquadramento 9:16** (MediaPipe/OpenCV com modo 3-Zonas, Split-Screen ou layouts customizados).
  4. **Legendas Dinâmicas `.ass`** (presets estilo Hormozi, etc.) queimadas via FFmpeg com aceleração de hardware (`h264_amf`, `h264_nvenc`, `h264_qsv` ou `libx264`).
- **Editor Visual de Cortes:** ajuste título, início, fim e `hook_text` diretamente na interface (ou via JSON bruto em `temp/cuts.json`).
- **Shorts & Publicação em Lote:** player vertical `9:16`, edição inline de título/descrição/visibilidade, sincronização com a YouTube Data API v3 e upload automático via Chrome CDP (`playwright`).
- **Capas & Thumbnails com Hook:** gera capas `1080x1920` estilizadas e atualiza no YouTube Studio em lote.
- **Analytics & Coach IA:** métricas do canal por faixa de duração (`30s`, `60s`, `90s`, `Longo`) e recomendações geradas pelo Pool IA.
- **Limpar Registros:** botão na barra lateral que limpa `output/`, filas e caches obsoletos levando em conta os vídeos atuais de `input/`, preservando modelos Whisper, sessão do Chrome e histórico.

---

## Estrutura do Projeto

```text
Cortes Monetizaveis/
├── backend/
│   └── server.py              # API FastAPI + SSE (jobs em tempo real) + streaming de mídia
├── frontend/                  # Interface React + TypeScript + Tailwind CSS (Vite)
│   └── src/components/        # StudioTab, ShortsTab, AnalyticsTab, SystemTab
├── src/
│   ├── ffmpeg_utils.py        # Auto-descoberta do FFmpeg + seleção de encoder H.264
│   ├── transcriber.py         # faster-whisper com timestamps por palavra e cache
│   ├── context_analyzer.py    # Segmentação contextual (local + Pool LLM opcional)
│   ├── face_detector.py       # Detecção de facecam e preview 9:16
│   ├── captioner.py           # Gerador de legendas dinâmicas .ass
│   ├── video_editor.py        # Compositor FFmpeg 1080x1920 e catálogo projects_index.json
│   ├── thumbnail_generator.py # Capas 1080x1920 com Hook + upload no YouTube Studio
│   ├── youtube_publisher.py   # Fila de postagem + automação Chrome CDP
│   ├── youtube_analytics.py   # Coleta via YouTube Data API v3 / Studio CDP + Coach IA
│   ├── llm_pool.py            # Pool de chaves Gemini/OpenRouter com round-robin e fallback
│   └── demo_generator.py      # Gerador de vídeo demo sintético para testes
├── remotion/                  # Projeto Remotion Studio integrado (templates React 9:16)
├── input/                     # Vídeos brutos 16:9 de entrada
├── output/                    # Shorts renderizados, thumbnails e índices JSON
├── temp/                      # Transcrições, cortes, legendas .ass e caches locais
├── launcher.py                # Launcher standalone (FastAPI + janela desktop)
├── package.json               # Scripts npm (start, dev, build, legacy)
├── run.bat / run.ps1          # Inicialização rápida no Windows
├── app.py                     # Interface legada em Gradio (fallback)
├── requirements.txt           # Dependências Python
└── .env.example               # Modelo de variáveis de ambiente
```

---

## Pré-requisitos

- **Python 3.12+**
- **Node.js 20+** e **npm**
- **FFmpeg / FFprobe** instalados no sistema (ou no `PATH`)
- **Microsoft Edge** ou **Google Chrome** (usado tanto para a janela standalone quanto para automação CDP do YouTube Studio)

---

## Instalação

### 1. Ambiente Python
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
```

### 2. Frontend React
```powershell
npm --prefix frontend install
npm run build
```

### 3. Variáveis de Ambiente (`.env`)
Copie `.env.example` para `.env` e preencha apenas o que for utilizar (todas as chaves são opcionais — o pipeline local funciona 100% sem LLMs externas):

```powershell
Copy-Item .env.example .env
```

Campos disponíveis em `.env`:
- `ARANDU_GEMINI_KEY_1`, `ARANDU_GEMINI_KEY_2`, `ARANDU_MODEL`, `ARANDU_MODEL_FALLBACK`: Pool de chaves Gemini para curadoria de cortes, títulos e Coach IA.
- `ARANDU_OPENROUTER_KEY`, `ARANDU_OPENROUTER_FREE_MODEL`: Fallback OpenRouter.
- `YOUTUBE_API_KEY`, `YOUTUBE_CHANNEL_REF`: YouTube Data API v3 para sincronização e Analytics do canal.

---

## Como Executar

### Modo Standalone (Produção — Recomendado)
Inicia o backend FastAPI servindo o frontend compilado e abre a janela desktop dedicada:

- **Duplo clique** em `run.bat`
- Ou via PowerShell: `.\run.ps1`
- Ou via npm: `npm start`

### Modo Desenvolvimento (Vite HMR + FastAPI)
Para editar o frontend com hot-reload automático:
```powershell
npm run dev
```

### Modo Legado (Gradio)
```powershell
npm run legacy
```

---

## Guia de Uso do Fluxo Completo

1. **Adicionar Vídeo (`Sistema & Mídia` ou pasta `input/`):**
   Coloque seus vídeos `16:9` (`.mp4`, `.mkv`, `.mov`, `.avi`, `.webm`) na pasta `input/` ou envie pela aba **Sistema & Mídia** (também é possível gerar um vídeo demo para testes).
2. **Gerar Cortes (`Estúdio & Pipeline`):**
   Selecione o vídeo, escolha o range (**Mix**, **30s**, **60s** ou **90s**) e clique em **Gerar Cortes 1-Click**. Acompanhe o progresso por etapas, edite os cortes visualmente se quiser e confira no **Preview 9:16**.
3. **Revisar & Publicar (`Shorts & Publicar`):**
   - Clique em **Abrir Chrome Studio** na primeira vez para fazer login na sua conta Google/YouTube (a sessão fica salva em `temp/youtube_chrome_profile/`).
   - Edite título, descrição e visibilidade diretamente em cada card.
   - Marque os Shorts desejados (ou use **Selecionar Pendentes**) e clique em **Publicar**.
   - Use o painel **Capas** para gerar e enviar thumbnails com Hook.
4. **Acompanhar Resultados (`Analytics & Coach IA`):**
   Atualize as métricas pela **API v3** ou **Studio CDP**, compare o desempenho por faixa (`30s`, `60s`, `90s`) e gere sugestões com o **Coach IA**.
5. **Iniciar Novo Ciclo (`Limpar Registros`):**
   Após concluir os uploads e remover os vídeos antigos de `input/`, clique em **Limpar Registros** na barra lateral para zerar `output/`, filas e caches antigos com segurança.

---

## Execução Modular via CLI

Os módulos principais também podem ser executados diretamente via terminal:

```powershell
# 1. Transcrever vídeo
.\.venv\Scripts\python.exe -m src.transcriber input\gameplay.mp4 --language pt --model base

# 2. Analisar contexto (30s, 60s, 90s ou mix)
.\.venv\Scripts\python.exe -m src.context_analyzer --duration mix --max-cuts 6

# 3. Renderizar Shorts verticais (1080x1920)
.\.venv\Scripts\python.exe -m src.video_editor input\gameplay.mp4 --layout auto --preset hormozi
```
