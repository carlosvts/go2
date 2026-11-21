# go2-api

API HTTP e WebSocket para controlar e observar um **Unitree Go2** pela rede, sem lidar com WebRTC. Ela mantém a **única conexão WebRTC** que o robô aceita e a divide entre quantos clientes você quiser: scripts, notebooks, outros serviços. Projeto do NEURON/UFLA.

<img width="1472" height="800" alt="image" src="https://github.com/user-attachments/assets/f698d3db-2de3-4f88-ac25-461d178a3c12" />

**O que dá para fazer:** mudar postura, fazer gestos, andar e parar; ler bateria, IMU, motores, temperaturas e erros; acender a lanterna, mudar a cor do LED e o volume; tocar áudio no alto-falante ou guardar áudios no robô; receber em tempo real a nuvem de pontos do LiDAR, o vídeo da câmera e o estado do robô.

> [!WARNING]
> É um robô de ~15 kg. Antes de mandar ele andar, leia [Segurança](#segurança). Não há autenticação: quem alcança a porta controla o robô. Use só na rede do laboratório.

## Começar

### 1. Pegar só a api

Este repositório também tem o pipeline de voz (`server/`, `tvbox/`), de que você não precisa. Para baixar só a api e os contratos:

```bash
git clone --filter=blob:none --sparse https://github.com/carlosvts/go2.git
cd go2
git sparse-checkout set api specs/contracts
cd api
```

### 2. Configurar

```bash
cp .env.example .env
```

No `.env`, o mínimo é dizer onde o robô está. Com o robô no Wi-Fi do roteador (modo **LocalSTA**), use o **serial** (`B42D...`, na etiqueta ou no app). A api acha o robô mesmo se o IP mudar:

```bash
GO2_CONNECTION_METHOD=LocalSTA
GO2_ROBOT_SERIAL_NUMBER=B42D2000XXXXXXXX
```

Com o robô criando a própria rede (modo **LocalAP**, IP fixo `192.168.12.1`), basta `GO2_CONNECTION_METHOD=LocalAP` com o computador conectado ao Wi-Fi do robô.

> [!NOTE]
> `192.168.123.x` é a rede interna do robô, alcançável só por cabo. Não use esse IP.

### 3. Rodar

**Com Docker** (Linux; recomendado para quem só quer usar):

```bash
docker compose --profile api up --build
```

**Com Python** (precisa do [uv](https://docs.astral.sh/uv/) e da PortAudio: `sudo apt install portaudio19-dev` no Debian/Ubuntu):

```bash
uv sync
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Abra **`http://localhost:8000/docs`**: todas as rotas, com os corpos e a opção de testar no navegador. O log deve mostrar `🐝 Conectado ao Go2.`, e o `GET /status` deve ter `"connected": true`.

O container usa a rede do próprio PC (`network_mode: host`), porque a descoberta do robô usa multicast e o WebRTC precisa anunciar o IP real. Por isso o Docker só funciona assim no Linux. Detalhes na [ficha](docs/essencial/rodar-com-docker.md).

### Primeiros comandos

```bash
API=http://localhost:8000
curl $API/status                                   # conexão, bateria, sensores
curl -X POST $API/commands/posture -H 'content-type: application/json' -d '{"cmd":"stand_up"}'
curl -X POST $API/commands/gesture -H 'content-type: application/json' -d '{"cmd":"hello"}'
curl -X PUT  $API/device/led -H 'content-type: application/json' -d '{"color":"cyan","duration_s":5}'
curl -X POST $API/speaker/play -F file=@meu-audio.mp3
curl -X POST $API/commands/stop                    # parar (deixa o robô de pé)
```

Em Python:

```python
import httpx

api = httpx.Client(base_url="http://localhost:8000")
print(api.get("/status").json()["battery"])
api.post("/commands/posture", json={"cmd": "balance_stand"})  # necessário antes de andar
api.post("/commands/move", json={"vx": 0.3, "vy": 0, "vyaw": 0, "duration_s": 2})
```

### Sem o robô

Para desenvolver sem o robô:

```bash
GO2_CONNECTION_METHOD=LocalAP
GO2_CONNECT_ON_STARTUP=false
```

A api sobe sem conectar: `GET /status` responde `connected: false`, os comandos respondem `503` e corpos inválidos respondem `422`. Os testes também não precisam do robô: `uv run pytest`.

## Segurança

- **`move` exige `balance_stand` antes.** Só `stand_up` não basta ([ficha](docs/essencial/balance-stand-vs-stand-up.md)).
- **`POST /commands/stop`** interrompe o movimento e deixa o robô de pé. **`damp`** desliga os motores: **o robô cai** se estiver de pé.
- Tenha sempre um jeito de parar à mão: um terminal com o `curl -X POST $API/commands/stop` já digitado, e o controle remoto do Go2.
- Gesto já enviado não é cancelável; só o `stop` interrompe um `move`.
- O desvio de obstáculo nativo (`/safety/obstacle-avoidance`), no teste da equipe, **para** o robô antes de bater. Não foi visto contornar.
- Truques (flips, pulos) e o modo bípede **não estão expostos** de propósito: risco real de queda.
- Som alto e luz forte de repente assustam quem está perto, sobretudo criança. `POST /audio/silence` cala o robô.
- Os streams (LiDAR, vídeo) dividem a conexão com os comandos. Até a equipe medir o efeito no `stop`, evite mover o robô com eles ligados.

## O que a api faz

Todas as rotas, com os corpos e as respostas, estão em **`/docs`** (OpenAPI). Este resumo diz o que cada uma faz.

**Convenções**:
- `202`: o robô **aceitou** o pedido. Não quer dizer que terminou. Ex.: o gesto pode estar em andamento, e o som pode ainda não ter tocado.
- `422`: corpo inválido; nada é enviado.
- `502`: o robô recusou ou respondeu algo ilegível.
- `503`: sem conexão com o robô.
- `504`: o robô não respondeu em `GO2_REQUEST_TIMEOUT_S`.

Em `502` e `504` o pedido **pode ter sido aplicado**: confira com o `GET` correspondente.

### Movimento

| Rota | Corpo | O que faz |
|---|---|---|
| `POST /commands/posture` | `{"cmd": "stand_up"}` | Postura ([lista](#posturas)). Cancela o `move` em andamento. |
| `POST /commands/gesture` | `{"cmd": "hello"}` | Gesto ([lista](#gestos)). Cancela o `move` em andamento. |
| `POST /commands/move` | `{"vx", "vy", "vyaw", "duration_s"}` | Anda durante `duration_s` e para. Acima de `GO2_MAX_*` ou `GO2_MOVE_MAX_DURATION_S` responde `422`. Um `move` novo substitui o anterior. |
| `POST /commands/stop` | — | Para e fica de pé onde está. |
| `PUT` / `GET /commands/speed` | `{"level": 1}` | Nível de velocidade. |
| `PUT` / `GET /safety/obstacle-avoidance` | `{"enabled": true}` | Liga, desliga e consulta o desvio de obstáculo nativo. |
| `GET /capabilities` | — | Comandos de movimento aceitos, para catálogos automáticos. Não depende do robô. |

### Estado e sensores

| Rota | O que faz |
|---|---|
| `GET /status` | Conexão (`connected`, `state`, `since`), `battery` (percentual, tensão, corrente, ciclos, temperaturas), `imu`, `motion` (modo, posição, velocidade, altura do corpo…), `motors` (ângulo, temperatura), `body_temperature_c`, `settings` (brilho, volume, nível de velocidade, desvio…) e `errors`, os erros ativos do robô. `errors: null` quer dizer **desconhecido**, não "sem erros". Sempre `200`; `?raw=true` inclui os payloads crus. |
| `GET /ws/state` (WebSocket) | O mesmo em tempo real, em frames JSON, até `GO2_STATE_MAX_HZ` por tópico; inclui o estado do alto-falante e do player do robô. [Contrato](../specs/contracts/ws-state.md). |

Os nomes e as unidades dos campos vêm dos exemplos da lib e ainda não foram conferidos no robô.

### Lanterna, LED e volume

| Rota | Corpo | O que faz |
|---|---|---|
| `PUT` / `GET /device/brightness` | `{"level": 0–10}` | Brilho da lanterna. |
| `PUT` / `GET /device/volume` | `{"level": 0–10}` | Volume do alto-falante. |
| `PUT /device/led` | `{"color", "duration_s", "flash_cycle_ms"?}` | Cor do LED por um tempo: `white`, `red`, `yellow`, `blue`, `green`, `cyan` ou `purple`. Com `flash_cycle_ms`, pisca. |

`GO2_MAX_VOLUME` e `GO2_MAX_BRIGHTNESS` limitam o que a api aceita; o padrão `10` não limita.

### Áudio

Formatos: **WAV e MP3**. Não precisa de `ffmpeg`. Limite: `GO2_AUDIO_MAX_UPLOAD_MB` (padrão 5 MB).

| Rota | O que faz |
|---|---|
| `POST /speaker/play` (multipart `file`) | Toca o arquivo no alto-falante **na hora**, sem guardar no robô. Substitui o que estiver tocando. |
| `POST /speaker/stop`, `GET /speaker` | Cala; diz o que está tocando. |
| `GET /audio/files` | Lista os áudios **guardados no robô**. |
| `POST /audio/files` (multipart `file`, `name`?) | Envia um áudio para o robô guardar. O envio é lento (minutos para alguns MB): responde `202` com um `upload_id` e o andamento fica em `GET /audio/uploads/{upload_id}`. |
| `POST /audio/files/{id}/play`, `PATCH` / `DELETE /audio/files/{id}` | Toca, renomeia, apaga. |
| `POST /audio/pause`, `POST /audio/resume`, `PUT` / `GET /audio/play-mode` | Controle do player do robô (`single_cycle`, `no_cycle`, `list_loop`). |
| `GET /audio/player` | Último estado do player publicado pelo robô (cru). |
| `POST /audio/silence` | **Cala tudo**: pausa o player do robô e para o alto-falante. |

### Streams (WebSocket)

Todos aceitam a conexão, mandam o estado da conexão com o robô em texto e ficam abertos se ele cair. Também têm limite de clientes (`1013` quando cheio).

| Rota | O que manda | Contrato |
|---|---|---|
| `/ws/lidar` | Nuvem de pontos do LiDAR, frames binários `float32` | [ws-lidar](../specs/contracts/ws-lidar.md) |
| `/ws/telemetry` | Métricas, pose e estado do LiDAR, frames JSON | [ws-telemetry](../specs/contracts/ws-telemetry.md) |
| `/ws/video` | Câmera frontal, um JPEG por frame binário | [ws-video](../specs/contracts/ws-video.md) |
| `/ws/state` | Estado e sensores, frames JSON | [ws-state](../specs/contracts/ws-state.md) |

Ferramentas prontas em `scripts/`:
- visualizadores no navegador: `lidar_viewer.html` e `video_viewer.html`;
- clientes de diagnóstico: `ws_lidar_client.py`, `ws_video_client.py` e `ws_state_client.py`;
- gravadores: `record_lidar.py` e `record_video.py`.

### O que já foi testado no robô

Cada rota tem uma spec em [`specs/features/`](../specs/features/) com o que já foi verificado. Resumo:

| Grupo | Testado no robô |
|---|---|
| Postura, gestos, `move`, `stop` | sim, usados pela equipe com o pipeline de voz |
| Velocidade, desvio de obstáculo | em parte (o desvio para antes de bater) |
| `/ws/lidar`, `/ws/telemetry` | dados reais gravados; efeito no `stop` não medido |
| `/ws/video`, `/status` ampliado, `/ws/state`, `/device/*`, áudio | **ainda não**: só testes automáticos |

## Configuração

Tudo por variáveis de ambiente ou pelo `.env`, comentadas em [`.env.example`](.env.example). As principais:

| Variável | Padrão | Para quê |
|---|---|---|
| `GO2_CONNECTION_METHOD` | `LocalSTA` | `LocalSTA` (roteador) ou `LocalAP` (rede do robô) |
| `GO2_ROBOT_SERIAL_NUMBER` / `GO2_ROBOT_IP` | — | Onde está o robô (prefira o serial) |
| `GO2_CONNECT_ON_STARTUP` | `true` | `false` para subir sem robô |
| `GO2_MAX_VX`, `GO2_MAX_VY`, `GO2_MAX_VYAW`, `GO2_MOVE_MAX_DURATION_S` | 1,0 / 1,0 / 2,0 / 10 | Limites do `move` |
| `GO2_REQUEST_TIMEOUT_S` | `5` | Espera por resposta do robô |
| `GO2_MAX_VOLUME`, `GO2_MAX_BRIGHTNESS` | `10` | Tetos de volume e brilho |
| `GO2_AUDIO_MAX_UPLOAD_MB` | `5` | Tamanho máximo de áudio |
| `GO2_LIDAR_MAX_CLIENTS`, `GO2_VIDEO_MAX_CLIENTS`, `GO2_STATE_MAX_CLIENTS`, `GO2_TELEMETRY_MAX_CLIENTS` | 1 / 2 / 4 / 1 | Clientes por stream (`0` desliga) |
| `UVICORN_HOST`, `UVICORN_PORT` | `0.0.0.0`, `8000` | Endereço e porta da api |

## Arquitetura

| Módulo | Responsabilidade |
|---|---|
| `app/main.py` | App factory (`create_app`) e lifespan. |
| `app/routers/` | Wrappers HTTP finos, um por grupo de rotas. |
| `app/requests/`, `app/responses/` | Corpos de entrada e saída; entrada inválida nem chega a existir. |
| `app/robot/` | Tudo que fala com o robô, sem HTTP: conexão, canais, movimento, estado, streams, áudio, fachada `Go2Robot`. |
| `app/robot/unitree.py` | Única fronteira com a lib da Unitree (`unitree_webrtc_connect` 2.2.0). |
| `app/error_handlers.py` | Exceção de domínio → status HTTP, num só lugar. |

Qualidade: `uv run pytest --cov`, `uv run ruff check . && uv run ruff format --check . && uv run mypy`.

## Comandos

### Posturas

Disponíveis em `POST /commands/posture`:

| `cmd`            | O que faz                                                                                                                                                            |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `stand_up`       | Fica de pé.                                                                                                                                                          |
| `stand_down`     | Deita.                                                                                                                                                               |
| `sit`            | Senta.                                                                                                                                                               |
| `rise_sit`       | Levanta depois de sentar.                                                                                                                                            |
| `balance_stand`  | Fica de pé em modo de equilíbrio, pronto para andar. **Necessário antes de `move`**: só `stand_up` não basta ([ficha](docs/essencial/balance-stand-vs-stand-up.md)). |
| `recovery_stand` | Levanta depois de uma queda.                                                                                                                                         |
| `damp`           | Desliga a força dos motores; o robô cai se estiver de pé.                                                                                                            |

### Gestos

Disponíveis em `POST /commands/gesture`. Um movimento em curso é cancelado antes do gesto.

| `cmd`              | O que faz                    |
| ------------------ | ---------------------------- |
| `hello`            | Acena com a pata.            |
| `stretch`          | Se espreguiça.               |
| `finger_heart`     | Faz um coração com as patas. |
| `wiggle_hips`      | Rebola.                      |
| `content`          | Demonstra contentamento.     |
| `dance1`, `dance2` | Danças.                      |
| `scrape`           | Arranha o chão.              |
| `pose`             | Faz uma pose.                |

### Truques (planejado)

Também **não implementados**. Têm risco real de queda e vão exigir `"confirm": true` em `POST /commands/trick`: `front_flip`, `back_flip`, `handstand`, `moon_walk`, `bound`.

### Comandos da lib ainda não expostos

A lib (`SPORT_CMD`, versão 2.2.0) tem 49 comandos e a API expõe 21. Os demais **não foram implementados ainda pelo risco de dano físico** ao robô (queda, impacto na carcaça e nos sensores) e só entram depois de testados um a um com o robô. Alguns também dependem de parâmetros que a lib não documenta.

| Grupo                        | Comandos na lib                                                                                                   | Situação                                                                                               |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Rolar no chão                | `Wallow`                                                                                                          | Sem parâmetro, mas o robô rola de costas: risco para a carcaça e os sensores do topo. Tratar como truque. |
| Saltos e investidas          | `FrontJump`, `FrontPounce`                                                                                        | Sem parâmetro, mas o robô salta para a frente. Mesmo cuidado dos truques.                              |
| Truques                      | `FrontFlip`, `BackFlip`, `LeftFlip`, `RightFlip`, `Handstand`, `MoonWalk`, `Bound`, `CrossStep`, `OnesidedStep`   | Risco real de queda. Planejados para `POST /commands/trick` com `"confirm": true`.                     |
| Modos de andar               | `SwitchGait`, `ContinuousGait`, `EconomicGait`, `FreeWalk`, `LeadFollow`, `CrossWalk`, `StandOut`, `Standup`      | Não são gestos: mudam como o robô anda ou ligam um modo. Vários pedem parâmetro. `StandOut` e `Standup` não têm descrição na lib: efeito a confirmar. |
| Ajustes do corpo             | `Euler`, `BodyHeight`, `FootRaiseHeight`, `SwitchJoystick`, `Trigger`, `TrajectoryFollow`                         | Pedem parâmetro, e o formato não está documentado.                                                     |
| Consultas                    | `GetState`, `GetBodyHeight`, `GetFootRaiseHeight`                                                                 | Leituras, sem risco físico; ainda não expostas.                                                        |

Estar na lib não garante que o robô aceite o comando: a lista é a mesma para vários firmwares. Na lib, `FreeWalk` e `LeadFollow` têm o mesmo número (1045), então um dos dois está errado.

## Limitações

- **Sem autenticação:** quem alcança a porta controla o robô. Use só na rede do laboratório.
- **Sem arbitragem entre clientes:** o último pedido vale (um `move` novo substitui o anterior; a última cor do LED fica).
- **Um processo só:** não rode o uvicorn com `--workers`. A conexão com o robô é uma só.
- **Reconexão sem reenvio:** se a conexão cair, a api tenta de novo sozinha a cada `GO2_RECONNECT_INTERVAL_S` (`state: reconnecting`). Enquanto isso, os comandos respondem `503` e nada é guardado para depois. Cada tentativa trava a api por alguns segundos.
- **Não verificado no robô:** formatos de vários payloads (bateria, IMU, erros, VUI, áudio) vêm dos exemplos da lib; veja a tabela "O que já foi testado no robô".

## Documentação

- [`docs/cobertura_lib.md`](docs/cobertura_lib.md): tudo o que a lib oferece e o que a api expõe.
- [`docs/arquitetura_go2_api.md`](docs/arquitetura_go2_api.md): arquitetura, convenções e rotas.
- [`docs/essencial/`](docs/essencial/README.md): fichas curtas (parar o robô, modos de rede, pegadinhas da lib, Docker…).
- [`docs/dossie_go2.md`](docs/dossie_go2.md) e [`docs/lib_unitree_webrtc_connect.md`](docs/lib_unitree_webrtc_connect.md): o robô, o protocolo e a lib 2.2.0.
- [`../specs/contracts/`](../specs/contracts/): contratos dos streams e o OpenAPI.

## Termos

| Termo                             | Significado                                                                                         |
| --------------------------------- | --------------------------------------------------------------------------------------------------- |
| **API**                           | _Application Programming Interface_: aqui, este serviço, que recebe pedidos HTTP e fala com o robô. |
| **HTTP / `GET` / `POST` / `PUT`** | Protocolo de pedido e resposta da web, e os tipos de pedido: ler, disparar, substituir.             |
| **202 / 422 / 503 / 504**         | Códigos de resposta: aceito (não quer dizer executado), corpo inválido, sem conexão com o robô, robô não respondeu a tempo. |
| **Docker / container**            | Programa que roda a API num processo isolado (container), já com tudo de que ela precisa.           |
| **Healthcheck**                   | Teste que o Docker repete para saber se o container está respondendo.                               |
| **Polling**                       | Perguntar de tempos em tempos (aqui, chamar `GET /status` repetidamente) em vez de ser avisado.     |
| **WebRTC**                        | Protocolo de comunicação em tempo real: o túnel entre a API e o robô. Só uma conexão por vez.       |
| **LocalSTA / LocalAP**            | Robô no Wi-Fi do roteador (IP pode mudar) / robô criando a própria rede (IP fixo `192.168.12.1`).   |
| **IP / serial**                   | Endereço do robô na rede / número de série dele (`B42D...`), que a lib usa para achá-lo.            |
| **`damp`**                        | Postura que desliga os motores: o robô cai se estiver de pé.                                        |
| **Lib / `SPORT_CMD`**             | A biblioteca `unitree_webrtc_connect` / a tabela dela com o nome e o número de cada comando.        |
| **Firmware**                      | O software de fábrica que roda dentro do robô. A versão dele muda o que o robô aceita.              |
| **NEURON / UFLA**                 | Grupo de pesquisa do projeto / Universidade Federal de Lavras.                                      |

Mais termos em [`docs/essencial/glossario.md`](docs/essencial/glossario.md).
