# Arquitetura

Três serviços independentes que só conversam por HTTP. Nenhum importa código de outro; os contratos estão em [`specs/contracts/`](../specs/contracts/).

## Visão geral

```mermaid
flowchart LR
    subgraph TVBOX["TV Box (aarch64, Debian 11, sem Docker)"]
        MIC["Microfone Anker"] --> SENSE["tvbox/ — Sense<br/>openWakeWord hey_jarvis + VAD"]
        SENSE --> SPK["Alto-falante<br/>beeps e falas de retorno"]
        STOPCLI["python -m sense.stop<br/>parada manual"]
    end

    subgraph PC["PC do laboratório (Docker, network_mode: host)"]
        SERVER["server/ — go2-server :9000<br/>Whisper → interpretação → fila"]
        API["api/ — go2-api :8000<br/>única conexão WebRTC"]
        CAT[("catalog.yaml")]
        MODELS[("volume models<br/>Whisper + embeddings")]
        CAPT[("server/captures/")]
        CAT -.-> SERVER
        MODELS -.-> SERVER
        SERVER -.->|GO2S_SAVE_UTTERANCES=1| CAPT
    end

    GO2["Unitree Go2"]

    SENSE -->|"POST /v1/utterance<br/>WAV + meta"| SERVER
    SERVER -->|"status → som de retorno"| SENSE
    SERVER -->|"POST /commands/*<br/>GET/PUT /safety/obstacle-avoidance<br/>GET /status"| API
    STOPCLI -->|"POST /commands/stop"| API
    STOPCLI -.->|"POST /v1/cancel (em paralelo)"| SERVER
    API <-->|"WebRTC"| GO2
```

| Serviço | Onde roda | Porta | Fala com |
|---|---|---|---|
| `api/` | PC, container `go2-api` | 8000 | Go2 (WebRTC); recebe do server e do `sense.stop` |
| `server/` | PC, container `go2-server` | 9000 | api; recebe do tvbox |
| `tvbox/` | TV Box, com `uv` direto | — (só cliente) | server; api só no `sense.stop` |

## Um comando de voz

```mermaid
sequenceDiagram
    autonumber
    participant P as Pessoa
    participant T as tvbox (Sense)
    participant S as server
    participant A as api
    participant R as Go2

    P->>T: "hey jarvis"
    T->>P: beep
    P->>T: "anda para frente"
    Note over T: grava até o silêncio (VAD)
    T->>S: POST /v1/utterance (WAV + meta)
    Note over S: Whisper → tira a wake word →<br/>interpreta pelo catálogo → enfileira
    S-->>T: 200 {status: enqueued, ...}
    T->>P: som "confirmado"
    Note over S,A: a fila executa depois de responder
    S->>A: GET /safety/obstacle-avoidance
    opt desvio desligado
        S->>A: PUT /safety/obstacle-avoidance {enabled: true}
    end
    opt robô não está em balance_stand
        S->>A: POST /commands/posture {cmd: balance_stand}
    end
    S->>A: POST /commands/move {vx, vy, vyaw, duration_s}
    A-->>S: 202 (aceito, não executado)
    A->>R: Move reenviado a 40 Hz, depois StopMove
    Note over S: espera max_duration_s do catálogo
```

A resposta do server à TV Box só diz se a frase virou comando (`enqueued`, `rejected`, `stopped` ou `ignored`). Ela não espera o robô executar.

## Parada

```mermaid
sequenceDiagram
    participant T as tvbox
    participant S as server
    participant A as api

    rect rgba(128,128,128,0.1)
    Note over T,A: Falada: passa pelo server (depende de rede e Whisper)
    T->>S: POST /v1/utterance ("hey jarvis, para")
    Note over S: limpa a fila
    S->>A: POST /commands/stop
    S-->>T: 200 {status: stopped}
    end

    rect rgba(128,128,128,0.1)
    Note over T,A: Manual: python -m sense.stop (não depende do server)
    par
        T->>A: POST /commands/stop
    and
        T->>S: POST /v1/cancel {reason: stop}
    end
    end
```

## Docker e deploy

```mermaid
flowchart TB
    ROOT["docker-compose.yml (raiz)<br/>include"] --> AC["api/docker-compose.yml<br/>profile: api"]
    ROOT --> SC["server/docker-compose.yml<br/>profile: server"]

    AC --> AI["imagem go2-api:local<br/>api/Dockerfile (multi-stage, PortAudio)"]
    SC --> SI["imagem go2-server:local<br/>server/deploy/Dockerfile<br/>copia catalog.yaml no build"]

    AI --> ACT["container go2-api<br/>network_mode: host · env_file: api/.env<br/>healthcheck GET /status · restart: unless-stopped"]
    SI --> SCT["container go2-server<br/>network_mode: host · env_file: server/.env<br/>gpus: all · cpus: 4 · healthcheck GET /health<br/>volumes: models, ./captures"]

    TV["TV Box: clone parcial (tvbox + specs/contracts)<br/>uv sync + python -m sense"]
```

- `network_mode: host`, só em Linux: a api precisa enxergar a LAN do robô (descoberta por multicast e WebRTC), e o server fala com ela por `127.0.0.1:8000`.
- O healthcheck da api diz se ela responde, não se o robô está conectado: isso é o campo `connected` de `GET /status`.
- `docker compose --profile api --profile server up -d --build` na raiz sobe os dois; cada pasta também sobe sozinha com o próprio perfil.

## Catálogo (antes de rodar, manual)

```mermaid
flowchart LR
    CAP["GET /capabilities<br/>da api no ar"] -->|"build_catalog.py --capabilities"| CJ["discovery/capabilities.json<br/>(cópia, não ao vivo)"]
    CJ --> B["scripts/build_catalog.py"]
    PJ["discovery/phrases.json<br/>discovery/commands.json"] --> B
    INF["discovery/inferred.yaml<br/>durações, frases, enabled_inferred"] --> B
    B -->|"commitar"| CAT["server/catalog.yaml"]
    CAT -->|"docker compose ... --build"| IMG["imagem go2-server"]
    CAT --> EVAL["eval/phrases.yaml<br/>scripts/calibrate.py"]
```

Nada regenera o catálogo sozinho. Editar `discovery/` sem rodar o `build_catalog.py` (e sem rebuild da imagem) deixa o robô com o catálogo antigo.

## CI e contratos

```mermaid
flowchart LR
    PR["pull request / push na main"] --> ACI["api-ci.yml + api-build.yml<br/>paths: api/**"]
    PR --> SCI["server-ci.yml<br/>paths: server/**"]
    PR --> TCI["tvbox-ci.yml<br/>paths: tvbox/**"]
    PR --> CC["contracts-check.yml<br/>paths: api/**, server/**, specs/contracts/**"]
    CC -->|"create_app().openapi()"| DIFF{"git diff --exit-code<br/>specs/contracts/"}
    DIFF -->|"igual"| OK["passa"]
    DIFF -->|"diferente"| FAIL["falha: contrato mudou sem atualizar specs/contracts/"]
```

| Contrato | Dono | Consumidores |
|---|---|---|
| `specs/contracts/api.openapi.json` | api | server; tvbox (só `POST /commands/stop`) |
| `specs/contracts/server.openapi.json` | server | tvbox (`/v1/utterance`, `/v1/cancel`) |
