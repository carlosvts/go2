# go2-api

API HTTP que mantém e multiplexa a **única conexão WebRTC** com o Unitree Go2 (NEURON/UFLA). O robô só aceita uma conexão por vez, então os outros serviços (voz, chat etc.) mandam comandos por HTTP em vez de conectar direto.
<img width="1472" height="800" alt="image" src="https://github.com/user-attachments/assets/f698d3db-2de3-4f88-ac25-461d178a3c12" />

## Rodando

```bash
cp .env.example .env    # preencha GO2_ROBOT_SERIAL_NUMBER ou GO2_ROBOT_IP
uv sync
uv run uvicorn app.main:create_app --factory --reload
```

- Documentação interativa: `http://127.0.0.1:8000/docs`
- Testes (não precisam do robô): `uv run pytest --cov`
- Qualidade: `uv run ruff check . && uv run ruff format --check . && uv run mypy`
- Hooks: `uv run pre-commit install`

Prefira o **serial** ao IP.

> [!NOTE]
> `192.168.123.x` é a rede interna do robô.

### Com Docker

```bash
cp .env.example .env
docker compose --profile api up -d --build
```

O container usa a rede do próprio PC (só Linux) e tem um healthcheck que indica se a API está no ar (não se o robô está conectado: isso é o `connected` do `GET /status`). Detalhes, reconexão e checklist de teste com o robô na [ficha](docs/essencial/rodar-com-docker.md).

### Configuração

Tudo por variáveis de ambiente (ou `.env`), comentadas em [`.env.example`](.env.example): modo de conexão e IP/serial do robô (`GO2_CONNECTION_METHOD`, `GO2_ROBOT_IP`, `GO2_ROBOT_SERIAL_NUMBER`), conexão na subida e intervalo de reconexão (`GO2_CONNECT_ON_STARTUP`, `GO2_RECONNECT_INTERVAL_S`), limites do `move` (`GO2_MAX_VX`, `GO2_MAX_VY`, `GO2_MAX_VYAW`, `GO2_MOVE_MAX_DURATION_S`, `GO2_MOVE_RATE_HZ`), espera por resposta do robô (`GO2_REQUEST_TIMEOUT_S`) e endereço/porta do servidor (`UVICORN_HOST`, `UVICORN_PORT`).

### Sem o robô

Para testar os endpoints sem o robô, use no `.env`:

```bash
GO2_CONNECTION_METHOD=LocalAP
GO2_CONNECT_ON_STARTUP=false
```

A API sobe sem tentar conectar. O `GET /status` responde `200` com `connected: false`, os comandos respondem `503` e corpos inválidos respondem `422`.

> [!NOTE]
> Com `LocalSTA`, a API exige `GO2_ROBOT_IP` ou `GO2_ROBOT_SERIAL_NUMBER` mesmo sem conectar. Por isso o exemplo usa `LocalAP`.

## Arquitetura

| Módulo                            | Responsabilidade                                                                                |
| --------------------------------- | ----------------------------------------------------------------------------------------------- |
| `app/main.py`                     | App factory (`create_app`) e lifespan.                                                          |
| `app/routers/`                    | Wrappers HTTP finos, um por grupo de endpoints.                                                 |
| `app/requests/`, `app/responses/` | Corpos de entrada/saída; entrada inválida nem chega a existir.                                  |
| `app/robot/`                      | Tudo que fala com o robô, sem HTTP: `link`, `channel`, `movement`, `state`, fachada `Go2Robot`. |
| `app/robot/unitree.py`            | Única fronteira com a lib da Unitree.                                                           |
| `app/error_handlers.py`           | Exceção de domínio → status HTTP, num só lugar.                                                 |

## Endpoints

| Endpoint                 | Corpo                                | O que faz                                                                                                                                                                         |
| ------------------------ | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /status`            | —                                    | Conexão (`connected`, `state`, `since`), bateria e modo. `state` é `connected`, `disconnected` ou `reconnecting`. Sempre `200`; `?raw=true` inclui os payloads crus.             |
| `GET /capabilities`      | —                                    | Lista os comandos que a API aceita (nome, método, rota e campos do corpo) e um `version` que muda quando a lista muda. Não depende do robô.                                       |
| `POST /commands/posture` | `{"cmd": "stand_up"}`                | Muda a postura ([lista abaixo](#posturas)). Cancela o `move` em andamento.                                                                                                        |
| `POST /commands/gesture` | `{"cmd": "hello"}`                   | Executa um gesto ([lista abaixo](#gestos)). Cancela o `move` em andamento.                                                                                                        |
| `POST /commands/move`    | `{"vx", "vy", "vyaw", "duration_s"}` | Move o robô durante `duration_s` e para. Acima dos limites configurados (`GO2_MAX_*`, `GO2_MOVE_MAX_DURATION_S`) responde `422`. Um `move` novo substitui o anterior.             |
| `POST /commands/stop`    | —                                    | Interrompe o `move` em andamento e envia `StopMove`: o robô para de andar e fica de pé onde está, sem mudar de postura. Não desliga os motores (para isso, use a postura `damp`). |
| `PUT /commands/speed`    | `{"level": 1}`                       | Define o nível de velocidade.                                                                                                                                                     |
| `GET /commands/speed`    | —                                    | Lê o nível de velocidade. Espera resposta do robô: `504` se ele não responder em `GO2_REQUEST_TIMEOUT_S`.                                                               |
| `PUT /safety/obstacle-avoidance` | `{"enabled": true}`                  | Liga ou desliga o desvio de obstáculo nativo do robô. Não espera confirmação: confira com o `GET`.                                                                                |
| `GET /safety/obstacle-avoidance` | —                                    | Lê se o desvio está ligado: `{"enabled", "raw"}`. Espera resposta do robô (`504` em timeout); `enabled` vem `null` se a resposta não for reconhecida.                             |

Os comandos respondem `202` quando são enviados, sem esperar o robô terminar. Com o robô desconectado, respondem `503`. Comando desconhecido ou corpo inválido responde `422` e nada é enviado ao robô.

Se a conexão com o robô cair, a API reconecta sozinha em segundo plano ([ficha](docs/essencial/rodar-com-docker.md)).

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

## Testar o desvio de obstáculo

Com o robô de pé, em área livre, e alguém pronto para o `POST /commands/stop`:

```bash
API=http://localhost:8000
curl -X PUT $API/safety/obstacle-avoidance -H 'Content-Type: application/json' -d '{"enabled": true}'
curl $API/safety/obstacle-avoidance      # esperado: {"enabled": true, "raw": ...}
```

1. Se o `GET` devolver `enabled: null`, anote o `raw`: é o formato real da resposta, e o caminho de extração em `app/robot/safety.py` precisa ser ajustado a ele.
2. Com `enabled: true`, ponha um obstáculo (uma caixa) a cerca de 1 m na frente do robô e mande-o andar devagar na direção dela:

   ```bash
   curl -X POST $API/commands/move -H 'Content-Type: application/json' \
     -d '{"vx": 0.3, "vy": 0, "vyaw": 0, "duration_s": 3}'
   ```

3. Repita com `{"enabled": false}`. Se o robô para ou desvia só com o desvio ligado, o `Move` é filtrado. Se ele encosta na caixa nos dois casos, o desvio não vale para o `Move` da API, e o movimento terá de ir por outro canal (o `MOVE` da própria API de desvio ou o controle simulado).

## Limitações atuais

- **Sem autenticação:** quem alcança a porta controla o robô. Use só na rede do laboratório.
- **Sem arbitragem entre clientes:** o último `move` enviado substitui o anterior.
- **Reconexão sem reenvio:** se a conexão cair, a API tenta de novo sozinha a cada `GO2_RECONNECT_INTERVAL_S` (`state: reconnecting` no `GET /status`). Enquanto isso os comandos respondem `503` e não são guardados para depois.
- **Queda só visível por polling:** o `GET /status` mostra `state` (`connected`/`disconnected`/`reconnecting`) e `since`, mas ainda não há WebSocket que avise da queda: o tópico `connection` depende do hub (#9, #12). O `connected` é o que decide os `503` e pode demorar mais que o `state` para refletir uma falha.
- **Desvio de obstáculo não comprovado para o `move`:** ligar o desvio com `PUT /safety/obstacle-avoidance` **não garante** que `POST /commands/move` desvie ou pare. A API anda pelo `SPORT_CMD["Move"]`, e o que o serviço de desvio comprovadamente filtra é o canal do controle. Teste com o robô antes de confiar ([como testar](#testar-o-desvio-de-obstáculo)).
- **Pendente de validação com o robô ligado:** os payloads de `Move`/`SpeedLevel`, a leitura de bateria/modo e o formato da resposta do desvio de obstáculo.

## Documentação

- [`docs/go2_modelo_mental.md`](docs/go2_modelo_mental.md): visão geral e modos de rede.
- [`docs/arquitetura_go2_api.md`](docs/arquitetura_go2_api.md): arquitetura, endpoints implementados e planejados.
- [`docs/dossie_go2.md`](docs/dossie_go2.md): specs, protocolo e tópicos do robô.
- [`docs/lib_unitree_webrtc_connect.md`](docs/lib_unitree_webrtc_connect.md): comportamento real da lib 2.2.0 (pub/sub, timeouts, vídeo, lidar).

Índice completo em [`docs/README.md`](docs/README.md).

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
