# go2-api

API HTTP que mantém e multiplexa a **única conexão WebRTC** com o Unitree Go2 (NEURON/UFLA). O robô só aceita uma conexão por vez, então os outros serviços (voz, chat etc.) mandam comandos por HTTP em vez de conectar direto.
<img width="1472" height="800" alt="image" src="https://github.com/user-attachments/assets/f698d3db-2de3-4f88-ac25-461d178a3c12" />

## Rodando

```bash
cp .env.example .env    # preencha GO2_ROBOT_SERIAL_NUMBER ou GO2_ROBOT_IP
uv sync
uv run uvicorn app.main:app --reload
```

- Documentação interativa: `http://127.0.0.1:8000/docs`
- Testes (não precisam do robô): `uv run pytest`

Prefira o **serial** ao IP. 

> [!NOTE]
> `192.168.123.x` é a rede interna do robô.

### Sem o robô

Para testar os endpoints sem o robô, use no `.env`:

```bash
GO2_CONNECTION_METHOD=LocalAP
GO2_CONNECT_ON_STARTUP=false
```

A API sobe sem tentar conectar. O `GET /status` responde `200` com `connected: false`, os comandos respondem `503` e corpos inválidos respondem `422`.

> [!NOTE]
> Com `LocalSTA`, a API exige `GO2_ROBOT_IP` ou `GO2_ROBOT_SERIAL_NUMBER` mesmo sem conectar. Por isso o exemplo usa `LocalAP`.

## Endpoints

| Endpoint | Corpo | O que faz |
|---|---|---|
| `GET /status` | — | Conexão, bateria e modo. Sempre `200`; `?raw=true` inclui os payloads crus. |
| `POST /commands/posture` | `{"cmd": "stand_up"}` | Muda a postura ([lista abaixo](#posturas)). |
| `POST /commands/gesture` | `{"cmd": "hello"}` | Executa um gesto ([lista abaixo](#gestos)). |
| `POST /commands/move` | `{"vx", "vy", "vyaw", "duration_s"}` | Move o robô durante `duration_s` e para. |
| `POST /commands/stop` | — | Interrompe o `move` em andamento e envia `StopMove`: o robô para de andar e fica de pé onde está, sem mudar de postura. Não desliga os motores (para isso, use a postura `damp`). |
| `PUT /commands/speed` | `{"level": 1}` | Define o nível de velocidade. |
| `GET /commands/speed` | — | Lê o nível de velocidade. |

Os comandos respondem `202` quando são enviados, sem esperar o robô terminar. Com o robô desconectado, respondem `503`.

## Comandos

### Posturas

Disponíveis em `POST /commands/posture`:

| `cmd` | O que faz |
|---|---|
| `stand_up` | Fica de pé. |
| `stand_down` | Deita. |
| `sit` | Senta. |
| `rise_sit` | Levanta depois de sentar. |
| `balance_stand` | Fica de pé em modo de equilíbrio, pronto para andar. |
| `recovery_stand` | Levanta depois de uma queda. |
| `damp` | Desliga a força dos motores; o robô cai se estiver de pé. |

### Gestos

Disponíveis em `POST /commands/gesture`. Um movimento em curso é cancelado antes do gesto.

| `cmd` | O que faz |
|---|---|
| `hello` | Acena com a pata. |
| `stretch` | Se espreguiça. |
| `finger_heart` | Faz um coração com as patas. |
| `wiggle_hips` | Rebola. |
| `content` | Demonstra contentamento. |
| `dance1`, `dance2` | Danças. |
| `scrape` | Arranha o chão. |
| `pose` | Faz uma pose. |

### Truques (planejado)

Também **não implementados**. Têm risco real de queda e vão exigir `"confirm": true` em `POST /commands/trick`: `front_flip`, `back_flip`, `handstand`, `moon_walk`, `bound`.

## Limitações atuais

- **Sem autenticação:** quem alcança a porta controla o robô. Use só na rede do laboratório.
- **Sem arbitragem entre clientes:** o último `move` enviado substitui o anterior.
- **Sem reconexão automática:** se a conexão cair, reinicie a API.
- **Pendente de validação com o robô ligado:** os payloads de `Move`/`SpeedLevel` e a leitura de bateria/modo.

## Documentação

- [`docs/go2_modelo_mental.md`](docs/go2_modelo_mental.md): visão geral e modos de rede.
- [`docs/arquitetura_go2_api.md`](docs/arquitetura_go2_api.md): arquitetura e endpoints planejados.
- [`docs/dossie_go2.md`](docs/dossie_go2.md): specs, protocolo e tópicos do robô.
