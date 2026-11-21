# Cobertura da lib `unitree_webrtc_connect` pela go2-api (Go2)

Levantamento de 2026-11-21. Base para a spec que vai implementar o que falta.

Fontes:
- **lib**: pacote instalado, versão **2.2.0** (`constants.py`, `webrtc_datachannel.py`, `webrtc_audiohub.py`, `webrtc_audio.py`, `webrtc_video.py`).
- **ex.**: exemplos de `examples/go2/` no repositório `legion1581/unitree_webrtc_connect`, branch `master` (último push 2026-08-17). Payloads tirados do exemplo e **não vistos no robô** estão marcados assim.
- **api**: rotas da `go2-api` na branch `feat/ws-video` (`5c3d971`).

Fora do escopo do Go2: tudo de humanoide (`LOCO_API`, `R1_FSM`, `ARM_ACTION`, `ARM_REQUEST`, `BMS_STATE`, `SECONDARY_IMU`, `MAIN_BOARD_STATE`). Não entra na tabela.

Legenda: ✅ exposto · 🟡 exposto em parte · ❌ não exposto · ⛔ restrito por regra do `AGENTS.md` (só com spec, teste da equipe um a um ou decisão em `specs/decisions/`).

"Verificado no robô" quer dizer que alguém da equipe viu funcionar. Exposto na api não implica verificado.

## 1. Comandos esportivos (`SPORT_MOD`, `rt/api/sport/request`, `SPORT_CMD`)

| Comando (api_id) | O que faz | Payload | Fonte | Na api |
|---|---|---|---|---|
| `Damp` 1001 | Desliga os motores (o robô cai) | — | lib | ✅ `POST /commands/posture` `damp` (só frase exata no server) |
| `BalanceStand` 1002 | De pé, em equilíbrio; pré-requisito do `move` | — | lib | ✅ `posture` |
| `StopMove` 1003 | Para o movimento | — | lib | ✅ `POST /commands/stop` |
| `StandUp` 1004 / `StandDown` 1005 | Levanta / deita | — | lib | ✅ `posture` |
| `RecoveryStand` 1006 | Levanta depois de queda | — | lib | ✅ `posture` |
| `Sit` 1009 / `RiseSit` 1010 | Senta / levanta do sentado | — | lib | ✅ `posture` |
| `Move` 1008 | Velocidade `x, y, z` (vx, vy, vyaw) | `{"x","y","z"}` | lib, ex. | ✅ `POST /commands/move` (reenvio a `GO2_MOVE_RATE_HZ`) |
| `SpeedLevel` 1015 | Nível de velocidade | `{"data": n}` (a validar) | lib, ex. MCF | ✅ `PUT /commands/speed` |
| `GetSpeedLevel` 1026 | Lê o nível | — | lib | ✅ `GET /commands/speed` |
| `Hello` 1016, `Stretch` 1017, `Content` 1020, `Dance1` 1022, `Dance2` 1023, `Scrape` 1029, `Pose` 1028, `WiggleHips` 1033, `FingerHeart` 1036 | Gestos de baixo risco | `Pose` usa `{"data": true}` no ex. MCF | lib, ex. | ✅ `POST /commands/gesture` |
| `Euler` 1007 | Inclina o corpo parado (roll, pitch, yaw) | `{"x","y","z"}` (ex. MCF) | lib, ex. MCF | ❌ |
| `BodyHeight` 1013 / `GetBodyHeight` 1024 | Altura do corpo: define / lê | não visto | lib | ❌ |
| `FootRaiseHeight` 1014 / `GetFootRaiseHeight` 1025 | Altura do passo: define / lê | não visto | lib | ❌ |
| `SwitchGait` 1011 | Troca a marcha | não visto | lib | ❌ |
| `ContinuousGait` 1019 | Marcha contínua liga/desliga | `{"data": bool}` (ex. MCF) | lib, ex. MCF | ❌ |
| `EconomicGait` 1035 | Marcha econômica | não visto | lib | ❌ |
| `SwitchJoystick` 1027 | Liga/desliga o controle remoto físico | `{"data": bool}` (ex. MCF) | lib, ex. MCF | ❌ |
| `GetState` 1034 | Estado do modo esporte (request) | — | lib | ❌ (o `/status` usa o tópico `SPORT_MOD_STATE`) |
| `Trigger` 1012 | Não documentado | não visto | lib | ❌ |
| `TrajectoryFollow` 1018 | Seguir trajetória | não visto | lib | ❌ |
| `FreeWalk` / `LeadFollow` 1045 | Mesmo número na lib (pegadinha) | não visto | lib | ❌ |
| `StandOut` 1039 | Postura de pé nas patas traseiras; o ex. troca para o modo `ai` antes | `{"data": bool}` | lib, ex. | ⛔ (modo bípede desativado de propósito) |
| `Wallow` 1021 | Rolar no chão | — | lib | ⛔ (teste da equipe antes) |
| `FrontJump` 1031, `FrontPounce` 1032 | Pulo / bote | — | lib | ⛔ |
| `FrontFlip` 1030, `LeftFlip` 1042, `RightFlip` 1043, `BackFlip` 1044 | Mortais | `{"data": true}` no ex. | lib, ex. | ⛔ (risco de queda; previsto `POST /commands/trick` com `confirm`, carlosvts/go2-api#1) |
| `Handstand` 1301, `CrossStep` 1302, `OnesidedStep` 1303, `Bound` 1304, `MoonWalk` 1305 | Truques | não visto | lib | ⛔ |
| `Standup` 1050, `CrossWalk` 1051 | Não documentados (`Standup` ≠ `StandUp` 1004) | não visto | lib | ❌ |

## 2. Modo de movimento e MCF

| Item | O que faz | Payload | Fonte | Na api |
|---|---|---|---|---|
| `MOTION_SWITCHER` 1001 | Lê o modo atual (`normal`, `ai`, …) | resposta `{"name"}` | ex. | ❌ |
| `MOTION_SWITCHER` 1002 | Troca o modo | `{"name": "normal" \| "ai"}` | ex. | ❌ |
| `SPORT_CMD_MCF` (firmware ≥ 1.1.7) | Outro espaço de ids no mesmo tópico: `StaticWalk` 1061, `TrotRun` 1062, `EconomicGait` 1063, `FreeWalk` 2045, `FreeBound` 2046, `FreeJump` 2047, `FreeAvoid` 2048, `ClassicWalk` 2049, `BackStand` 2050, `CrossStep` 2051, `LeadFollow` 2056, `HandStand` 2044, flips 2041/2043 | por comando | lib, ex. MCF | ❌ (o robô precisa estar em MCF; fora do v1) |
| `SetAutoRecovery` 2054 / `GetAutoRecovery` 2055 | Auto-recuperação de queda (MCF) | não visto | lib | ❌ |
| `SwitchAvoidMode` 2058 | Modo de desvio (MCF) | não visto | lib | ❌ |

## 3. Desvio de obstáculo (`OBSTACLES_AVOID`) e controle remoto

| Item | O que faz | Payload | Fonte | Na api |
|---|---|---|---|---|
| `SWITCH_SET` 1001 / `SWITCH_GET` 1002 | Liga, desliga e consulta o desvio | `{"enable": bool}` | lib, ex. | ✅ `PUT/GET /safety/obstacle-avoidance` |
| `MOVE` 1003 | Andar com o desvio ativo (sem resposta) | `{"x","y","yaw","mode": 0}` | lib | ❌ |
| `USE_REMOTE_COMMAND_FROM_API` 1004 | Faz o desvio aceitar comando vindo da API | `{"is_remote_commands_from_api": bool}` | lib | ❌ |
| `WIRELESS_CONTROLLER` (`rt/wirelesscontroller`) | Emula o joystick (`lx, ly, rx, ry, keys`), ~50 Hz | publicação sem resposta | ex. | ❌ |

No teste da equipe, o desvio **para** antes de bater e não contorna (`AGENTS.md`). Observação do humano (2026-11-21): com o desvio ligado, o `POST /commands/move` atual (`SPORT_CMD` `Move` 1008) **para antes de bater** numa caixa. Por isso `MOVE` 1003 e `USE_REMOTE_COMMAND_FROM_API` 1004 ficam fora: o `move` atual já passa pelo desvio.

## 4. Dispositivo: lanterna, LED, volume (`VUI`, `rt/api/vui/request`)

Os api_ids **não estão nas constantes da lib**: vêm do exemplo `vui.py`, não vistos no robô.

| api_id | O que faz | Payload (ex.) | Na api |
|---|---|---|---|
| 1003 | Define o volume | `{"volume": 0–10}` | ✅ `PUT /device/volume` (F-005; só software testado) |
| 1004 | Lê o volume | resposta `{"volume"}` | ✅ `GET /device/volume` (F-005; só software testado) |
| 1005 | Define o brilho da lanterna | `{"brightness": 0–10}` | ✅ `PUT /device/brightness` (F-005; só software testado) |
| 1006 | Lê o brilho | resposta `{"brightness"}` | ✅ `GET /device/brightness` (F-005; só software testado) |
| 1007 | Cor do LED por um tempo, com pisca opcional | `{"color", "time", "flash_cycle"?}`; cores `white, red, yellow, blue, green, cyan, purple` (`VUI_COLOR`); `flash_cycle` entre 499 e `time*1000` ms | ✅ `PUT /device/led` (F-005; só software testado) |

Implementado na F-005 (carlosvts/go2-api#3), sem teste no robô. É a rota de que depende o sinal de "câmera ligada" da F-003.

## 5. Áudio

| Item | O que faz | Fonte | Na api |
|---|---|---|---|
| `WebRTCAudioHub.get_audio_list` (`AUDIO_API` 1001) | Lista os áudios guardados no robô | lib, ex. | ✅ `GET /audio/files` (F-006) |
| `play_by_uuid` 1002, `pause` 1003, `resume` 1004 | Toca / pausa / retoma um áudio guardado | lib, ex. | ✅ `POST /audio/files/{id}/play`, `/audio/pause`, `/audio/resume`; `POST /audio/silence` = pause + alto-falante (F-006) |
| `SELECT_PREV/NEXT_START_PLAY` 1005/1006 | Anterior / próximo (só constante, sem método) | lib | ❌ (fora do escopo da F-006) |
| `set_play_mode` 1007 / `get_play_mode` 1010 | Modo de reprodução | lib | ✅ `PUT/GET /audio/play-mode` (F-006) |
| `rename_record` 1008 / `delete_record` 1009 | Renomeia / apaga um áudio guardado | lib | ✅ `PATCH/DELETE /audio/files/{id}` (F-006) |
| `upload_audio_file` 2001 | Envia MP3/WAV ao robô (em pedaços, pelo data channel) | lib, ex. | ✅ `POST /audio/files` + `GET /audio/uploads/{id}` (F-006; protocolo copiado em `unitree.py`, com timeout por bloco; PyAV no lugar do pydub) |
| `enter_megaphone` 4001 / `upload_megaphone` 4003 / `exit_megaphone` 4002 | Modo megafone: toca um arquivo direto | lib | ❌ (fora do escopo da F-006) |
| Corpus interno 3001–3004, 5001–5003 | Falas prontas do robô (desvio, modo companhia, corpus longo); só constantes | lib | ❌ |
| `AUDIO_HUB_PLAY_STATE` (`rt/audiohub/player/state`) | Estado do player (tópico) | lib | ✅ `GET /audio/player`, cru (F-006); `/ws/state` na F-004 |
| Track de áudio de saída (`pc.addTrack(MediaPlayer(...))`) | Toca MP3 ou rádio pela conexão WebRTC, ao vivo | ex. | ❌ |
| Microfone do robô (`switchAudioChannel` + track de áudio) | Recebe o áudio do robô (48 kHz) | lib, ex. | ❌ |

Previsto em carlosvts/go2-api#2. HRI: som do robô pode ser captado pelo microfone da TV Box e virar comando (eco).

## 6. Câmera

| Item | O que faz | Fonte | Na api |
|---|---|---|---|
| Track de vídeo (`switchVideoChannel` + `add_track_callback`) | Stream da câmera frontal | lib, ex. | ✅ `/ws/video` (F-003; só software testado) |
| `FRONT_PHOTO_REQ` (`rt/api/videohub/request`) | Pedir foto ao robô | lib (só tópico; api_id não visto) | ❌ |

## 7. Estado e sensores (tópicos)

| Tópico | Conteúdo | Fonte | Na api |
|---|---|---|---|
| `LOW_STATE` (`rt/lf/lowstate`) | Bateria, IMU, motores, temperaturas | lib, ex. | 🟡 `GET /status` (bateria; resto em `?raw=true`) |
| `SPORT_MOD_STATE` (`rt/sportmodestate`) | Modo, pose, velocidade | lib, ex. | 🟡 `GET /status` (modo; resto em `?raw=true`) |
| `LF_SPORT_MOD_STATE` (`rt/lf/sportmodestate`) | Versão "low frequency" do anterior | lib | ❌ |
| `MULTIPLE_STATE` (`rt/multiplestate`) | `bodyHeight`, `brightness`, `footRaiseHeight`, `obstaclesAvoidSwitch`, `speedLevel`, `uwbSwitch`, `volume` | lib, ex. | ❌ (devolveria a leitura de vários `GET` sem request) |
| `SELF_TEST` (`rt/selftest`) | Autoteste | lib | ❌ |
| `SERVICE_STATE` (`rt/servicestate`) | Serviços do robô | lib | ❌ |
| Erros (`DATA_CHANNEL_TYPE` `errors`/`add_error`/`rm_error`, `app_error_messages`) | Falhas de motor, bateria, ventoinha, radar, superaquecimento | lib | ❌ |
| `WIRELESS_CONTROLLER` (leitura) | Estado do controle remoto | lib | ❌ |
| `UWB_STATE` / `UWB_REQ` | UWB (seguir a pessoa com o controle) | lib | ❌ |
| `GAS_SENSOR` / `GAS_SENSOR_REQ` | Sensor de gás (acessório) | lib | ❌ |

## 8. LiDAR e mapeamento

| Item | Fonte | Na api |
|---|---|---|
| `ULIDAR_ARRAY` (voxel comprimido, decoder `native`) | lib, ex. | ✅ `/ws/lidar` (F-001) |
| `ULIDAR_STATE`, `ROBOTODOM` | lib | ✅ `/ws/telemetry` (F-002) |
| `ULIDAR_SWITCH` (`rt/utlidar/switch`, `"on"`/`"off"`) | lib | ❌ (F-001 só se o H1 mostrar que é preciso) |
| `ULIDAR` (não comprimido), decoder `libvoxel` (malha) | lib | ❌ (fora de escopo do F-001) |
| `GRID_MAP` (`rt/mapping/grid_map`) | lib | ❌ |
| SLAM/navegação: `SLAM_*`, `LIDAR_MAPPING_*`, `LIDAR_LOCALIZATION_*`, `LIDAR_NAVIGATION_GLOBAL_PATH` | lib | ❌ (fora do v1) |

## 9. Baixo nível e outros

| Item | O que faz | Na api |
|---|---|---|
| `LOW_CMD` (`rt/lowcmd`) | Controle direto de cada motor | ❌ ⛔ (risco físico alto) |
| `BASH_REQ` (`rt/api/bashrunner/request`) | Roda comando de shell no robô | ❌ ⛔ (sem autenticação na api; fora de escopo) |
| `GPT_FEEDBACK`, `ASSISTANT_RECORDER` | Assistente de voz da Unitree | ❌ |
| `PROGRAMMING_ACTUATOR_CMD` | Programação gráfica | ❌ |
| `disableTrafficSaving` | Link sem economia de tráfego | ✅ interno (refcount de LiDAR/telemetria/vídeo) |

## 10. Conexão

| Item | Na api |
|---|---|
| `LocalSTA` (IP ou serial por multicast), `LocalAP` | ✅ |
| `Remote` (nuvem Unitree, conta e internet) | ❌ (fora de propósito, `app/config.py`) |
| `aes_128_key` (firmware ≥ 1.1.15) | 🟡 configurável, não repassado (firmware atual não exige) |

## Resumo

| Grupo | Na lib/exemplos | Na api hoje |
|---|---|---|
| Postura, `move`, `stop`, velocidade | 12 comandos | ✅ todos |
| Gestos de baixo risco | 9 | ✅ todos |
| Ajuste de corpo e marcha (`Euler`, `BodyHeight`, `FootRaiseHeight`, gaits, `SwitchJoystick`) | ~10 | ❌ |
| Truques (flips, pulos, handstand, `Wallow`, `StandOut`…) | ~16 | ⛔ |
| Modo de movimento (`MOTION_SWITCHER`) e MCF | 2 + ~20 | ❌ |
| Desvio de obstáculo | 4 api_ids + joystick | 🟡 2 de 4 (os outros 2 não fazem falta: o `move` atual já é filtrado) |
| Lanterna, LED, volume (VUI) | 5 api_ids | ✅ todos (F-005; só software testado) |
| Áudio (hub, megafone, track de saída, microfone) | ~15 | ❌ |
| Câmera | stream + foto | 🟡 stream (F-003) |
| Estado e sensores | ~10 tópicos | 🟡 2 tópicos no `/status` |
| LiDAR | 4 itens + SLAM | 🟡 3 de 4; SLAM fora |
| Baixo nível (`LOW_CMD`, `BASH_REQ`) | 2 | ⛔ |
