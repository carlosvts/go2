# go2-api

API HTTP que mantém a **única conexão WebRTC** com o Unitree Go2 (NEURON/UFLA). O robô só aceita uma conexão por vez, então os outros serviços (voz, chat etc.) mandam comandos por HTTP em vez de conectar direto.

## Rodando

```bash
cp .env.example .env    # preencha GO2_ROBOT_SERIAL_NUMBER ou GO2_ROBOT_IP
uv sync
uv run uvicorn app.main:app --reload
```

- Documentação interativa: `http://127.0.0.1:8000/docs`
- Testes (não precisam do robô): `uv run pytest`

Prefira o **serial** ao IP, porque o IP pode mudar. Não use `192.168.123.x`: essa é a rede interna do robô.

## Endpoints

| Endpoint | Corpo | O que faz |
|---|---|---|
| `GET /status` | — | Conexão, bateria e modo. Sempre `200`; `?raw=true` inclui os payloads crus. |
| `POST /commands/posture` | `{"cmd": "stand_up"}` | Muda a postura (`stand_up`, `stand_down`, `sit`, `rise_sit`, `balance_stand`, `recovery_stand`, `damp`). |
| `POST /commands/move` | `{"vx", "vy", "vyaw", "duration_s"}` | Move o robô durante `duration_s` e para. |
| `POST /commands/stop` | — | Para na hora. |
| `PUT /commands/speed` | `{"level": 1}` | Define o nível de velocidade. |
| `GET /commands/speed` | — | Lê o nível de velocidade. |

Os comandos respondem `202` quando são enviados, sem esperar o robô terminar. Com o robô desconectado, respondem `503`.

## Limitações atuais

- **Sem autenticação:** quem alcança a porta controla o robô. Use só na rede do laboratório.
- **Sem arbitragem entre clientes:** o último `move` enviado substitui o anterior.
- **Sem reconexão automática:** se a conexão cair, reinicie a API.
- **Pendente de validação com o robô ligado:** os payloads de `Move`/`SpeedLevel` e a leitura de bateria/modo.

## Documentação

- [`docs/go2_modelo_mental.md`](docs/go2_modelo_mental.md): visão geral e modos de rede.
- [`docs/arquitetura_go2_api.md`](docs/arquitetura_go2_api.md): arquitetura e endpoints planejados.
- [`docs/dossie_go2.md`](docs/dossie_go2.md): specs, protocolo e tópicos do robô.
