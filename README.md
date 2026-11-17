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
│   ├── youtube_downloader.py  # Descoberta do yt-dlp (YtoWave) e download direto para input/
│   ├── llm_pool.py            # Pool de chaves Gemini/OpenRouter com round-robin e fallback
│   └── demo_generator.py      # Gerador de vídeo demo sintético para testes
├── assets/                    # Marca do canal para overlay (logo.png e follow.png)
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

## Pré-requisitos e Repositórios Externos

Antes de instalar as dependências do projeto, garanta que os softwares e binários abaixo estejam disponíveis no sistema:

| Componente | Obrigatório | Endereço Oficial / Repositório | Instalação rápida (Windows `winget`) |
| :--- | :---: | :--- | :--- |
| **Python 3.12+** | Sim | [python.org/downloads](https://www.python.org/downloads/) | `winget install Python.Python.3.12` |
| **Node.js 20+ (npm)** | Sim | [nodejs.org](https://nodejs.org/) | `winget install OpenJS.NodeJS.LTS` |
| **FFmpeg / FFprobe** | Sim | [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) · [ffmpeg.org](https://ffmpeg.org/download.html) | `winget install Gyan.FFmpeg` |
| **yt-dlp** *(ou **YtoWave**)* | Recomendado *(YouTube + `.json3`)* | [github.com/yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp/releases) · [YtoWave](https://marentropico.github.io/ytowave/) | `winget install yt-dlp.yt-dlp` |
| **Google Chrome ou Edge** | Sim *(App + CDP)* | [google.com/chrome](https://www.google.com/chrome/) · [microsoft.com/edge](https://www.microsoft.com/edge) | Pré-instalado no Windows (Edge) |

> **Descoberta automática de binários:** O sistema procura `ffmpeg.exe`/`ffprobe.exe` no `PATH`, em `bin/`, `C:\ffmpeg\bin` e pacotes do WinGet (`Gyan.FFmpeg`). Para download do YouTube e legendas `.json3`, procura `yt-dlp.exe` no `PATH`, na pasta do **YtoWave** (`ytowave/bin/yt-dlp.exe`) ou via variáveis `YT_DLP_PATH` / `YTOWAVE_BIN_DIR`.

---

## Instalação

### 1. Clonar o repositório
```powershell
git clone <url-do-seu-repositorio>
cd "Cortes Monetizaveis"
```

### 2. Ambiente Python e Pacotes (`requirements.txt`)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

Principais pacotes Python instalados via [PyPI](https://pypi.org/) (`requirements.txt`):
- **Transcrição:** [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) `>=1.1.0` *(modelos `int8` são baixados automaticamente na 1ª execução para `temp/models/` via [HuggingFace Systran](https://huggingface.co/Systran))*
- **Visão / Facecam:** [`mediapipe`](https://github.com/google-ai-edge/mediapipe) `>=0.10.14`, `opencv-python>=4.9.0`, `Pillow>=10.0.0`
- **Vídeo / Áudio / NLP:** `ffmpeg-python>=0.2.0`, `moviepy>=2.0.0`, `numpy>=1.26.0`, `scipy>=1.12.0`, `nltk>=3.8.1`
- **Backend / UI:** `fastapi>=0.115.0`, `uvicorn>=0.30.0`, `python-multipart>=0.0.9`, `gradio>=5.0.0` *(legado)*
- **Automação Studio:** [`playwright`](https://playwright.dev/python/) `>=1.48.0` *(requer `playwright install chromium`)*

### 3. Frontend React (`frontend/`) e Remotion (`remotion/`, opcional)
```powershell
npm --prefix frontend install
npm run build
```

Caso utilize os templates React 9:16 em `remotion/`:
```powershell
npm --prefix remotion install
```

Principais pacotes Node.js via [npm](https://www.npmjs.com/):
- **Frontend (`frontend/package.json`):** `react@^19.0.0`, `react-dom@^19.0.0`, `lucide-react@^0.475.0`, `vite@^6.2.0`, `tailwindcss@^4.0.9`, `@tailwindcss/vite@^4.0.9`, `typescript@~5.7.2`
- **Remotion (`remotion/package.json`):** `remotion@4.0.537`, `@remotion/cli`, `@remotion/noise`, `@remotion/shapes`, `@remotion/transitions`

### 4. Variáveis de Ambiente e Chaves de API (`.env`)
Copie `.env.example` para `.env` e preencha apenas o que for utilizar (todas as chaves são opcionais — o pipeline local funciona 100% sem LLMs externas):

```powershell
Copy-Item .env.example .env
```

Onde obter as chaves opcionais:
- **Gemini API (`ARANDU_GEMINI_KEY_1`, `ARANDU_GEMINI_KEY_2`):** [Google AI Studio](https://aistudio.google.com/apikey) — pool de chaves para curadoria de cortes, títulos, revisão de legendas e Coach IA.
- **OpenRouter (`ARANDU_OPENROUTER_KEY`):** [openrouter.ai/keys](https://openrouter.ai/keys) — fallback com modelos gratuitos (`openrouter/free`).
- **YouTube Data API v3 (`YOUTUBE_API_KEY`, `YOUTUBE_CHANNEL_REF`):** [Google Cloud Console — YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) — sincronização e métricas de Analytics do canal.

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

## Personalização de Marca (`assets/logo.png` e `assets/follow.png`)

Qualquer usuário pode personalizar os cortes com a identidade do seu canal colocando dois arquivos **PNG com fundo transparente** na pasta `assets/`:

- `assets/logo.png`: exibido na **primeira metade** do corte, ao lado esquerdo do círculo da facecam (`pip_split`).
- `assets/follow.png` *(opcional)*: na **metade do vídeo**, substitui o logo com um leve **"pop" visual** (`0.28s`, sem áudio) convidando o público a se inscrever/seguir. Se `follow.png` não existir, apenas `logo.png` permanece visível durante todo o corte.

> **Ajuste automático de tamanho:** não importa a resolução ou proporção da sua imagem original (quadrada, horizontal ou vertical) — o renderizador redimensiona proporcionalmente para caber dentro da área segura máxima de **`460 x 250` px**, centralizada ao lado esquerdo do círculo da facecam, sem invadir a facecam, o Hook superior ou as legendas.

---

## Download Direto do YouTube (Integração YtoWave)

Na aba **Estúdio & Pipeline**, é possível colar um link do YouTube para baixar o vídeo em `.mp4` direto para `input/`. O sistema busca automaticamente o `yt-dlp.exe` no `PATH` ou na instalação local do **YtoWave** (`ytowave/bin/yt-dlp.exe`). Caso não encontre, a interface exibe um botão direto para a página de download do YtoWave.

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
