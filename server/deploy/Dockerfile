# syntax=docker/dockerfile:1
# Build a partir de server/:  docker build -f deploy/Dockerfile -t go2-server:local .

# ─── Estágio 1: builder ───────────────────────────────────────────────────────
# Só monta o `.venv`. O cache do uv (uma cópia extra de todos os pacotes) fica
# aqui e não vai para a imagem final.
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /srv

# UV_PYTHON_DOWNLOADS=never: o `.venv` tem de apontar para o Python da imagem
# (/usr/local/bin/python3.12), que existe nos dois estágios. Um Python baixado
# pelo uv ficaria só neste estágio e deixaria o `.venv` quebrado no runtime.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# cuBLAS e cuDNN vêm do extra `gpu`; sem GPU no container o Whisper usa a CPU.
# O cache do uv fica num volume do BuildKit: acelera rebuilds sem entrar na camada.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra gpu


# ─── Estágio 2: runtime ───────────────────────────────────────────────────────
FROM python:3.12-slim

# Mesmo caminho do builder (/srv/.venv): o `.venv` guarda caminhos absolutos.
WORKDIR /srv

ENV HF_HOME=/models/huggingface \
    PATH="/srv/.venv/bin:$PATH" \
    NVIDIA=/srv/.venv/lib/python3.12/site-packages/nvidia
ENV LD_LIBRARY_PATH=$NVIDIA/cublas/lib:$NVIDIA/cudnn/lib

COPY --from=builder /srv/.venv /srv/.venv
COPY app ./app
COPY catalog.yaml ./

EXPOSE 9000
HEALTHCHECK --interval=30s --timeout=3s --start-period=120s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=2)"

# Sem `uv run` no runtime: o uv não vai para a imagem e não tenta sincronizar
# nada ao subir. O uvicorn do `.venv` é o processo principal e recebe o SIGTERM.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "9000"]
