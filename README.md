# go2

Controle por voz do Unitree Go2 (NEURON/UFLA). Três serviços independentes, só por HTTP:

```
tvbox/ ──áudio──▶ server/ ──HTTP──▶ api/ ──WebRTC──▶ Go2
```

- `api/`: única conexão WebRTC com o robô (PC do lab)
- `server/`: transcrição, interpretação e fila (PC do lab)
- `tvbox/`: wake word e envio do comando (TV Box)
- `specs/`: contratos, features, experimentos e decisões

## Como rodar, do zero

Onde roda cada parte:

| Máquina | O que roda | Como |
|---|---|---|
| PC do lab (Linux, GPU NVIDIA) | `api/`, `server/` e, na E-002, `llama-server` e `piper-tts` | Docker |
| TV Box | `tvbox/` (wake word e microfone) | uv, sem Docker |

A ordem é: preparar o PC, subir a api e o server e conferir sem a TV Box. Só depois ligar a TV Box.

### 1. PC do lab: pré-requisitos

- Linux. A api e o server usam a rede do host (`network_mode: host`), que só funciona em Linux.
- `git`, `curl` e `sox` (`sudo apt install git curl sox` ou `sudo dnf install git curl sox`).
- Docker com o plugin Compose: `docker compose version` tem de responder.
- Driver NVIDIA (`nvidia-smi` funciona) e o [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), para os containers enxergarem a GPU. Confira:

  ```bash
  docker run --rm --gpus all ubuntu nvidia-smi    # tem de listar a placa
  ```

- [uv](https://docs.astral.sh/uv/), para os scripts de teste rodados fora do Docker:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # feche e abra o terminal; depois: uv --version
  ```

### 2. Clonar

```bash
git clone git@github.com:carlosvts/go2.git
cd go2
git checkout <branch>     # main, ou a branch do experimento em teste (ex.: exp/e002-e003)
```

### 3. Configurar a api

```bash
cp api/.env.example api/.env
```

Em `api/.env`, preencha `GO2_ROBOT_SERIAL_NUMBER`. O serial é melhor que `GO2_ROBOT_IP`, porque o IP do robô pode mudar. Para testar sem o robô, use:

```
GO2_CONNECTION_METHOD=LocalAP
GO2_CONNECT_ON_STARTUP=false
```

### 4. Configurar o server

```bash
cp server/.env.example server/.env
```

O `.env.example` já funciona com a api em `127.0.0.1:8000`. Com a resposta falada (E-002, só nas branches que a têm), descomente e ligue:

```
GO2S_LLM_ENABLED=1
```

### 5. Baixar os modelos

Os modelos não ficam no git (`server/models/` está no `.gitignore`).

**Whisper e embeddings:** não precisa fazer nada. O server baixa os dois na primeira subida, cerca de 2 GB, e guarda num volume do Docker. A primeira subida demora.

**Vozes do Piper:** a `faber` é a do `piper-tts` (E-002). A `cadu` é opcional e só serve para variar a voz do `send_wav.py --say`.

```bash
cd server
base=https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR
for v in faber cadu; do for ext in onnx onnx.json; do
  curl -L --create-dirs -o models/piper/pt_BR-$v-medium.$ext \
    $base/$v/medium/pt_BR-$v-medium.$ext
done; done
cd ..
```

**Llama (só E-002, 4,9 GB):** baixe exatamente esta revisão e confira o hash, que está em `server/llm/generation.yaml`:

```bash
cd server
mkdir -p models/llm && curl -L -o models/llm/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf \
  https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/bf5b95e96dac0462e2a09145ec66cae9a3f12067/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
sha256sum models/llm/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
# tem de dar 7b064f5842bf9532c91456deda288a1b672397a54fa729aa665952863033557c
cd ..
```

### 6. Buildar as imagens e subir

Na raiz do repo:

```bash
docker compose --profile api --profile server up -d --build
```

Isso builda a imagem `go2-api:local` e a `go2-server:local`, que também serve o `piper-tts`. Baixa também a imagem pronta do `llama-server`, que na primeira vez demora.

Sem a E-002 (sem o `.gguf`), suba só a api e o server. Senão o `llama-server` fica reiniciando sem o modelo:

```bash
docker compose --profile api --profile server up -d --build go2-api go2-server
```

Acompanhe os logs:

```bash
docker compose --profile api --profile server logs -f
```

Esperado:

- `go2-server`: `Whisper medium em cuda (float16)` e depois `go2-server pronto`. Se aparecer `tentando cpu`, a GPU não foi enxergada (volte ao passo 1).
- Na E-002: `piper pronto em 127.0.0.1:5002` no `piper-tts`, e `offloaded N/N layers to GPU` no `llama-server`. Com Whisper e Llama juntos, confira a VRAM com `nvidia-smi`. Caber em 8 GB é inferido, ninguém mediu.

### 7. Conferir sem a TV Box

```bash
curl http://127.0.0.1:8000/status      # api: "connected": true com o robô
curl http://127.0.0.1:9000/health      # server: diz se alcança a api
```

Mande uma frase sintética ao server, como se fosse a TV Box:

```bash
cd server
uv sync --extra llm
uv run python scripts/send_wav.py --say "hey jarvis qual é o seu nome"   # E-002: resposta salva em reply.wav
uv run python scripts/send_wav.py --say "hey jarvis senta"               # o robô SENTA: área livre
cd ..
```

A resposta impressa traz `status`, `transcript` e `commands`.

### 8. TV Box

Na TV Box, o disco não comporta o monorepo inteiro. Por isso é um clone parcial:

```bash
df -h / && free -h                       # disco a ~90%: confira antes
sudo apt install portaudio19-dev gcc python3-dev
curl -LsSf https://astral.sh/uv/install.sh | sh     # se ainda não tiver o uv

git clone --filter=blob:none --sparse https://github.com/carlosvts/go2.git
cd go2 && git sparse-checkout set tvbox specs/contracts
git checkout <a mesma branch do PC>
cd tvbox
uv sync --no-dev --extra capture --extra recognition
uv run python scripts/download_models.py           # modelo da wake word hey_jarvis
cp .env.example .env
```

No `tvbox/.env`, aponte para o IP do PC do lab:

```
SERVER_URL=http://<IP_DO_PC>:9000
GO2_API_URL=http://<IP_DO_PC>:8000
```

Teste o som e rode:

```bash
uv run python -m sense.say --all      # beep e todas as falas de retorno
uv run python -m sense                # log: Wake word pronta, Servidor de inferência no ar, Microfone aberto
```

Diga "hey jarvis", espere o beep e fale o comando. Deixe um segundo terminal pronto com a parada manual, que vai direto à api:

```bash
uv run python -m sense.stop
```

A parada falada passa pelo server e depende da rede e do Whisper. Ela **não é garantida**: tenha o `sense.stop` ou o controle do robô à mão.

### Atualizar

```bash
git pull
docker compose --profile api --profile server up -d --build      # no PC: o código, o catalog.yaml e server/llm/ vão dentro da imagem
```

Na TV Box, basta `git pull` e reiniciar o `sense`.

### Sem Docker (desenvolvimento)

Em dois terminais, a partir da raiz do repo:

```bash
cd api && uv sync && uv run uvicorn app.main:create_app --factory
```

```bash
cd server && uv sync && uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 9000
```

O server usa a GPU fora do Docker se o sistema tiver cuBLAS e cuDNN 9. Se não tiver, veja a seção GPU do [`server/README.md`](server/README.md#gpu).

### Catálogo do server

O server usa o `server/catalog.yaml` commitado (embutido na imagem no build). Nada o regenera sozinho: nem o container, nem o server, nem o CI. Para rodar, não precisa fazer nada.

Regenere à mão, em `server/`, e commite o `catalog.yaml` junto:

```bash
uv run python scripts/build_catalog.py                     # depois de editar discovery/
uv run python scripts/build_catalog.py \
    --capabilities http://127.0.0.1:8000/capabilities      # quando a api mudar os comandos (api no ar)
docker compose --profile server up --build                 # o catálogo novo só entra com rebuild
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

## Licença

Todos os direitos reservados ao NEURON/UFLA. Ver [`LICENSE`](LICENSE). As dependências de terceiros seguem as próprias licenças.
