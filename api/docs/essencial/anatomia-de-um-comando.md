# Anatomia de um comando

**Em uma frase:** um comando é uma mensagem JSON publicada no tópico `rt/api/sport/request`, com o `api_id` do comando e um `parameter` que é **string** JSON.

```json
{
  "type": "req",
  "topic": "rt/api/sport/request",
  "data": {
    "header": { "identity": { "id": 1759300000123, "api_id": 1008 } },
    "parameter": "{\"x\": 0.3, \"y\": 0.0, \"z\": 0.5}"
  }
}
```

| Campo | Regra |
|---|---|
| `type` | `"req"`. Com `"msg"` (o padrão da lib), o comando **não executa**. |
| `header.identity.id` | Número do pedido. O robô o devolve na resposta, para dizer a qual pedido está respondendo. |
| `header.identity.api_id` | O comando (`SPORT_CMD["Move"]` = 1008, `StandUp` = 1004...). |
| `parameter` | Sempre presente. String vazia `""` sem argumento, ou JSON **serializado como string**. |

## Na prática

Quem monta isso é `RobotConnection._build_request` (`app/robot.py`). Os endpoints só escolhem o `api_id` e o parâmetro.

## Pegadinha

No `Move`, o yaw vai no campo **`z`**, não em `yaw`. Com `yaw`, o robô ignora o comando.

## Mais detalhes

`app/robot.py` (`_build_request`, `send_sport`) · [`lib_unitree_webrtc_connect.md`](../lib_unitree_webrtc_connect.md) §3
