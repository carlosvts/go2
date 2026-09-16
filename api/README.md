# go2-api

Serviço HTTP que é a **dona única da conexão WebRTC** com o Unitree Go2 do projeto NEURON/UFLA. O WebRTC do robô é ponto-a-ponto — só aceita uma conexão por vez, que é a causa do `RobotBusyError` — então alguém precisa segurar essa conexão e multiplexar o acesso a ela. Esta API é esse processo: mantém uma conexão física com o robô e expõe comandos por HTTP, para que o pipeline de voz, o modo chat e outros projetos do NEURON não precisem saber nada de WebRTC, AES ou `aiortc`. Ela não substitui a `unitree_webrtc_connect` (lib MIT do `legion1581`) — ela empacota a responsabilidade que hoje está dentro do container `robot_control`.

Detalhe completo nos documentos de referência:

- [`docs/dossie_go2.md`](docs/dossie_go2.md) — specs do robô, protocolo e mapa de tópicos (`RTC_TOPIC`); seção 12 separa o que já tem wrapper na lib do que exige engenharia reversa.
- [`docs/arquitetura_go2_api.md`](docs/arquitetura_go2_api.md) — camadas, mapeamento de endpoints (seção 4) e ordem de implementação (seção 5).
- [`docs/go2_modelo_mental.md`](docs/go2_modelo_mental.md) — por que a API existe (seção 5), os três modos de rede (seção 3) e os cinco erros comuns (seção 6).

## Rodando

```bash
cp .env.example .env    # preencha GO2_ROBOT_SERIAL_NUMBER ou GO2_ROBOT_IP
uv sync
uv run uvicorn app.main:app --reload
```

Documentação interativa em `http://127.0.0.1:8000/docs`.

Prefira o **serial** ao IP: em `LocalSTA` o robô é cliente DHCP comum e o roteador pode trocar o IP dele a qualquer momento; a descoberta por serial é multicast e imune a isso. E não use um endereço `192.168.123.x` — essa é a rede *interna* do robô, por cabo, sem porta exposta num Pro.

Testes (rodam com o robô desligado, sem abrir WebRTC):

```bash
uv run pytest
```

## Conexão

A conexão é criada **uma vez** no `lifespan` da aplicação e guardada em `app.state.robot`. Não há reconexão automática: se o robô estiver desligado ou a conexão cair, a API continua no ar, `GET /status` passa a responder `connected: false` e os endpoints de comando respondem `503`. Isso é deliberado — reconectar em silêncio a cada request mascararia justamente o problema que o operador precisa enxergar.

Na conexão, a API assina `rt/sportmodestate` e `rt/lf/lowstate` uma única vez e mantém o último estado em memória. É esse cache que `GET /status` lê.

O parâmetro `aes_128_key` **não** é usado: o firmware deste robô é anterior a 1.1.15 e não exige chave por dispositivo (dossiê seção 7.3). O campo existe no `.env.example` apenas como preparo caso o firmware seja atualizado.

## Endpoints

Todos os comandos respondem `202 Accepted` assim que a API **aceita e despacha** o comando — não depois que o robô termina de se mexer (`arquitetura_go2_api.md` seção 2).

| Endpoint | Corpo | Observação |
|---|---|---|
| `POST /commands/posture` | `{"cmd": "stand_up"}` | Enum: `stand_up`, `stand_down`, `sit`, `rise_sit`, `balance_stand`, `recovery_stand`, `damp`. Interrompe qualquer movimento em curso. |
| `POST /commands/move` | `{"vx","vy","vyaw","duration_s"}` | A API reenvia o comando internamente a `GO2_MOVE_RATE_HZ` (20–50Hz) durante `duration_s` e então manda `StopMove`. Velocidade ou duração acima dos tetos configurados → `422`. |
| `POST /commands/stop` | — | Cancela o reenvio em curso e manda `StopMove` na hora. |
| `PUT /commands/speed` | `{"level": 1}` | `SpeedLevel`. |
| `GET /commands/speed` | — | `GetSpeedLevel`. Único endpoint que espera resposta do robô, logo o único sujeito a `504`. |

### `GET /status`

Snapshot pontual lido do cache — não gera tráfego novo com o robô:

```json
{
  "connected": true,
  "battery_percent": 87,
  "mode": 1,
  "sport_state_age_s": 0.03,
  "low_state_age_s": 0.4,
  "raw": null
}
```

Responde `200` mesmo com o robô desligado (com `connected: false`) — é este endpoint que distingue "robô fora do ar" de "API fora do ar", então ele nunca devolve `503`. Os campos `*_age_s` dizem há quanto tempo chegou o último estado, o que revela uma conexão que parou de receber dados sem ter caído formalmente. `?raw=true` inclui os payloads crus.

## Pendente de validação com o robô ligado

Esta sessão foi escrita e testada com o robô inacessível. Três pontos só podem ser fechados com o robô ligado:

1. **Payload de `Move` e `SpeedLevel`.** Os três `.md` confirmam que os comandos existem e estão prontos na lib, mas não registram os nomes dos campos do `parameter`. Em uso aqui, por decisão explícita: `Move` → `{"x", "y", "yaw"}`, `SpeedLevel` → `{"data": level}`.
2. **`battery_percent` e `mode` em `GET /status`.** O formato de `rt/sportmodestate` e `rt/lf/lowstate` não está fixado nos documentos, então a extração tenta caminhos plausíveis (`bms_state.soc`, `bms.soc`, `soc`) e devolve `null` quando nenhum bate — nunca um valor inventado. Use `?raw=true` para ver o formato real e então fixar os caminhos em `app/robot.py`.
3. **Nível em `GET /commands/speed`.** Mesma abordagem: vem `null` se a resposta não for reconhecida, com o payload cru no campo `raw`.

## Fora desta versão

Implementado aqui: apenas o **grupo 4.1** (postura e movimento) da `arquitetura_go2_api.md`, mais `GET /status`. Ficam para sessões futuras:

- **Grupo 4.2** — gestos (`hello`, `stretch`, `finger_heart`...) e "tricks" (`front_flip`, `handstand`...). Os tricks têm risco real de queda e exigem flag de confirmação e teste físico antes.
- **Grupo 4.3** — áudio, LED e volume via `WebRTCAudioHub`/`VUI`. Esforço baixo, a lib já tem tudo pronto.
- **Grupo 4.5** — streams WebSocket (LiDAR, vídeo, telemetria); exige fan-out multi-assinante.
- **MCF, navegação autônoma e UWB** — fora do v1 inteiro, engenharia reversa do payload ainda pendente (dossiê 12.2/12.3).

E, principalmente, duas decisões de design **já registradas mas não implementadas**:

- **Lease de controle de concorrência** (dossiê seção 13) — token com dono e expiração para o controle contínuo, fila para comandos discretos, `StopMove` sempre passando na frente. Sem isso, nesta versão, um `POST /commands/move` novo simplesmente cancela e substitui o anterior: **quem chamar por último ganha**, sem nenhuma arbitragem entre clientes.
- **Autenticação / controle de acesso** (dossiê seção 13.1) — previsto para um gateway futuro. Nesta versão **não há autenticação nenhuma**: qualquer um que alcance a porta da API controla o robô. Trate a porta como confiável e não a exponha fora da rede do laboratório.

## Notas sobre o `robot_control` atual

Duas coisas observadas ao comparar com `unitreego2/robot_control/src/controller.py`, que valem para quem for migrar aquele container para esta API:

- `controller.py` chama `publish_request_new(topic, sport_cmd)` passando um `int`. Na versão atual da lib (2.2.0) o segundo argumento precisa ser um `dict` com a chave `api_id` — passar um `int` levanta `TypeError`. Esta API usa a forma correta.
- O default `ROBOT_IP=192.168.123.161` de lá aponta para a rede interna do robô, que não é onde se conecta em `LocalSTA`. Esse default não foi replicado aqui.
