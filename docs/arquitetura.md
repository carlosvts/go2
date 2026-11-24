# Arquitetura

Três serviços independentes que só conversam por HTTP. Nenhum importa código de outro; os contratos estão em [`specs/contracts/`](../specs/contracts/).

Cores em todos os diagramas: 🟩 tvbox · 🟦 server · 🟧 api · ⬜ Go2 · 🟪 dados e arquivos · 🟨 Docker e CI.

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
    CLIENTS["Outros clientes da api<br/>scripts, notebooks, Insomnia,<br/>visualizadores de LiDAR/vídeo"]

    SENSE -->|"POST /v1/utterance<br/>WAV + meta"| SERVER
    SERVER -->|"status → som de retorno"| SENSE
    SERVER -->|"POST /commands/*<br/>GET/PUT /safety/obstacle-avoidance<br/>GET /status"| API
    STOPCLI -->|"POST /commands/stop"| API
    STOPCLI -.->|"POST /v1/cancel (em paralelo)"| SERVER
    API <-->|"WebRTC"| GO2
    CLIENTS -->|"HTTP: /commands, /status, /device, /audio, /speaker<br/>WS: /ws/state, /ws/lidar, /ws/telemetry, /ws/video"| API

    classDef tvbox fill:#c8e6c9,stroke:#2e7d32,color:#000
    classDef server fill:#bbdefb,stroke:#1565c0,color:#000
    classDef api fill:#ffe0b2,stroke:#ef6c00,color:#000
    classDef robot fill:#e0e0e0,stroke:#424242,color:#000
    classDef data fill:#e1bee7,stroke:#6a1b9a,color:#000
    classDef client fill:#fff,stroke:#ef6c00,stroke-dasharray:4 3,color:#000
    class MIC,SENSE,SPK,STOPCLI tvbox
    class SERVER server
    class API api
    class GO2 robot
    class CAT,MODELS,CAPT data
    class CLIENTS client
    style TVBOX fill:#e8f5e9,stroke:#2e7d32,color:#000
    style PC fill:#fff8e1,stroke:#f9a825,color:#000
```

| Serviço | Onde roda | Porta | Fala com |
|---|---|---|---|
| `api/` | PC, container `go2-api` | 8000 | Go2 (WebRTC); recebe do server, do `sense.stop` e de qualquer cliente na rede |
| `server/` | PC, container `go2-server` | 9000 | api; recebe do tvbox |
| `tvbox/` | TV Box, com `uv` direto | — (só cliente) | server; api só no `sense.stop` |

## A api sozinha

A api também é um produto à parte: quem quer só controlar ou observar o Go2 clona só `api/` (e `specs/contracts/`) e não precisa do server nem da TV Box. Passo a passo em [`api/README.md`](../api/README.md).

| Grupo | Rotas | Spec |
|---|---|---|
| Movimento | `/commands/posture`, `/commands/gesture`, `/commands/move`, `/commands/stop`, `/commands/speed`, `/safety/obstacle-avoidance` | — (anterior às specs) |
| Estado e sensores | `GET /status` (bateria, IMU, motores, configurações, erros), `/ws/state` | F-004 |
| Lanterna, LED e volume | `/device/brightness`, `/device/led`, `/device/volume` | F-005 |
| Áudio | `/speaker/*` (tocar na hora), `/audio/*` (biblioteca do robô, `/audio/silence`) | F-006, F-007 |
| Streams | `/ws/lidar`, `/ws/telemetry`, `/ws/video` | F-001, F-002, F-003 |

O que a lib oferece e ficou de fora, com o motivo, está em [`api/docs/cobertura_lib.md`](../api/docs/cobertura_lib.md). Truques, modo bípede, MCF e controle de motor direto estão restritos pelo `AGENTS.md`. Todas as rotas, com exemplos, estão na coleção do Insomnia (`api/insomnia/go2-api.json`).

## Um comando de voz

```mermaid
sequenceDiagram
    autonumber
    participant P as Pessoa
    box rgba(46,125,50,0.15) TV Box
        participant T as tvbox (Sense)
    end
    box rgba(21,101,192,0.15) server no PC
        participant S as server
    end
    box rgba(239,108,0,0.15) api no PC
        participant A as api
    end
    box rgba(66,66,66,0.15) Robô
        participant R as Go2
    end

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
    box rgba(46,125,50,0.15) TV Box
        participant T as tvbox
    end
    box rgba(21,101,192,0.15) server no PC
        participant S as server
    end
    box rgba(239,108,0,0.15) api no PC
        participant A as api
    end

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

    classDef infra fill:#fff9c4,stroke:#f9a825,color:#000
    classDef tvbox fill:#c8e6c9,stroke:#2e7d32,color:#000
    classDef server fill:#bbdefb,stroke:#1565c0,color:#000
    classDef api fill:#ffe0b2,stroke:#ef6c00,color:#000
    class ROOT infra
    class AC,AI,ACT api
    class SC,SI,SCT server
    class TV tvbox
```

- `network_mode: host`, só em Linux: a api precisa enxergar a LAN do robô (descoberta por multicast e WebRTC), e o server fala com ela por `127.0.0.1:8000`.
- O healthcheck da api diz se ela responde, não se o robô está conectado: isso é o campo `connected` de `GET /status`.
- `docker compose --profile api --profile server up --build` na raiz sobe os dois; cada pasta também sobe sozinha com o próprio perfil.

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

    classDef api fill:#ffe0b2,stroke:#ef6c00,color:#000
    classDef server fill:#bbdefb,stroke:#1565c0,color:#000
    classDef data fill:#e1bee7,stroke:#6a1b9a,color:#000
    class CAP api
    class B,IMG,EVAL server
    class CJ,PJ,INF,CAT data
```

Nada regenera o catálogo sozinho. Editar `discovery/` sem rodar o `build_catalog.py` (e sem rebuild da imagem) deixa o robô com o catálogo antigo.

## CI e contratos

```mermaid
flowchart LR
    PR["pull request / push na main"] --> ACI["api-ci.yml + api-build.yml<br/>paths: api/**"]
    PR --> SCI["server-ci.yml<br/>paths: server/**"]
    PR --> TCI["tvbox-ci.yml<br/>paths: tvbox/**"]
    PR --> CC["contracts-check.yml<br/>paths: api/, server/, specs/contracts/"]
    CC -->|"create_app().openapi()"| DIFF{"git diff --exit-code<br/>specs/contracts/"}
    DIFF -->|"igual"| OK["passa"]
    DIFF -->|"diferente"| FAIL["falha: contrato mudou sem atualizar specs/contracts/"]

    classDef infra fill:#fff9c4,stroke:#f9a825,color:#000
    classDef tvbox fill:#c8e6c9,stroke:#2e7d32,color:#000
    classDef server fill:#bbdefb,stroke:#1565c0,color:#000
    classDef api fill:#ffe0b2,stroke:#ef6c00,color:#000
    classDef data fill:#e1bee7,stroke:#6a1b9a,color:#000
    classDef ok fill:#a5d6a7,stroke:#1b5e20,color:#000
    classDef fail fill:#ef9a9a,stroke:#b71c1c,color:#000
    class PR,CC infra
    class ACI api
    class SCI server
    class TCI tvbox
    class DIFF data
    class OK ok
    class FAIL fail
```

| Contrato | Dono | Consumidores |
|---|---|---|
| `specs/contracts/api.openapi.json` | api | server; tvbox (só `POST /commands/stop`) |
| `specs/contracts/server.openapi.json` | server | tvbox (`/v1/utterance`, `/v1/cancel`) |
