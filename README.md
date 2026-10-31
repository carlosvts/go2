# go2

Controle por voz do robô Unitree Go2 (NEURON/UFLA). Três serviços independentes, que só conversam por HTTP:

```
TV Box (tvbox/) ──áudio──▶ go2-server (server/) ──HTTP──▶ go2-api (api/) ──WebRTC──▶ Go2
```

| Pasta | O que é | Onde roda |
|---|---|---|
| [`api/`](api/) | go2-api: dona da única conexão WebRTC com o robô, expõe os comandos por HTTP | PC do laboratório |
| [`server/`](server/) | go2-server: transcrição (Whisper), interpretação e fila de comandos de voz | PC do laboratório |
| [`tvbox/`](tvbox/) | Go2 Sense: wake word e envio do comando falado ao server | TV Box (ARM) |
| [`specs/`](specs/) | contratos, features e decisões (spec-driven, em construção) | — |

Cada serviço tem o próprio `pyproject.toml`, `uv.lock`, `.env` e README. Nenhum importa código de outro.

## Como rodar

Detalhes e configuração no README de cada pasta.

```bash
# api
cd api && cp .env.example .env && uv sync
uv run uvicorn app.main:create_app --factory

# server
cd server && cp .env.example .env && uv sync
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 9000

# tvbox (na TV Box; veja o clone parcial em tvbox/README.md)
cd tvbox && cp .env.example .env && uv sync --no-dev --extra capture --extra recognition
uv run python -m sense
```

Com Docker, api e server juntos (cada um com o seu `.env` na própria pasta):

```bash
docker compose --profile api --profile server up -d --build
```

## CI

Um workflow por serviço em `.github/workflows/`, disparado só quando a pasta dele muda: `api-ci.yml` e `api-build.yml`, `server-ci.yml`, `tvbox-ci.yml`.
