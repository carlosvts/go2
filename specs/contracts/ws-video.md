# Contrato: `/ws/video` (api)

Stream da câmera frontal do Go2 em JPEG. Comportamento e critérios em [`F-003`](../features/F-003-ws-video.md). O OpenAPI não descreve WebSocket: este arquivo é a fonte, e o CI **não** o confere.

| | |
|---|---|
| Dono | api |
| Consumidores | `api/scripts/video_viewer.html` (visualização no navegador), `api/scripts/ws_video_client.py` (diagnóstico no terminal) e `api/scripts/record_video.py` (gravação). O server ainda não. |
| Ativação | A câmera é ligada (`switchVideoChannel(True)`) com pelo menos 1 cliente e o robô `connected`, e desligada quando sai o último. O `disableTrafficSaving` é comum com [`/ws/lidar`](ws-lidar.md) e [`/ws/telemetry`](ws-telemetry.md). |
| Rota | `GET /ws/video` (upgrade para WebSocket), sem autenticação |
| Processo | Um só (`uvicorn` sem `--workers`): `seq` e o limite de clientes valem por processo |
| Uso | Avise as pessoas no lab antes de ligar o vídeo e não grave quem não foi avisado (F-003, Impacto HRI). |

## Sequência

1. A api aceita o upgrade e envia um frame de texto `connection` com o estado da conexão com o robô; com a câmera já ligada, também o estado `video` atual.
2. A cada mudança, envia outro frame de texto (`connection` ou `video`). Frames de texto nunca são descartados.
3. Com a câmera ligada, envia um **frame binário** por quadro codificado. Frames binários podem ser descartados (filas curtas); o descarte aparece como buraco no `seq`.
4. O cliente não precisa enviar nada; o que ele enviar é ignorado.

## Frames de texto

```json
{"topic": "connection", "ts": 1763380000.123, "data": {"state": "connected"}}
{"topic": "video", "ts": 1763380000.456, "data": {"state": "streaming"}}
```

- `connection.state`: `connected` | `disconnected` | `reconnecting`. Fora de `connected` não há frames binários nem `video`, mas o WebSocket continua aberto.
- `video.state`, só com a câmera ligada:
  - `starting`: a api pediu a câmera (o comando não tem resposta) e ainda não chegou quadro;
  - `streaming`: chegou quadro;
  - `stalled`: `GO2_VIDEO_STALL_S` (padrão 3 s) sem quadro. O WebSocket continua aberto; volta a `streaming` no próximo quadro. É o retorno de câmera que não respondeu: reconectar o cliente tenta de novo.
- `ts`: Unix, segundos, no envio pela api.

## Frame binário (versão 1)

Little-endian, cabeçalho de 32 bytes, seguido do JPEG.

| Offset | Tipo | Campo | Significado |
|---|---|---|---|
| 0 | u8 | `version` | `1`. Versão desconhecida: descarte o frame. |
| 1 | u8 | `flags` | `0` (reservado) |
| 2 | u16 | `header_len` | `32`. O JPEG começa aqui. |
| 4 | u32 | `seq` | +1 por quadro admitido pela api (depois do teto de taxa); comum aos clientes; volta a 0 após 2³²−1 e quando a api reinicia |
| 8 | f64 | `ts` | Leitura do quadro pela api (Unix, s). Não é o instante da captura. |
| 16 | u16 | `width` | Largura em pixels |
| 18 | u16 | `height` | Altura em pixels |
| 20 | u32 | `jpeg_len` | Bytes do JPEG |
| 24 | f64 | `media_time` | Tempo do quadro no relógio RTP do robô (s, origem arbitrária), ou `NaN`. Para taxa e intervalo, não para comparar com `ts`. |
| 32 | bytes | `jpeg` | JPEG baseline, cor, na resolução original |

Tamanho: `header_len + jpeg_len`.

```python
import cv2, numpy as np
image = cv2.imdecode(np.frombuffer(frame, np.uint8, offset=32), cv2.IMREAD_COLOR)
```

```js
const blob = new Blob([new Uint8Array(buf, 32, jpegLen)], {type: "image/jpeg"});
```

## Códigos de fechamento

| Código | Motivo | Quando | O que o cliente faz |
|---|---|---|---|
| `1013` | `max_clients` | Já há `GO2_VIDEO_MAX_CLIENTS` clientes (padrão 2), ou o limite é `0` | Tentar mais tarde |
| `1011` | `video_unavailable` | `disableTrafficSaving(True)` falhou ou `switchVideoChannel(True)` lançou erro. A api não tenta de novo sozinha. | Reconectar dispara uma nova tentativa |
| `1001` | `shutdown` | A api está desligando | Reconectar quando ela voltar |
