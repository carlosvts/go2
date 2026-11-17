# Contrato: `/ws/telemetry` (api)

Telemetria do LiDAR do Go2. Comportamento e critérios em [`F-002`](../features/F-002-ws-telemetry.md). O OpenAPI não descreve WebSocket: este arquivo é a fonte, e o CI **não** o confere.

| | |
|---|---|
| Dono | api |
| Consumidores | `api/scripts/record_lidar.py` (gravação) e o visualizador. O server ainda não. |
| Rota | `GET /ws/telemetry` (upgrade para WebSocket), sem autenticação |
| Processo | Um só (`uvicorn` sem `--workers`) |
| Ativação | Um cliente desta rota sozinho liga e decodifica o LiDAR no robô (compartilhado com [`/ws/lidar`](ws-lidar.md)) e assina `rt/utlidar/robot_pose` e `rt/utlidar/lidar_state` |

## Frames

Só texto, JSON estrito (sem `NaN`/`Infinity`), no envelope:

```json
{"topic": "<tópico>", "ts": 1763380000.123, "data": { ... }}
```

`ts`: Unix, segundos, quando a api produziu ou recebeu o dado.

| `topic` | Quando | `data` |
|---|---|---|
| `connection` | ao aceitar (sempre o primeiro frame) e a cada transição; nunca descartado | `{"state": "connected" \| "disconnected" \| "reconnecting"}` |
| `lidar_metrics` | a cada 1 s, mesmo sem LiDAR ativo | ver abaixo |
| `lidar_pose` | a cada mensagem de `rt/utlidar/robot_pose` | payload cru do robô, convertido |
| `lidar_state` | a cada mensagem de `rt/utlidar/lidar_state` | payload cru do robô, convertido |

**Conversão dos payloads crus** (recursiva). Nenhum formato do robô foi verificado; a api não interpreta nada.

| No robô | No JSON |
|---|---|
| `bytes` | `{"base64": "<...>"}` |
| `NaN`, `+Inf`, `-Inf` | `{"nonfinite": "nan" \| "inf" \| "-inf"}` |
| escalar/array do numpy | número/lista |
| chave não string, tupla | string, lista |
| outro tipo | `{"unserializable": "<tipo>"}` |

## `lidar_metrics`

Janela global de 1 s; estatísticas `{min, mean, max}`, `null` sem amostra. Mede **a api**, não o sensor.

| Campo | Significado |
|---|---|
| `window_s` | Duração real da janela (s) |
| `active` | LiDAR assinado no robô ao fim da janela |
| `last_error` | `null` ou `"activation_failed"` |
| `received` | Mensagens de LiDAR que chegaram à api (inclui malformadas) |
| `rate_hz` | `received / window_s` (`null` se a janela tiver duração 0) |
| `interval_ms` | Intervalo entre chegadas; zera em desativação e reconexão |
| `seq` | `{first, last}` atribuídos na janela (u32; pode dar a volta) |
| `compressed_bytes`, `src_size` | Tamanho comprimido e descomprimido declarado (mensagens válidas) |
| `n_points` | Pontos por mensagem decodificada |
| `decode_ms` | Decodificação + montagem do frame, tempo de parede na thread do worker |
| `pipeline_ms` | Do callback (mensagem já desmontada pela lib) ao frame pronto; sem o envio |
| `resolution`, `origin` | Da última mensagem válida da janela |
| `decoded` | Mensagens decodificadas |
| `dropped_decode_queue` | Descartadas antes do decoder |
| `dropped_lidar_clients` | Frames descartados nas filas de `/ws/lidar` (soma) |
| `malformed`, `decode_errors` | Mensagens malformadas, falhas de decodificação |
| `clients` | `{"lidar": N, "telemetry": M}` |
| `dropped` | **Deste cliente:** itens perdidos na fila dele desde o último `lidar_metrics` entregue |

## Fila do cliente

Uma fila por tópico, de `GO2_TELEMETRY_CLIENT_QUEUE` itens (padrão 16). Cheia, a api descarta o mais antigo daquele tópico e conta em `dropped`. `connection` não entra nessa fila.

## Códigos de fechamento

| Código | Motivo | Quando |
|---|---|---|
| `1013` | `max_clients` | Já há `GO2_TELEMETRY_MAX_CLIENTS` clientes (padrão 1), ou o limite é `0` |
| `1001` | `shutdown` | A api está desligando |

Falha na ativação do LiDAR **não** fecha esta rota: `lidar_metrics` passa a vir com `active: false` e `last_error: "activation_failed"`. Um cliente novo, em qualquer das duas rotas, dispara outra tentativa.
