# Contrato: `/ws/lidar` (api)

Stream da nuvem de pontos do LiDAR do Go2. Comportamento e critérios em [`F-001`](../features/F-001-ws-lidar.md). O OpenAPI não descreve WebSocket: este arquivo é a fonte, e o CI **não** o confere.

| | |
|---|---|
| Dono | api |
| Consumidores | `api/scripts/ws_lidar_client.py` (visualização/debug). O server ainda não. |
| Rota | `GET /ws/lidar` (upgrade para WebSocket), sem autenticação |
| Processo | Um só (`uvicorn` sem `--workers`): `seq` e o limite de clientes valem por processo |

## Sequência

1. A api aceita o upgrade e, logo depois, envia **um frame de texto** com o estado da conexão com o robô.
2. A cada mudança de estado, envia outro frame de texto. Frames de texto nunca são descartados.
3. Com o robô `connected`, envia um **frame binário** por mensagem de LiDAR decodificada. Frames binários podem ser descartados (fila curta por cliente); o descarte aparece como buraco no `seq`.
4. O cliente não precisa enviar nada; o que ele enviar é ignorado.

## Frame de texto

```json
{"topic": "connection", "ts": 1763380000.123, "data": {"state": "connected"}}
```

`state`: `connected` | `disconnected` | `reconnecting`. `ts`: Unix, segundos, no envio pela api. Fora de `connected` não há frames binários, mas o WebSocket continua aberto.

## Frame binário (versão 1)

Little-endian, cabeçalho de 40 bytes (corpo alinhado em 8: `Float32Array(buf, 40)` funciona no navegador).

| Offset | Tipo | Campo | Significado |
|---|---|---|---|
| 0 | u8 | `version` | `1`. Versão desconhecida: descarte o frame. |
| 1 | u8 | `flags` | `0` (reservado) |
| 2 | u16 | `header_len` | `40`. O corpo começa aqui. |
| 4 | u32 | `seq` | +1 por mensagem do robô recebida pela api; comum aos clientes; volta a 0 após 2³²−1 e quando a api reinicia |
| 8 | f64 | `ts` | Chegada da mensagem na api (Unix, s). Não é o instante da medição. |
| 16 | u32 | `n_points` | Pontos no corpo (pode ser 0) |
| 20 | f32 | `resolution` | Lado do voxel em metros, copiado do robô |
| 24 | f32×3 | `origin` | Origem do grid (x, y, z), copiada do robô |
| 36 | u32 | `reserved` | `0` |
| 40 | f32×3×N | `points` | `(x, y, z)` em metros, `resolution` e `origin` já aplicados |

Tamanho: `40 + 12 × n_points`. O referencial dos pontos ainda não foi verificado no robô (F-001, H1).

```python
import numpy as np
points = np.frombuffer(frame, "<f4", offset=40).reshape(-1, 3)
```

## Códigos de fechamento

| Código | Motivo | Quando | O que o cliente faz |
|---|---|---|---|
| `1013` | `max_clients` | Já há `GO2_LIDAR_MAX_CLIENTS` clientes (padrão 1), ou o limite é `0` | Tentar mais tarde |
| `1011` | `lidar_unavailable` | A ativação do LiDAR no robô falhou (timeout, resposta não `ok` ou erro). A api não tenta de novo sozinha. | Reconectar dispara uma nova tentativa |
| `1001` | `shutdown` | A api está desligando | Reconectar quando ela voltar |
