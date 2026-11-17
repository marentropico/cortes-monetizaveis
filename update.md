# Roadmap da Atualização — Hard Cleeps Studio

Este documento consolida todo o plano da próxima atualização do sistema, desenhado para ser implementado assim que a pipeline em andamento finalizar.

---

## 1. Identidade Visual, Logo Interna e Favicon
- **Logo SVG oficial:** utilizar [app_icon.svg](file:///w:/Desktop/Cortes%20Monetizaveis/assets/app_icon.svg) (botão de player partido em raio, roxo e laranja) e [app_icon_mini.svg](file:///w:/Desktop/Cortes%20Monetizaveis/assets/app_icon_mini.svg) como fonte visual única.
- **Barra lateral esquerda (`frontend/src/App.tsx`):** substituir o ícone atual ao lado do título **Hard Cleeps** pela nova logo SVG oficial.
- **Favicon do programa (`frontend/index.html` + `frontend/public/`):** adicionar `<link rel="icon" type="image/svg+xml" href="/favicon.svg" />` e fallback `.ico` para que a janela e abas exibam a nova marca.
- **Ícones do Windows (`assets/app_icon.ico` e `assets/app_icon_mini.png`):** aplicar no atalho, na barra de tarefas e nos ícones ocultos (System Tray).

---

## 2. Janela Standalone, Barra de Tarefas e Segundo Plano (`launcher.py`)
- **Janela nativa Windows (`pywebview` / WebView2 + `pystray`):**
  - Exibir `assets/app_icon.ico` diretamente na barra de tarefas enquanto a janela estiver aberta.
  - Manter `assets/app_icon_mini.png` nos **ícones ocultos (System Tray)** com menu rápido (*Abrir Hard Cleeps Studio*, *Status*, *Sair*).
- **Confirmação ao clicar em Fechar (`X`):**
  - Interceptar o evento de fechamento da janela e perguntar ao usuário:
    1. **Rodar em segundo plano:** oculta a janela da barra de tarefas (`window.hide()`), mantém o ícone mini na área de ícones ocultos e preserva 100% dos processos ativos (backend, pipelines, downloads e uploads).
    2. **Sair do programa:** encerra o servidor FastAPI e subprocessos de forma limpa (com aviso caso haja pipeline ativa).

---

## 3. Auto-Updater por Commits do GitHub
- **Motor (`src/updater.py`):**
  - Detecta automaticamente `origin` e a branch atual do `git`.
  - Checa `git fetch` + `git rev-list --count HEAD..origin/<branch>` + changelog (`git log`) e detecta se `requirements.txt` ou `frontend/` mudaram.
  - Persiste preferência em `temp/updater_config.json` (`auto_update: true/false`).
  - Modo **offline-safe**: nunca trava ou gera erro caso não haja internet.
- **Backend (`backend/server.py`):**
  - `GET /api/system/update-status`
  - `POST /api/system/update-config`
  - `POST /api/system/apply-update` com **trava obrigatória** (`jobs.is_running()` → retorna `409 Conflict` para jamais interromper uma pipeline ativa).
- **Script externo (`installer/update_and_restart.ps1`):**
  - Encerra o servidor atual, executa `git pull --ff-only`, atualiza `pip` / `npm run build` somente se necessário (preservando `.env`, `input/`, `output/`, `temp/`, `assets/`) e relança o `launcher.py`.
- **Interface React (`App.tsx` + `SystemTab.tsx`):**
  - Exibe versão + hash atual na sidebar e um aviso/badge quando houver commits disponíveis.
  - Card na aba **Sistema & Mídia** com changelog, botão **Verificar Agora**, botão **Atualizar e Reiniciar** e switch **Ativar Atualizações Automáticas**.

---

## 4. Instalador Wizard Windows (`Inno Setup`)
- **`installer/install.ps1`:** verifica/instala via `winget` (**Git**, **Python 3.12**, **Node.js LTS**, **FFmpeg** e **yt-dlp**), clona o repositório, cria `.venv`, instala dependências Python/Playwright e gera o build do frontend.
- **`installer/HardCleeps_Setup.iss` → `HardCleeps_Setup.exe`:**
  - Assistente gráfico clássico (*Avançar → Pasta de destino → Instalar*).
  - Cria atalhos na Área de Trabalho e Menu Iniciar com `assets/app_icon.ico`.
  - Registra **Desinstalador oficial** em *Aplicativos Instalados* do Windows (com opção de preservar `input/`, `output/` e `.env`).

---

## 5. Upload Headless & Redução de Erros de Rascunho (`src/youtube_publisher.py`)
- **Login vs. Publicação Headless:**
  - O **login inicial** continua em janela visível (para passar por 2FA/verificações do Google e salvar a sessão em `temp/youtube_chrome_profile/`).
  - Na hora de **Publicar**, se a janela de login não estiver aberta (ou após fechar), o sistema sobe o Chrome real com **`--headless=new`** usando o mesmo perfil autenticado — invisível na tela e mais rápido.
- **Aceleração & Anti-Throttling:**
  - Adicionar flags `--disable-background-timer-throttling`, `--disable-renderer-backgrounding` e `--disable-backgrounding-occluded-windows` para evitar que o Chrome desacelere uploads em segundo plano/headless.
- **Eliminação de vídeos presos em "Rascunho":**
  - Aguardar o botão **Publicar** ficar realmente habilitado (após checagens/upload) antes de clicar.
  - **Validação pós-clique:** não fechar a aba imediatamente após clicar em *Publicar*; aguardar a confirmação real do diálogo de publicação (*"Vídeo publicado"* / URL final `youtube.com/shorts/...`) e tratar eventuais modais secundários de confirmação.

---

## 6. Filtro de Gancho Inicial (`hook_score` de 0 a 10)
- **Avaliação na Sala de Roteiro (`src/llm_pool.py`):**
  - Exigir que cada corte candidato retorne um campo `hook_score` (`0.0` a `10.0`) avaliando exclusivamente os **primeiros 3 segundos / primeira frase** do clipe.
  - Critérios de nota alta (`>= 7.0`): reação explosiva, grito/susto, pergunta polêmica, afirmação chocante ou entrada imediata no clímax (*Cold Open*).
- **Descarte ou Ajuste Automático (`src/llm_pool.py` + `src/context_analyzer.py`):**
  - Cortes com `hook_score < 6.5` (ex.: início morno, *"então galera"*, silêncio ou frase sem contexto) são **descartados** antes de entrar em `temp/cuts.json` (ou têm seu `start` avançado para a primeira frase de impacto dentro daquele arco).

---

## 7. Jump Cuts Automáticos em Silêncios (> 1.5s)
- **Detecção Híbrida (Transcrição + RMS do Áudio) (`src/video_editor.py`):**
  - Identificar intervalos sem fala com duração `> 1.5s` usando os timestamps de `words`/`segments`, **validados pela energia RMS do WAV** (para não cortar risadas, sustos ou efeitos sonoros importantes mesmo quando não há palavras transcritas).
- **Corte Limpo + Ressincronização de Legendas:**
  - Remover o miolo do silêncio preservando uma micro-respiração natural (`~0.15s–0.20s`) para manter o ritmo humano sem travar o corte.
  - Concatenar os trechos ativos via FFmpeg (`trim` / `atrim` + `concat`) e **re-mapear automaticamente os timestamps** das palavras e legendas `.ass` para o novo tempo comprimido do vídeo.

---

## 8. B-Roll Automático (Wikipédia Imagens + Motion Design Remotion)
- **Extração de Entidades pelo Contexto (`src/llm_pool.py` / `src/context_analyzer.py`):**
  - Ao analisar os cortes selecionados, extrair até **~10 entidades visuais** citadas (pessoas, jogos, lugares, objetos, marcas, eventos) com o timestamp aproximado em que aparecem na fala.
- **Download Inteligente via Wikipédia / Wikimedia (`src/wiki_assets.py`):**
  - Consultar a API pública gratuita da Wikipédia (`pt.wikipedia.org` / `en.wikipedia.org` → `api/rest_v1/page/summary/<termo>` ou `w/api.php?prop=pageimages`) para baixar miniaturas/PNGs/JPGs em boa resolução, salvando em cache local `temp/projects/<stem>/wiki_assets/`.
- **Pop-up Animado com Remotion (`remotion/` + `src/video_editor.py`):**
  - Sempre que um termo for citado no corte, exibir o asset correspondente por **1,2s a 2,0s** em uma área segura da tela (acima das legendas e sem cobrir a facecam), entrando com animação **pop-up elástica** (escala + leve rotação/sombra) e saindo com **fade-out** suave.
  - *Estratégia de performance:* renderizar apenas os overlays animados curtos (`1–2s`) com fundo transparente via Remotion (ou composição direta leve) para somar valor editorial e passar com folga nos critérios de originalidade/monetização do YouTube sem tornar a renderização lenta em CPU.

---

## 9. Correção de Hashtags Genéricas (`#mais`, `#REALISTA`, `#você`, etc.)
- **Causa:** o extrator de fallback gerava hashtags a partir de qualquer palavra com 4+ letras do título/nome do arquivo, transformando palavras comuns/stopwords em `#mais`, `#você`, `#para`, `#essa`, etc.
- **Correção (`src/llm_pool.py` + `src/youtube_publisher.py`):**
  - Aplicar lista abrangente de **stopwords PT-BR e EN** (pronomes, advérbios, preposições, verbos auxiliares e adjetivos genéricos como `mais`, `você`, `muito`, `isso`, `como`, `esse`, `tudo`, `aqui`, `agora`, `melhor`, `realista`, `with`, `this`, `that`, `from`, `your`, etc.).
  - Priorizar **substantivos próprios / palavras capitalizadas / termos de nicho** e normalizar acentos para hashtags limpas e relevantes.


