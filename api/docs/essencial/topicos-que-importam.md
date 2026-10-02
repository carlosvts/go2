# Tópicos que importam

**Em uma frase:** a lib conhece dezenas de tópicos, mas o projeto usa (ou vai usar) só estes.

| Nome na lib (`RTC_TOPIC[...]`) | Tópico | Direção | O que é | Uso |
|---|---|---|---|---|
| `SPORT_MOD` | `rt/api/sport/request` | → robô | Comandos de postura, movimento e gestos | ✅ todos os `/commands/*` |
| `SPORT_MOD_STATE` | `rt/sportmodestate` | ← robô | Modo atual, posição, velocidade | ✅ `/status` · 🔜 `/ws/telemetry` |
| `LOW_STATE` | `rt/lf/lowstate` | ← robô | IMU, motores, bateria (baixa frequência, o `lf`) | ✅ `/status` · 🔜 `/ws/telemetry` |
| `ULIDAR_ARRAY` | `rt/utlidar/voxel_map_compressed` | ← robô | LiDAR comprimido | 🔜 `/ws/lidar` |
| `VUI` | `rt/api/vui/request` | → robô | Volume, brilho, LED | 🔜 `/device/*` |
| `AUDIO_HUB_REQ` | `rt/api/audiohub/request` | → robô | Biblioteca de áudio do robô | 🔜 `/audio/*` |
| `OBSTACLES_AVOID` | `rt/api/obstacles_avoid/request` | → robô | Desvio de obstáculo | ⏸ `/safety/*` |

O vídeo **não** é um tópico: chega como track WebRTC separada.

## Pegadinha

O formato exato do payload de `lowstate` e `sportmodestate` ainda não foi fixado. Por isso o `GET /status?raw=true` devolve o payload cru, para a validação com o robô ligado.

## Mais detalhes

[`dossie_go2.md`](../dossie_go2.md) §12 · [`arquitetura_go2_api.md`](../arquitetura_go2_api.md) §4

## Termos desta ficha

- **Tópico**: Nome de um canal de mensagens (ex.: `rt/api/sport/request`).
- **IMU**: *Inertial Measurement Unit*: sensor de orientação e aceleração (inclinação, giro).
- **`lf`**: *Low frequency* (baixa frequência): versão do tópico que manda menos mensagens por segundo.
- **LiDAR**: *Light Detection and Ranging*: sensor que mede distâncias com laser.
- **VUI**: Nome que a Unitree dá ao serviço de volume, brilho e LED do Go2 (o significado da sigla não está documentado na lib).
- **Track**: Fluxo de mídia (vídeo ou áudio) dentro da conexão WebRTC.
- **Payload**: O conteúdo útil de uma mensagem (os dados), sem o cabeçalho.
- **Endpoint**: Um endereço da API que aceita pedidos (ex.: `POST /commands/move`).
