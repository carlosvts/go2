---
id: F-004
titulo: Estado e sensores do robô (/status ampliado e /ws/state)
tipo: comportamento
status: em-implementacao
servicos: [api]
verificacao: testado-software
verificado-em: null
depende-de: [F-003]            # reaproveita a fila, o cliente e o laço de stream de app/robot/streams.py
---

# F-004 — Estado e sensores do robô (`/status` ampliado e `/ws/state`)

## Objetivo
Expor tudo o que o Go2 publica sobre o próprio estado: bateria completa, IMU, motores, temperaturas, movimento, configurações (brilho, volume, nível de velocidade, desvio) e os erros ativos. Hoje o `GET /status` só devolve bateria e modo. O consumidor é quem clonar a api (equipe do lab e outros projetos), não um serviço específico.

Base: `api/docs/cobertura_lib.md` §7. Os nomes dos campos vêm dos exemplos `lowstate.py`, `sportmodestate.py` e `multiplestate.py` do repositório `legion1581/unitree_webrtc_connect` e **não foram vistos no robô**.

## Comportamento

### Fontes
- **Tópicos** (assinados a cada `connect()`, como hoje): `LOW_STATE` e `SPORT_MOD_STATE`, já assinados, e `MULTIPLE_STATE` (`rt/multiplestate`), **novo**. O `data` do `MULTIPLE_STATE` chega como string JSON (exemplo); a api decodifica. A lib guarda **um callback por tópico** (pegadinha do F-001): o `/ws/state` lê do mesmo cache do `/status`, sem assinar de novo.
- **Erros do data channel** (tipos `errors`, `add_error` e `rm_error`). A lib 2.2.0 só os imprime: `WebRTCDataChannel.handle_response` chama `msgs/error_handler.handle_error`, sem callback. A api captura sem patch na lib, em `app/robot/unitree.py`:
  - instala um gancho no `datachannel` **na criação dele, dentro do `connect()`**, como o `VideoHookedConnection` da F-003 faz com `video`; assim a fotografia inicial de erros, se vier logo depois da validação, não se perde;
  - o gancho chama o `handle_response` original e depois entrega a mensagem à api;
  - exceção no código da api é registrada em log e não chega à lib.

### Seções
Extraídas sob demanda (no `GET /status`) e, com cliente no `/ws/state`, uma vez por mensagem recebida. Tipos esperados são `inferido`.

| Seção | Origem | Campos na api ← campo no exemplo (tipo esperado) |
|---|---|---|
| `battery` | `LOW_STATE` | `percent` ← mesma extração do `battery_percent` atual (int); `voltage_v` ← `power_v` (float); `current_ma` ← `bms_state.current` (int); `cycles` ← `bms_state.cycle` (int); `temperatures_c.bq` / `.mcu` ← `bms_state.bq_ntc` / `mcu_ntc` (int) |
| `imu` | `SPORT_MOD_STATE` | `rpy` (3 floats), `quaternion` (4), `gyroscope` (3), `accelerometer` (3), `temperature` (número) ← `imu_state.*` |
| `motion` | `SPORT_MOD_STATE` | `mode` ← mesma extração do `mode` atual (int); `progress` (float); `gait_type` (int); `body_height` (float); `foot_raise_height` (float); `position` (3); `velocity` (3); `yaw_speed` (float); `range_obstacle` (lista de floats); `foot_force` (lista de números) |
| `motors` | `LOW_STATE` | lista na ordem de `motor_state`, cada item `{q (float), temperature_c (número), lost (int)}` ← `{q, temperature, lost}` |
| `body_temperature_c` | `LOW_STATE` | `temperature_ntc1` (número) |
| `settings` | `MULTIPLE_STATE` | `body_height` ← `bodyHeight`; `brightness`; `foot_raise_height` ← `footRaiseHeight`; `obstacle_avoidance` ← `obstaclesAvoidSwitch` (bool; 0/1 também viram bool); `speed_level` ← `speedLevel`; `uwb` ← `uwbSwitch` (bool); `volume` |
| `errors` | data channel | lista dos erros ativos, ou `null` (ver "Erros ativos") |

Regras de extração:
- Tópico que nunca chegou nesta execução da api: a seção é `null`.
- Campo ausente, de tipo diferente do esperado ou **não finito** (`NaN`, `±Inf`): só aquele campo vira `null`. `bool` não conta como número. O `/status` sempre responde `200`.
- Lista de tamanho diferente do esperado (os números entre parênteses): o campo vira `null`. Listas sem tamanho fixo (`motors`, `range_obstacle`, `foot_force`) aceitam qualquer tamanho; item malformado de `motors` vira `null` sem zerar a lista.
- Unidades são as dos exemplos (metros, °C, volts, mA, radianos), todas `inferido`. A api não converte nada além de renomear.
- `battery.percent` e `battery_percent` vêm da mesma extração (os três caminhos de hoje), e `motion.mode` e `mode` também: nunca divergem.
- `settings.obstacle_avoidance` é só leitura informativa. A fonte de verdade para ligar e consultar continua sendo `/safety/obstacle-avoidance`.

### Conexão que cai
- As seções **mantêm o último valor**, como o `/status` já faz com bateria e modo. A idade de cada uma aparece em `GET /status`: `low_state_age_s` e `sport_state_age_s` (existentes) e `multiple_state_age_s` (nova). O `connected: false` avisa que o dado é da conexão anterior.
- `errors` é exceção: vira `null` (desconhecido) na queda.

### `GET /status`
- Os campos atuais (`connected`, `state`, `since`, `battery_percent`, `mode`, `sport_state_age_s`, `low_state_age_s`, `raw`) **não mudam** de nome nem de significado. O `server/` usa o `/status` no health check.
- Campos novos: as seções da tabela e `multiple_state_age_s`.
- `?raw=true` passa a incluir `multiple_state` já decodificado (o JSON, não a string). Mensagens de erro cruas não entram no `raw`.

### Erros ativos
- `errors` é `null` até a primeira mensagem `errors` ou `add_error` **nesta conexão**, e volta a `null` na queda. `[]` só aparece depois de uma fotografia `errors` vazia ou de um `rm_error` que esvaziou a lista. **`null` quer dizer desconhecido, nunca "sem erros"** (decisão do humano).
- Formato das mensagens, lido no código da lib, que cita o app oficial: `[timestamp, source, code]`, com `code` inteiro. `data` pode ser um item só ou uma lista de itens.
- `errors` substitui a lista inteira; `add_error` acrescenta, sem duplicar o par `(source, code)`; `rm_error` remove o par. `rm_error` de par que não está na lista não faz nada (log DEBUG).
- Cada erro: `{"source", "source_text", "code", "code_hex", "code_text", "robot_ts", "seen_at"}`.
  - `code_hex`: hex maiúsculo, sem `0x` e sem zeros à esquerda (`integer_to_hex_string` da lib). Exemplo: 16 → `"10"`.
  - `code_text`: `app_error_messages["app_error_code_{source}_{code_hex}"]`, ou o fallback da lib `"{source}-{code_hex}"`.
  - `source_text`: `app_error_messages["app_error_source_{source}"]`, ou o fallback `"{source}"`.
  - `robot_ts`: o `timestamp` cru do robô. `seen_at`: Unix da api quando o erro entrou na lista.

### `/ws/state`
- Rota `GET /ws/state` (WebSocket), sem autenticação, no estilo dos outros streams: aceita o upgrade antes de qualquer fechamento; o cliente não envia nada.
- Só frames de texto JSON, no envelope `{"topic", "ts", "data"}`. `ts` é a chegada da mensagem de origem à api (Unix, s), como no `ws-telemetry`. Tópicos:
  - `connection`: igual aos outros streams;
  - `battery`, `imu`, `motion`, `motors`, `body_temperature_c` e `settings`: `data` é a seção do `/status`;
  - `errors`: a lista de erros ativos (ou `null`), a cada mudança dela.
- **Ao aceitar:** `connection`, depois o valor atual de cada seção que não é `null` (com o `ts` da chegada original, para o cliente saber a idade), depois `errors`.
- **Na queda:** `connection` e `errors: null`. **Na volta a `connected`:** `connection`; as seções seguem com as mensagens novas.
- **Taxa:** cada mensagem recebida do robô gera um frame por seção que ela alimenta (um `LOW_STATE` gera `battery`, `motors` e `body_temperature_c`). Por cliente e por tópico, no máximo `GO2_STATE_MAX_HZ` frames por segundo. Acima disso, o frame retido é o mais recente e **sai quando a janela fecha**, mesmo que o tópico pare de chegar. `GO2_STATE_MAX_HZ=0` = sem teto; negativo impede a api de subir.
- **Cliente lento:** um item pendente por tópico de seção; o mais recente substitui o pendente. `connection` e `errors` vão por um caminho próprio, **sem descarte e sem limite de taxa**, na ordem em que aconteceram. Um cliente lento não atrasa os outros nem o robô.
- O JSON de cada frame é montado **uma vez** e compartilhado pelos clientes.
- **Limite:** `GO2_STATE_MAX_CLIENTS` clientes; o próximo é aceito e fechado com `1013` / `max_clients`; `0` desliga a rota. `1001` / `shutdown` quando a api desliga.
- O `/ws/state` não assina nem cancela nada no robô: lê o cache que o `/status` já mantém.

### Métrica
Com pelo menos um cliente no `/ws/state`, a api registra em log (INFO), a cada 1 s, a linha `state_metrics` com:
- mensagens/s por tópico de origem (`low_state`, `sport_state`, `multiple_state`, erros);
- frames enviados e retidos/descartados por cliente.

### Configuração (`.env`)

| Variável | Padrão | Origem |
|---|---|---|
| `GO2_STATE_MAX_CLIENTS` | `4` | sugerido pelo Claude (`inferido`); leve, só texto |
| `GO2_STATE_MAX_HZ` | `10` | sugerido pelo Claude (`inferido`); a taxa real dos tópicos não foi medida |

### Contrato
- `specs/contracts/api.openapi.json` regenerado (o `/status` muda) no commit da implementação.
- `specs/contracts/ws-state.md` novo, com os tópicos, a ordem, a taxa e os códigos de fechamento; linha nova em `specs/contracts/README.md` (consumidores: clientes externos; nenhum no repo).
- O `/capabilities` não muda (decisão do humano): as rotas novas ficam documentadas no OpenAPI e no README da api.

## Critérios de aceite

| ID | Critério (observável) | Como verificar | Tipo | Verificação |
|---|---|---|---|---|
| A1 | Dados payloads de `LOW_STATE`, `SPORT_MOD_STATE` e `MULTIPLE_STATE` (este como string JSON) com os campos dos exemplos, o `GET /status` devolve cada seção renomeada conforme a tabela; os campos antigos têm os mesmos valores de antes; `battery.percent == battery_percent` e `motion.mode == mode` | teste com fake pub_sub | software | testado-software (2026-11-22 @ dc1043e) |
| A2 | Campo ausente, de tipo errado, `bool` no lugar de número, lista de tamanho errado ou `NaN` (ex.: em `imu.rpy`) deixa só aquele campo `null` e o `/status` responde `200`; item ruim de `motors` vira `null` sem zerar a lista; tópico que nunca chegou deixa a seção `null`; `MULTIPLE_STATE` que não é JSON deixa `settings` `null` e é registrado em log | teste, um caso por regra | software | testado-software (2026-11-22 @ dc1043e) |
| A3 | Usando a classe **real** `WebRTCDataChannel` da lib:<br>(a) uma fotografia `errors` entregue **durante** o `connect()` aparece no `/status`;<br>(b) `add_error` acrescenta sem duplicar; `rm_error` remove; `rm_error` de par ausente não muda nada;<br>(c) código 300/16 dá `code_hex` `"10"` e `code_text` `"Winding overheating"`; código sem texto dá o fallback;<br>(d) a lista é `null` antes da primeira mensagem e depois da queda;<br>(e) depois de uma reconexão, só mensagens do canal novo alimentam a lista;<br>(f) exceção no código da api não chega à lib | teste com `WebRTCDataChannel` real e conexão fake | software | testado-software (2026-11-22 @ dc1043e) |
| A4 | Um cliente de `/ws/state` recebe, na ordem: `connection`, o valor atual de cada seção não nula (com `ts` da chegada original), `errors`. Depois, um frame por seção a cada mensagem. Em `reconnecting` → `connected` recebe `connection`, `errors: null`, `connection` e volta a receber as seções | teste | software | testado-software (2026-11-22 @ dc1043e) |
| A5 | Com `GO2_STATE_MAX_HZ=H` e um tópico chegando a 5H com relógio controlado, o cliente recebe no máximo H frames desse tópico por segundo, e o último frame recebido tem o valor da última mensagem, mesmo que o tópico pare. Com `0`, recebe todos. Negativo impede a api de subir | teste com relógio fake; teste de config | software | testado-software (2026-11-22 @ dc1043e) |
| A6 | Um cliente que não lê não atrasa outro que lê; o lento fica com no máximo 1 item pendente por tópico de seção. Um `add_error` seguido de `rm_error` chega inteiro ao cliente lento, na ordem | teste | software | testado-software (2026-11-22 @ dc1043e) |
| A7 | Com `GO2_STATE_MAX_CLIENTS` clientes, o próximo leva `1013`; com `0`, todos | teste | software | testado-software (2026-11-22 @ dc1043e) |
| A8 | Conectar e desconectar clientes do `/ws/state` não assina nem cancela tópico no robô | teste com fake pub_sub | software | testado-software (2026-11-22 @ dc1043e) |
| A9 | Com `GO2_STATE_MAX_CLIENTS` clientes que leem e `LOW_STATE`, `SPORT_MOD_STATE` e `MULTIPLE_STATE` chegando a 100 Hz cada (sintético, pior caso), o intervalo entre reenvios de um `move` simulado: (a) p99 do desvio ≤ linha de base + 10% do período; (b) nunca acima de 2× o período (régua do F-001 A8) | teste de carga (`slow`) | software | testado-software (2026-11-22 @ dc1043e) |
| A10 | Com o robô real, em até 5 s depois de conectar (número sugerido pelo Claude, sem medida), o `GET /status` mostra `battery`, `imu`, `motion`, `motors` e `settings` não nulos; `battery.percent` bate com o app oficial (±1); `settings.volume` e `settings.brightness` batem com o app | roteiro | hardware-only | inferido |
| A11 | Com o robô real e um cliente no `/ws/state` por 60 s, nenhum tópico passa de `GO2_STATE_MAX_HZ`. Registrar a taxa de cada tópico de origem (`state_metrics`) | roteiro | hardware-only | inferido |
| A12 | Com o robô real, registrar o que `errors` mostra logo depois de conectar (`null`, `[]` ou erros) e se bate com o app oficial | roteiro | hardware-only | inferido |

## Fora de escopo
- Converter unidades, calcular grandezas derivadas, alertar sobre bateria baixa ou temperatura.
- `LF_SPORT_MOD_STATE`, `SELF_TEST`, `SERVICE_STATE`, `UWB_STATE`, `GAS_SENSOR`, `WIRELESS_CONTROLLER` (conteúdo desconhecido ou acessório).
- Mudar ou remover campo existente do `/status`; mudar o `/capabilities`.
- Pedir `MULTIPLE_STATE` ao robô (só assinar). Se ele não chegar sozinho (A10), a spec é revista.
- Autenticação e lease (AGENTS.md raiz).

## Segurança
- Só leitura: nenhum comando novo de movimento.
- Assinar `MULTIPLE_STATE` põe mais um tópico no mesmo link e no mesmo event loop do `move` e do `stop`. A taxa e se ele exige algo do link (`disableTrafficSaving`) são `inferido`. O custo do `/ws/state` é medido em software (A9) e a taxa no robô (A11).
- Os dados do `/status` e do `/ws/state` não são usados para decisão de movimento nesta spec. `errors: null` quer dizer desconhecido: quem consome não deve tratar como robô saudável.

## Impacto HRI
Sem impacto HRI: a feature só expõe leitura para quem programa contra a api. O robô não emite som, luz nem movimento novo, e nada muda para quem está perto dele.

## Hipóteses não verificadas
- Nomes, tipos e unidades dos campos (exemplos do legion). `TODO(humano): conferir` (A10).
- Que `MULTIPLE_STATE` chega sem pedido, periodicamente, com `data` em string JSON. `TODO(humano): conferir` (A10).
- Taxa de cada tópico pelo WebRTC. `TODO(humano): medir` (A11).
- Formato das mensagens de erro (`[ts, source, code]`) e que a fotografia `errors` vem ao conectar. Lido no código da lib, não visto no robô (A12).
- Que `code` pode ser máscara de bits (a tabela da lib tem 0x1, 0x2, 0x4, 0x10…). Nesse caso, um código combinado cai no fallback e um `rm_error` com máscara diferente não remove o item. `TODO(humano): conferir` se aparecer.
- O relógio do `timestamp` do robô (Unix?).
- Que `range_obstacle` é a distância ao obstáculo por direção. Só o nome.
- Quanto tempo o `MULTIPLE_STATE` leva para refletir uma mudança de volume ou brilho (a F-005 o usa para confirmar). `TODO(humano): medir`.

## Decisões
Tomadas (2026-11-21, humano):
- `/status` ampliado + `/ws/state`, ligado por padrão como os outros streams;
- api independente de server e TV Box;
- `errors` `null` = desconhecido;
- na queda, as seções mantêm o último valor com a idade;
- `/capabilities` não muda.

Pendentes (humano):
1. `GO2_STATE_MAX_CLIENTS` = `4` e `GO2_STATE_MAX_HZ` = `10`?

## Roteiro hardware-only
No roteiro único da rodada: [`specs/checklists/api-completa.md`](../checklists/api-completa.md).

## Histórico
- 2026-11-21: criada (proposta).
- 2026-11-21: revisada pelo `spec-reviewer`. Correções:
  - gancho de erros na criação do data channel;
  - `null` × `[]` em `errors`;
  - não finitos viram `null`;
  - tipos esperados;
  - mesma extração para `battery_percent` e `mode`;
  - ordem dos frames na queda e na volta;
  - taxa com envio do retido;
  - `errors` sem descarte;
  - teste de carga (A9) e `state_metrics`.
- 2026-11-22: implementada (dc1043e); A1–A9 passam em software (fakes e `WebRTCDataChannel` real da lib, sem robô); A10–A12 pendentes no robô.
