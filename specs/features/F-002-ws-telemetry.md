---
id: F-002
titulo: Telemetria do LiDAR (/ws/telemetry) e gravação para análise
tipo: comportamento
status: em-implementacao
servicos: [api]
verificacao: testado-software
verificado-em: null
depende-de: [F-001]            # muda a regra de refcount do F-001 (ver "Ativação compartilhada")
---

# F-002 — Telemetria do LiDAR (`/ws/telemetry`) e gravação para análise

## Objetivo
Dar à equipe, e a um professor que vai avaliar SLAM, os dados **sobre** o LiDAR do Go2:
- taxa de amostragem;
- tempos;
- tamanho e resolução das nuvens;
- perdas;
- a pose e o estado do sensor publicados pelo robô.

Inclui uma ferramenta que grava a telemetria e a nuvem de pontos em disco, para análise offline. Não implementa SLAM.

## Comportamento

### Conexão
- Rota: `GET /ws/telemetry` (upgrade para WebSocket), sem autenticação. Só **frames de texto** JSON, no envelope `{"topic", "ts", "data"}`. `ts` é o instante em que a api produziu ou recebeu o dado (Unix, s).
- Ao aceitar, a api envia o frame `connection` com o estado atual. Depois, um frame `connection` a cada transição, igual ao `/ws/lidar` (F-001). Com o robô fora do ar, o cliente continua conectado.
- Limite: `GO2_TELEMETRY_MAX_CLIENTS` (padrão `1`). Acima dele, a api aceita e fecha o novo cliente com `1013`/`max_clients`; `0` desliga a rota. Desligar a api fecha com `1001`/`shutdown`.
- O cliente não envia nada; o que ele enviar é ignorado.
- Restrição de processo único, como no F-001.

### Ativação compartilhada com o `/ws/lidar`
Esta spec **muda a regra do F-001**: o LiDAR passa a ser ativado e **decodificado** quando há cliente em **qualquer uma** das duas rotas, mesmo que ninguém esteja olhando a nuvem. A decodificação continua fora do event loop, com as mesmas filas (F-001). O custo extra no processo do `stop` é coberto por A15 (software) e A16 (robô).

1. **LiDAR** (decoder de repasse, `disableTrafficSaving(True)`, assinatura de `ULIDAR_ARRAY`):
   - **liga** quando há ≥ 1 cliente somando `/ws/lidar` e `/ws/telemetry`, e o robô está `connected`;
   - **desliga** quando a soma chega a 0. A desligada inclui `disableTrafficSaving(False)`, como no F-001.
2. **Tópicos extras** (`ROBOTODOM` = `rt/utlidar/robot_pose`, `ULIDAR_STATE` = `rt/utlidar/lidar_state`):
   - são assinados **depois** de o LiDAR ficar ativo naquela conexão (depois do `ok` do `disableTrafficSaving`), e só se houver ≥ 1 cliente de telemetria;
   - se a telemetria chega com o LiDAR já ativo por um cliente de `/ws/lidar`, a api assina só os extras, sem repetir o `disableTrafficSaving`;
   - quando o último cliente de telemetria sai, a api cancela os extras e remove os callbacks (pegadinha #2). O LiDAR segue ativo se houver cliente de `/ws/lidar`;
   - a cada nova conexão com o robô, tudo é refeito (pegadinha #7): reativar o LiDAR e reassinar os extras, se houver clientes.
3. **Corridas:** clientes que chegam ou saem durante uma ativação são tratados pela mesma tarefa única do F-001, que reavalia até o estado bater com os clientes (LiDAR e extras).
4. **Falha na ativação** (timeout, resposta não `ok` ou erro no `disableTrafficSaving`):
   - clientes de `/ws/lidar`: fechados com `1011`/`lidar_unavailable`, como no F-001;
   - clientes de `/ws/telemetry`: **continuam abertos** (decisão humana). O `lidar_metrics` passa a sair com `active: false` e `last_error: "activation_failed"`.
   - A api não tenta de novo sozinha. Um cliente novo, em qualquer rota, dispara uma nova tentativa e limpa o `last_error`.

### Tópicos enviados

| `topic` | Origem | Quando | `data` |
|---|---|---|---|
| `connection` | api | ao aceitar e a cada transição | `{"state": "connected" \| "disconnected" \| "reconnecting"}` |
| `lidar_metrics` | api | a cada 1 s (ver "Janela") | ver abaixo |
| `lidar_pose` | robô (`ROBOTODOM`) | a cada mensagem recebida | `message["data"]` cru, convertido para JSON |
| `lidar_state` | robô (`ULIDAR_STATE`) | a cada mensagem recebida | `message["data"]` cru, convertido para JSON |

**Conversão para JSON dos dados do robô:** nenhum formato de `ROBOTODOM`/`ULIDAR_STATE` foi verificado, então a api não interpreta nada. Ela percorre o `message["data"]` **recursivamente** (dicionários e listas) e converte:
- `bytes`/`bytearray` → `{"base64": "<...>"}`.

  Os dois tópicos têm `utlidar` no nome, e a lib passa binário desses tópicos pelo decoder de LiDAR (`deal_array_buffer_for_normal`). Com o decoder de repasse, eles chegariam como bytes em `message["data"]["data"]`.
- `float` NaN/±Inf → `{"nonfinite": "nan" | "inf" | "-inf"}`. A api gera JSON estrito (`allow_nan=False`).
- escalar/array do numpy → número/lista;
- qualquer outro tipo → `{"unserializable": "<tipo>"}`, com log.

A conversão é feita **uma vez por mensagem**, no callback (no loop), e o texto resultante é compartilhado por todos os clientes. Sem limite de taxa: decisão humana. O custo está coberto por A15.

### `lidar_metrics`

**Janela:**
- A janela é **global**: um único relógio de 1 s, que roda enquanto houver ≥ 1 cliente de telemetria.
- Sem cliente de telemetria, o relógio para. Quando o primeiro cliente chega, ele zera os contadores e começa uma janela nova.
- O primeiro `lidar_metrics` de um cliente sai no fim da janela em curso (≤ 1 s depois de aceitar).
- O frame sai mesmo sem LiDAR ativo.

| Campo | Significado |
|---|---|
| `window_s` | Duração real da janela, em segundos |
| `active` | O LiDAR estava assinado no robô ao fim da janela |
| `last_error` | `null` ou `"activation_failed"` (ver "Falha na ativação") |
| `received` | Mensagens de `ULIDAR_ARRAY` que chegaram ao callback na janela, **incluindo** as malformadas |
| `rate_hz` | `received / window_s` |
| `interval_ms` | `{min, mean, max}` do intervalo entre chegadas consecutivas. Inclui a última chegada da janela anterior, mas **zera** a cada desativação e a cada nova conexão: o primeiro intervalo depois disso não é contado |
| `seq` | `{first, last}`: valores de `seq` (u32) atribuídos na janela, na ordem de chegada. Depois de 2³²−1, `last` pode ser menor que `first` |
| `compressed_bytes` | `{min, mean, max}` do payload comprimido (mensagens válidas) |
| `src_size` | `{min, mean, max}` do tamanho descomprimido declarado (mensagens válidas) |
| `n_points` | `{min, mean, max}` das mensagens decodificadas na janela |
| `decode_ms` | `{min, mean, max}` do tempo de parede de decodificação + montagem do frame, na thread do worker. Inclui a disputa de GIL; não é custo puro de CPU |
| `pipeline_ms` | `{min, mean, max}` do instante do callback (a lib já desmontou a mensagem, no loop) até o frame pronto: espera na fila + decodificação. Não inclui o envio aos clientes |
| `resolution`, `origin` | Os da última mensagem válida da janela (`null` se nenhuma) |
| `decoded` | Mensagens decodificadas na janela |
| `dropped_decode_queue` | Descartadas na fila de entrada do decoder |
| `dropped_lidar_clients` | Frames descartados nas filas dos clientes de `/ws/lidar` (soma) |
| `malformed`, `decode_errors` | Mensagens malformadas e falhas de decodificação |
| `clients` | `{"lidar": N, "telemetry": M}` no fim da janela |
| `dropped` | **Por cliente:** itens que **este** cliente perdeu na sua fila (todos os tópicos, inclusive `lidar_metrics` anteriores) desde o último `lidar_metrics` entregue a ele. É calculado no envio, e não se perde se um `lidar_metrics` for descartado: acumula até ser entregue |

Estatística sem amostra na janela vem `null`.

As métricas medem **a api**, não o sensor. `rate_hz` é a taxa com que as mensagens chegam à api pelo WebRTC; pode diferir da taxa interna do LiDAR, porque o robô junta os pontos em voxel map antes de enviar.

### Cliente lento
- O frame `connection` nunca é descartado.
- Para os demais tópicos, cada cliente tem uma fila **por tópico** de `GO2_TELEMETRY_CLIENT_QUEUE` itens (padrão `16`, decisão humana, não medido). Cheia, a api descarta o item mais antigo daquele tópico e soma 1 ao `dropped` do cliente.
- Ordem de envio: `connection` primeiro; os demais na ordem de chegada.

### Gravação (`api/scripts/record_lidar.py`)
Conecta em `/ws/lidar` e `/ws/telemetry` e grava num diretório novo (`--out`, obrigatório; recusa diretório que já exista):
- `telemetry.jsonl`: uma linha por frame de texto de `/ws/telemetry`: `{"received_at": <relógio da máquina que grava>, "frame": <frame como chegou>}`;
- `lidar/<n>_<seq>.bin`: cada frame binário de `/ws/lidar`, como chegou. `n` é o contador do próprio gravador, para que um reinício da api, que zera o `seq`, não sobrescreva arquivos;
- `lidar/index.jsonl`: uma linha por frame: `{"n", "seq", "ts", "n_points", "file", "received_at"}`;
- `meta.json`: URL base, início, fim, versão do frame, `--api-commit` (se informado), contagens e como terminou.

Opções:
- `--seconds` (padrão `60`);
- `--url-base` (padrão `ws://localhost:8000`);
- `--max-mb`: opcional; para ao atingir esse tamanho em disco. Sem padrão, porque o tamanho por frame ainda não foi medido.

O WebSocket do LiDAR abre com `max_size` explícito, pelo motivo do script do F-001.

**Término:**
- Fim do tempo ou do `--max-mb`: fecha os dois sockets, grava `meta.json` e sai com código 0.
- Qualquer socket fechado pelo servidor (`1013`, `1011`, `1001`) ou queda de conexão: grava em `meta.json` qual rota, o código e o motivo, fecha o outro socket e sai com código 1. **Não reconecta.**

  Com o `1011`, a telemetria seguiria aberta, mas a gravação fica sem a nuvem e por isso para.

### Contrato
- `specs/contracts/ws-telemetry.md`, no mesmo commit da implementação, registrado em `specs/contracts/README.md` com os consumidores `record_lidar.py` e visualizador. O CI não o confere (WebSocket fora do OpenAPI).
- O `ws-lidar.md` ganha uma nota: a ativação é compartilhada com `/ws/telemetry`, e `record_lidar.py` também é consumidor.
- O F-001 ganha uma entrada no Histórico apontando a mudança de regra.

## Critérios de aceite

| ID | Critério (observável) | Como verificar | Tipo | Verificação |
|---|---|---|---|---|
| A1 | Ao conectar em `/ws/telemetry`, o primeiro frame é `connection` com o estado atual; com o robô fora do ar, o cliente continua conectado e recebe `lidar_metrics` com `active: false` | teste de rota | software | testado-software (2026-11-17 @ 009f4bb) |
| A2 | Só um cliente de telemetria, com o robô `connected`: o LiDAR é ativado (repasse, `disableTrafficSaving(True)`, `ULIDAR_ARRAY`) e, depois do `ok`, `ROBOTODOM` e `ULIDAR_STATE` são assinados | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A3 | Um cliente em cada rota: quando o de telemetria sai, os extras são cancelados e os callbacks removidos, mas o LiDAR segue ativo; quando o de `/ws/lidar` sai, o LiDAR é desativado (`disableTrafficSaving(False)`) | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A4 | Só cliente de `/ws/lidar`: os extras não são assinados | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A5 | LiDAR já ativo por cliente de `/ws/lidar`: quando a telemetria chega, só os extras são assinados (`disableTrafficSaving` chamado uma única vez no total) | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A6 | Clientes nas duas rotas e reconexão do robô: LiDAR e extras são reassinados na conexão nova, e os dois clientes recebem `disconnected`, `reconnecting` e `connected` sem fechar | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A7 | Falha na ativação com clientes nas duas rotas: o de `/ws/lidar` é fechado com `1011`/`lidar_unavailable`; o de telemetria segue aberto, com `lidar_metrics` em `active: false` e `last_error: "activation_failed"`; não há nova tentativa até um cliente novo chegar, que limpa o `last_error` se der certo | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A8 | Telemetria entra ou sai enquanto a ativação está pendente: ao fim, os extras estão assinados se, e só se, há cliente de telemetria | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A9 | Mensagens de `ROBOTODOM`/`ULIDAR_STATE` viram `lidar_pose`/`lidar_state` com `data` igual ao `message["data"]`, convertido conforme a regra: `bytes` aninhado → `{"base64"}`, NaN/Inf → `{"nonfinite"}`, numpy → número/lista, outro → `{"unserializable"}`; o JSON é estrito e o stream não cai | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A10 | Com relógio controlado e mensagens de LiDAR em instantes conhecidos, `lidar_metrics` traz `received` (inclui malformadas), `rate_hz`, `interval_ms`, `seq`, `compressed_bytes`, `src_size`, `n_points`, `resolution`/`origin` e `decoded` iguais aos esperados; `decode_ms` e `pipeline_ms` ≥ 0 | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A11 | `interval_ms` zera depois de uma desativação e de uma reconexão (o intervalo que cruza a pausa não é contado); estatísticas sem amostra vêm `null` | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A12 | Descartes: `dropped_decode_queue` bate com os descartes da fila do decoder; `dropped_lidar_clients` com os de um cliente de `/ws/lidar` que não lê; `malformed`/`decode_errors` com as mensagens ruins | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A13 | Cliente de telemetria lento: `connection` nunca é descartado; cada tópico guarda no máximo 16 itens (os mais novos); o `dropped` do próximo `lidar_metrics` entregue conta tudo o que ele perdeu, inclusive `lidar_metrics` descartados | teste | software | testado-software (2026-11-17 @ 009f4bb) |
| A14 | `GO2_TELEMETRY_MAX_CLIENTS` (padrão 1): o segundo cliente leva `1013`; `0` desliga a rota; o limite do `/ws/lidar` não muda | teste de rota | software | testado-software (2026-11-17 @ 009f4bb) |
| A15 | Pior caso só com telemetria: decoder ocupado sem parar (como o A8 do F-001) **e** `ROBOTODOM`/`ULIDAR_STATE` sintéticos chegando a uma taxa alta escolhida pelo teste (provisória até o H1). O `move` simulado respeita os limites do A8 do F-001: p99 do desvio ≤ linha de base + 10% do período; teto 2× o período | teste de carga (`slow`) | software | testado-software (2026-11-17 @ 009f4bb) (provisório: carga sintética até o H1) |
| A16 | O gravador, alimentado com frames conhecidos, produz `telemetry.jsonl`, `lidar/<n>_<seq>.bin`, `lidar/index.jsonl` e `meta.json` corretos, não sobrescreve quando o `seq` se repete e registra em `meta.json` o fechamento pelo servidor (rota, código, motivo) | teste das funções do script | software | testado-software (2026-11-17 @ 009f4bb) |
| A17 | Com o robô real, 60 s de gravação: `lidar_metrics` com `received > 0` e `active: true` na maior parte das janelas, e os `.bin` gravados abrem com o snippet do `ws-lidar.md`, com `n_points > 0` | roteiro H1 | hardware-only | inferido |
| A18 | Os limites do F-001 (A13: `stop` com mediana +0,2 s e pior caso +0,4 s; A14: p99 do intervalo do `move` ≤ linha de base + 10% do período, teto 2× o período) são respeitados com a configuração da sessão: `GO2_LIDAR_MAX_CLIENTS=2` com 2 clientes de LiDAR (visualizador e gravador) e 1 de telemetria (gravador), e o gravador na mesma máquina da api | roteiro H2 | hardware-only | inferido |

## Fora de escopo
- `LOW_STATE`/`SPORT_MOD_STATE` (IMU, velocidade, bateria) no stream: decisão humana desta spec. Continuam no `GET /status`.
- Metadados crus que acompanham cada voxel map, além de `src_size`, `origin` e `resolution`.
- Outros tópicos: `MULTIPLE_STATE`, `LF_SPORT_MOD_STATE`, `ULIDAR` não comprimido, `uslam`/mapeamento, `GRID_MAP`, `SLAM_*`.
- SLAM, sincronização de relógio com o robô, conversão para formatos ROS (bag, PCD).
- Interpretar a pose ou o estado do sensor (campos, unidades, referencial). O H1 só registra observações, sem critério.
- Gravação dentro da api (o gravador é cliente externo) e reconexão automática do gravador.
- Autenticação e lease.

## Segurança
- Nenhum comando novo; só leitura.
- **Mais carga no mesmo processo e no mesmo link que levam o `stop` e o `move`:**
  - o LiDAR pode ficar ativo e decodificando sem visualização;
  - entram duas assinaturas novas;
  - a conversão para JSON de pose e estado roda no loop, sem limite de taxa.

  Guardas:
  - decodificação fora do loop e filas limitadas (F-001);
  - conversão uma vez por mensagem;
  - carga medida em software (A15) e no robô (A18).

  Na sessão, o gravador roda na mesma máquina da api e também disputa CPU e disco; A18 mede com ele lá.
- Os dados não podem ser usados para decisão de movimento: pose, referencial e tempos são `inferido`.

## Impacto HRI
Sem impacto HRI: o stream é lido pela equipe e por um professor, para análise. O robô não emite som, fala nem movimento novo. O efeito indireto possível (atraso do `stop`) é tratado em Segurança e medido em A18.

## Hipóteses não verificadas
- Se `ROBOTODOM` e `ULIDAR_STATE` são publicados pelo robô via WebRTC, com que taxa e em que formato (texto JSON ou binário). `TODO(humano): verificar` (H1). Isso define também a taxa realista para o A15.
- O que é `ROBOTODOM` (pose do SLAM interno? odometria?), em que referencial e com que carimbo de tempo. O dossiê descreve como "pose do SLAM interno", mas ninguém verificou. `TODO(humano): observar` (H1.3).
- Se assinar esses tópicos exige algo além do `subscribe`, como o LiDAR exige o `disableTrafficSaving`.
- Taxa real do LiDAR pelo WebRTC e quanto ela varia: o `rate_hz` vai medir (H1).
- Tamanho em disco por minuto de gravação: o H1 vai medir (informa o `--max-mb` futuro).

## Decisões
Tomadas (2026-11-17, humano):
- Rota `/ws/telemetry` focada no LiDAR: métricas calculadas pela api + `ROBOTODOM` e `ULIDAR_STATE` crus.
- Formato cru para tudo que vem do robô, sem limite de taxa.
- Ativação compartilhada: um cliente de telemetria sozinho liga e decodifica o LiDAR. Isso muda a regra do F-001.
- Falha na ativação não fecha a telemetria (`last_error`).
- `GO2_TELEMETRY_MAX_CLIENTS` = `1`; `GO2_TELEMETRY_CLIENT_QUEUE` = `16`.
- Janela de 1 s.
- Script de gravação em disco, na mesma máquina da api.
- `LOW_STATE`/`SPORT_MOD_STATE` fora do stream.
- Sessão de hardware com `GO2_LIDAR_MAX_CLIENTS=2`, por configuração; o padrão do código continua `1`.

Pendentes: nenhuma.

## Roteiro hardware-only
Preparação: a mesma do F-001:
- área livre;
- `python -m sense.stop` pronto;
- api com log DEBUG e `GO2_LIDAR_MAX_CLIENTS=2`;
- server desligado: nesta sessão só rodam a api, o visualizador e o gravador.

Registrar o commit.

**H1 — dados reais (A17 e hipóteses)**, junto com o H1 do F-001:
1. Robô de pé e parado. Rodar `uv run python scripts/record_lidar.py --seconds 60 --out <dir>`.
2. Registrar a partir de `telemetry.jsonl`:
   - `rate_hz` (mín./médio/máx.);
   - `n_points`;
   - `decode_ms` e `pipeline_ms`;
   - descartes;
   - se chegaram `lidar_pose` e `lidar_state`, com que frequência e em que formato (JSON ou `base64`).
   - o tamanho do diretório.
3. **Só observação, sem passa/falha:**
   1. `balance_stand`;
   2. `POST /commands/move` com `vx=0.3`, `duration_s=3` (cerca de 0,9 m, se o robô seguir o comando);
   3. registrar a distância real com trena e como `lidar_pose` mudou.
4. Abrir alguns `lidar/*.bin` com o snippet do `ws-lidar.md` e conferir que a nuvem corresponde ao lab.
5. Guardar o diretório gravado para o professor.

**H2 — interferência (A18):** o H2 do F-001, com a configuração da sessão.
- **Linha de base:** api recém-reiniciada, sem nenhum cliente desde o boot, e o gravador parado.
- **Medida:** visualizador em `/ws/lidar` e gravador em `/ws/lidar` + `/ws/telemetry`, todos na mesma máquina da api.

Registrar a máquina, o vídeo, o log e o commit.

## Histórico
- 2026-11-17: criada (proposta), a partir do pedido do humano de telemetria do LiDAR para SLAM.
- 2026-11-17: revisada pelo `spec-reviewer`:
  - `dropped` por cliente;
  - ciclo de vida dos extras (LiDAR já ativo, reconexão, corrida);
  - conversão recursiva para JSON estrito;
  - definições de janela e métricas;
  - teste de carga em software (A15);
  - término do gravador;
  - critérios de hardware com passa/falha.

  Decisões humanas: falha mantém a telemetria aberta, fila 16, limite do LiDAR 2 na sessão, gravador na mesma máquina.
- 2026-11-17: implementada em `feat/ws-telemetry` (em-implementacao). A1–A16 passam em teste automático (dublês; A15 com carga sintética). A17 e A18 pendentes (H1/H2).
