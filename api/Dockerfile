# syntax=docker/dockerfile:1

# ─── Estágio 1: builder ───────────────────────────────────────────────────────
# Tem compilador e headers. Só serve para montar o `.venv`; não vai para a
# imagem final.
FROM python:3.12-slim-bookworm AS builder

# Binário do uv em versão fixa, copiado da imagem oficial.
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /bin/uv

# O `pyaudio` (dependência da unitree_webrtc_connect) não tem wheel pronto para
# Linux: é compilado aqui e precisa do gcc e dos headers do PortAudio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# UV_COMPILE_BYTECODE: gera os .pyc no build, para a API subir mais rápido.
# UV_LINK_MODE=copy: copia os pacotes para o .venv (hardlink não funciona entre
# o cache e a camada da imagem).
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Só os arquivos de dependência primeiro: enquanto eles não mudarem, o Docker
# reaproveita esta camada e não reinstala nada quando só o código muda.
COPY pyproject.toml uv.lock ./

# --locked: falha se o uv.lock não bater com o pyproject (versões fixadas).
# --no-dev: sem pytest/httpx. --no-install-project: só as dependências.
RUN uv sync --locked --no-dev --no-install-project


# ─── Estágio 2: runtime ───────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm

# Biblioteca do PortAudio (sem os headers): a lib importa `sounddevice` ao ser
# carregada, e ele falha sem ela — mesmo a API não usando áudio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

# Usuário sem privilégios para rodar a API.
RUN useradd --create-home --uid 1000 go2
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app

# PATH: usa o Python do .venv. PYTHONUNBUFFERED: os `print` da lib aparecem na
# hora em `docker logs`. UVICORN_HOST/UVICORN_PORT: lidos pelo próprio uvicorn;
# podem ser trocados pelo `.env`.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000

USER go2

# "healthy" = a API responde. NÃO quer dizer que o robô está conectado: isso é
# o campo `connected` de `GET /status`. O timeout é folgado porque cada
# tentativa de reconexão trava a API por alguns segundos, e o start-period
# cobre a primeira tentativa de conexão, feita antes de a API começar a responder.
HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['UVICORN_PORT'] + '/status', timeout=8)"]

# Forma exec (lista): o uvicorn vira o processo principal e recebe o SIGTERM do
# `docker stop`, fechando a conexão WebRTC antes de sair.
CMD ["uvicorn", "app.main:create_app", "--factory"]
