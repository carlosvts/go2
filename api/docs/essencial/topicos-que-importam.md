# Tópicos que importam

**Em uma frase:** a lib conhece dezenas de tópicos, mas a api usa só estes. A lista completa, com o que ficou de fora e por quê, está em [`cobertura_lib.md`](../cobertura_lib.md).

| Nome na lib (`RTC_TOPIC[...]`) | Tópico | Direção | O que é | Uso |
|---|---|---|---|---|
| `SPORT_MOD` | `rt/api/sport/request` | → robô | Comandos de postura, movimento e gestos | ✅ todos os `/commands/*` |
| `SPORT_MOD_STATE` | `rt/sportmodestate` | ← robô | Modo atual, posição, velocidade | ✅ `/status` (`imu`, `motion`) · `/ws/state` |
| `LOW_STATE` | `rt/lf/lowstate` | ← robô | IMU, motores, bateria (baixa frequência, o `lf`) | ✅ `/status` (`battery`, `motors`) · `/ws/state` |
| `MULTIPLE_STATE` | `rt/multiplestate` | ← robô | Brilho, volume, altura, nível de velocidade, desvio | ✅ `/status` (`settings`) · `/ws/state` |
| `ULIDAR_ARRAY` | `rt/utlidar/voxel_map_compressed` | ← robô | LiDAR comprimido | ✅ `/ws/lidar` · métricas no `/ws/telemetry` |
| `ULIDAR_STATE`, `ROBOTODOM` | `rt/utlidar/lidar_state`, `rt/utlidar/robot_pose` | ← robô | Estado do sensor e pose do robô | ✅ `/ws/telemetry` |
| `VUI` | `rt/api/vui/request` | → robô | Volume, brilho, LED (api_ids só no exemplo da lib) | ✅ `/device/*` |
| `AUDIO_HUB_REQ` | `rt/api/audiohub/request` | → robô | Biblioteca de áudio do robô | ✅ `/audio/*` |
| `AUDIO_HUB_PLAY_STATE` | `rt/audiohub/player/state` | ← robô | Estado do player do robô | ✅ `GET /audio/player` · `/ws/state` |
| `OBSTACLES_AVOID` | `rt/api/obstacles_avoid/request` | → robô | Desvio de obstáculo | ✅ `/safety/obstacle-avoidance` |

O vídeo **não** é um tópico: chega como track WebRTC separada (`/ws/video`). O áudio do `/speaker/play` também vai por track, no sentido contrário. Os erros do robô (`errors`, `add_error`, `rm_error`) são tipos de mensagem do data channel, não tópicos.

## Pegadinha

Os nomes dos campos vêm dos exemplos da lib e ainda não foram conferidos no robô. Por isso o `GET /status?raw=true` devolve também os payloads crus, para a validação com o robô ligado.

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
