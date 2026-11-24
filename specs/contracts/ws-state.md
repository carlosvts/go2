# Contrato: `/ws/state` (api)

Estado do Go2 e erros ativos em tempo real. Comportamento e critérios em [`F-004`](../features/F-004-estado-e-sensores.md). O OpenAPI não descreve WebSocket: este arquivo é a fonte, e o CI **não** o confere. O formato de cada seção é o do `GET /status` (schema `StatusResponse` em [`api.openapi.json`](api.openapi.json)).

| | |
|---|---|
| Dono | api |
| Consumidores | Clientes externos (quem clonar a api). Nenhum no repo. |
| Rota | `GET /ws/state` (upgrade para WebSocket), sem autenticação |
| Processo | Um só (`uvicorn` sem `--workers`): o limite de clientes vale por processo |
| Ativação | Nenhuma. O stream lê o cache que o `/status` já mantém (`rt/lf/lowstate`, `rt/sportmodestate`, `rt/multiplestate`, assinados a cada conexão) e não assina nem cancela nada no robô. |

Os nomes, tipos e unidades dos campos vêm dos exemplos do repositório do legion e **não foram vistos no robô** (`inferido`, F-004 A10).

## Frames

Só texto, JSON estrito (sem `NaN`/`Infinity`), no envelope:

```json
{"topic": "<tópico>", "ts": 1763380000.123, "data": { ... }}
```

`ts`: Unix, segundos. Nas seções, é a chegada à api da mensagem de origem (inclusive no aceite: o cliente sabe a idade do valor). Em `connection` e `errors`, o instante da mudança.

| `topic` | Origem | `data` |
|---|---|---|
| `connection` | estado da conexão | `{"state": "connected" \| "disconnected" \| "reconnecting"}` |
| `battery` | `rt/lf/lowstate` | seção `battery` do `/status` |
| `imu` | `rt/sportmodestate` | seção `imu` |
| `motion` | `rt/sportmodestate` | seção `motion` |
| `motors` | `rt/lf/lowstate` | seção `motors` (lista; item malformado = `null`) |
| `body_temperature_c` | `rt/lf/lowstate` | número ou `null` |
| `settings` | `rt/multiplestate` | seção `settings` (`null` se o `data` não for JSON) |
| `errors` | data channel (`errors`/`add_error`/`rm_error`) | lista dos erros ativos, ou `null` |
| `speaker` | alto-falante da api (F-007) | o mesmo corpo do `GET /speaker`: `{"state": "idle" \| "playing", "playback_id", "name", "started_at", "duration_s"}` |
| `audio_player` | `rt/audiohub/player/state` (F-006) | o `data` cru do player do robô (formato não visto no robô); segue o caminho e o teto das seções |

Campo ilegível vira `null` sozinho (ausente, tipo errado, não finito, lista de tamanho errado). `settings.obstacle_avoidance` é informativo: a fonte de verdade é `/safety/obstacle-avoidance`.

### `errors`

Cada item:

```json
{"source": 300, "source_text": "Motor malfunction", "code": 16, "code_hex": "10",
 "code_text": "Winding overheating", "robot_ts": 1700000000, "seen_at": 1763380000.5}
```

- **`null` quer dizer desconhecido, nunca "sem erros".** É o valor até a primeira mensagem `errors` ou `add_error` da conexão e depois de uma queda. Não trate `null` como robô saudável.
- `[]` só depois de uma fotografia `errors` vazia ou de um `rm_error` que esvaziou a lista.
- `code_hex`: hex maiúsculo, sem `0x` e sem zeros à esquerda. `code_text`/`source_text`: textos da lib, ou os fallbacks `"{source}-{code_hex}"` / `"{source}"`.
- `robot_ts`: timestamp cru do robô (relógio não confirmado). `seen_at`: Unix da api quando o erro entrou na lista.

## Sequência

1. **Ao aceitar:** `connection`; depois o valor atual de cada seção não nula, nesta ordem: `battery`, `imu`, `motion`, `motors`, `body_temperature_c`, `settings`; depois `audio_player` (se já chegou) e `speaker` (estado atual do alto-falante); depois `errors` (pode ser `null`).
2. **A cada mensagem do robô:** um frame por seção que ela alimenta (`rt/lf/lowstate` → `battery`, `motors`, `body_temperature_c`; `rt/sportmodestate` → `imu`, `motion`; `rt/multiplestate` → `settings`).
3. **A cada mudança da lista de erros:** `errors`.
4. **Na queda** (cada transição para fora de `connected`): `connection` e `errors: null`. As seções mantêm o último valor no `/status` (com a idade em `*_age_s`) e não são reenviadas.
5. **Na volta a `connected`:** `connection`; as seções seguem com as mensagens novas.
6. O cliente não precisa enviar nada; o que ele enviar é ignorado.

## Taxa e filas

- **Seções:** por cliente e por tópico, no máximo `GO2_STATE_MAX_HZ` frames por segundo (padrão 10; `0` = sem teto). Acima disso, o frame retido é o mais recente e sai quando a janela fecha, mesmo que o tópico pare de chegar. Cliente lento: um item pendente por tópico de seção; o mais recente substitui o pendente.
- **`connection`, `errors` e `speaker`:** caminho próprio, **sem descarte e sem teto**, na ordem em que aconteceram (no aceite, o `speaker` segue a ordem acima).
- A ordem relativa entre todos os frames é a de entrada na fila do cliente.
- Um cliente lento não atrasa os outros nem o robô.

## Métrica (log da api, não vai ao cliente)

Com pelo menos um cliente, a cada 1 s, linha INFO `state_metrics {json}`: `window_s`; `received` e `rate_hz` por origem (`low_state`, `sport_state`, `multiple_state`, `errors`); `clients`: `[{"sent", "dropped"}]` por cliente, na janela.

## Códigos de fechamento

| Código | Motivo | Quando | O que o cliente faz |
|---|---|---|---|
| `1013` | `max_clients` | Já há `GO2_STATE_MAX_CLIENTS` clientes (padrão 4), ou o limite é `0` | Tentar mais tarde |
| `1001` | `shutdown` | A api está desligando | Reconectar quando ela voltar |

## Tópicos futuros

Specs posteriores podem acrescentar tópicos neste stream, no mesmo envelope. Um cliente deve ignorar `topic` desconhecido.
