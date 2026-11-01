# go2

Controle por voz do Unitree Go2 (NEURON/UFLA). Três serviços independentes, só por HTTP:

```
tvbox/ ──áudio──▶ server/ ──HTTP──▶ api/ ──WebRTC──▶ Go2
```

- `api/`: única conexão WebRTC com o robô (PC do lab)
- `server/`: transcrição, interpretação e fila (PC do lab)
- `tvbox/`: wake word e envio do comando (TV Box)
- `specs/`: contratos, features, experimentos e decisões

## Como rodar

```bash
# api
cd api && cp .env.example .env && uv sync
uv run uvicorn app.main:create_app --factory

# server
cd server && cp .env.example .env && uv sync
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 9000

# api e server com Docker
docker compose --profile api --profile server up -d --build
```

Na TV Box, em `tvbox/` (`SERVER_URL` e `GO2_API_URL` no `.env`):

```bash
uv sync --no-dev --extra capture --extra recognition
uv run python -m sense          # cliente de voz
uv run python -m sense.stop     # parada manual, direto na api
```

### Catálogo do server

O server usa o `server/catalog.yaml` commitado (embutido na imagem no build). Nada o regenera sozinho: nem o container, nem o server, nem o CI. Para rodar, não precisa fazer nada.

Regenere à mão, em `server/`, e commite o `catalog.yaml` junto:

```bash
uv run python scripts/build_catalog.py                     # depois de editar discovery/
uv run python scripts/build_catalog.py \
    --capabilities http://127.0.0.1:8000/capabilities      # quando a api mudar os comandos (api no ar)
docker compose --profile server up -d --build              # o catálogo novo só entra com rebuild
```

Editar `discovery/` sem regenerar não dá erro: o robô continua com o catálogo antigo.

## Spec-driven

Comportamento e contratos ficam em `specs/` (regras em [`specs/README.md`](specs/README.md)); regras para agentes nos `AGENTS.md`. Skills em `.claude/skills/`:

1. `new-spec`: escreve a spec (o que não foi medido é `inferido`)
2. um humano aprova
3. `implement-spec`: testes, depois código
4. `check-contracts`: regenera `specs/contracts/` (o CI falha se divergir)
5. `hardware-checklist`: roteiro e resultados no robô
6. `close-experiment`: adota ou rejeita

Só um humano marca `testado-hardware`.

Mais informações em [`docs/spec-driven-development.md`](docs/spec-driven-development.md).

## Migrar a TV Box do go2-tvbox

Disco a ~90%: só clone parcial. O `.env` antigo serve.

```bash
df -h / && free -h
cd ~/go2-tvbox && git status --short --ignored    # guarde .env e WAVs novos de media/

# se a unit systemd antiga estiver instalada
sudo systemctl disable --now go2-sense
sudo rm /etc/systemd/system/go2-sense.service /etc/systemd/journald@go2-sense.conf
sudo systemctl daemon-reload

cd ~ && git clone --filter=blob:none --sparse https://github.com/carlosvts/go2.git
cd go2 && git sparse-checkout set tvbox specs/contracts
cp ~/go2-tvbox/.env tvbox/.env

cd tvbox
uv sync --no-dev --extra capture --extra recognition
uv run python scripts/download_models.py          # hey_jarvis
uv run python -m sense.say --all && uv run python -m sense

rm -rf ~/go2-tvbox                                # depois de funcionar
```

Atualizar: `cd ~/go2 && git pull`.

## Arquitetura

Diagramas de como os serviços interagem, Docker, catálogo e CI em [`docs/arquitetura.md`](docs/arquitetura.md).
