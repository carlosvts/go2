---
id: F-001
titulo: Stream binário de nuvem de pontos do LiDAR (/ws/lidar)
tipo: comportamento
status: em-implementacao
servicos: [api]
verificacao: testado-software
verificado-em: null
depende-de: []                 # cria o contrato specs/contracts/ws-lidar.md junto com a implementação
---

# F-001 — Stream binário de nuvem de pontos do LiDAR (`/ws/lidar`)

## Objetivo
Dar a clientes da api acesso contínuo à nuvem de pontos do LiDAR do Go2, por WebSocket binário, sem que eles precisem de WebRTC, lz4 ou do formato de voxel da Unitree. O primeiro consumidor é **visualização/debug** no lab. O uso pelo `server/` (decisão de movimento) é outra feature, com spec própria.

Corresponde à issue carlosvts/go2-api#6. Da infraestrutura de streams de `api/docs/arquitetura_go2_api.md` §4.5–4.6, entram só as partes que o LiDAR usa:
- #12: ponte entre o callback da lib e os clientes;
- #13: refcount;
- #14: estado da conexão no stream.

O `TopicHub` genérico (#9), o `FakeHub` (#10) e o `/ws/telemetry` (#5) ficam fora.

Isso inverte a ordem de §5 da arquitetura, que previa o `/ws/telemetry` primeiro para validar o desenho. Motivo: o LiDAR é o primeiro consumidor pedido. Inversão aprovada pelo humano (2026-11-17); a telemetria terá spec própria depois.

## Comportamento

### Conexão
- Rota: `GET /ws/lidar` (upgrade para WebSocket). Sem autenticação: fora de escopo (AGENTS.md raiz).
- A api sempre aceita o upgrade (`accept()`) antes de qualquer fechamento, para que o cliente receba o código de fechamento e não um HTTP 403.
- Ao aceitar, a api envia **um frame de texto** com o estado atual da conexão com o robô (ver "Frames de texto"). Isso vale também com o robô fora do ar: o cliente fica conectado esperando.
- Com pelo menos um cliente conectado e o robô `connected`, a api envia **um frame binário por mensagem de LiDAR decodificada** (tópico `rt/utlidar/voxel_map_compressed`, `ULIDAR_ARRAY`), respeitando os descartes descritos abaixo.
- O cliente não envia nada. A api ignora mensagens vindas do cliente.
- Restrição: a api roda em **um processo** (sem `uvicorn --workers`), como já exige §4.6. O `seq` e o limite de clientes só valem assim.

### Frame binário (versão 1)
Little-endian. O cabeçalho tem 40 bytes, para que o corpo comece em offset múltiplo de 8. Assim funcionam `Float32Array(buf, 40)` no navegador e `np.frombuffer(buf, "<f4", offset=40)`.

| Offset | Tipo | Campo | Significado |
|---|---|---|---|
| 0 | u8 | `version` | `1`. Cliente que não conhece a versão descarta o frame. |
| 1 | u8 | `flags` | `0`; reservado. |
| 2 | u16 | `header_len` | `40`. O corpo começa em `header_len`. |
| 4 | u32 | `seq` | Contador da api: +1 a cada mensagem de LiDAR recebida do robô, comum a todos os clientes. Volta a 0 depois de 2³²−1 e quando a api reinicia. Buraco na sequência = mensagem descartada (antes do decoder ou na fila do cliente). |
| 8 | f64 | `ts` | Instante em que a api recebeu a mensagem (Unix, segundos). Não é o instante da medição no robô. |
| 16 | u32 | `n_points` | Número de pontos no corpo. Pode ser `0`. |
| 20 | f32 | `resolution` | Lado do voxel em metros, copiado da mensagem do robô. |
| 24 | f32×3 | `origin` | Origem do grid (x, y, z), copiada da mensagem do robô. |
| 36 | u32 | `reserved` | `0`. |
| 40 | f32×3×N | `points` | Pontos `(x, y, z)` em metros, já com `resolution` e `origin` aplicados: saída do decoder `native` da lib, convertida de float64 para float32. |

Tamanho do frame: `40 + 12 × n_points` bytes.

O que **não se sabe** sobre o frame:
- o formato de `resolution`/`origin` na mensagem do robô (escalar/lista de 3) foi lido no código do decoder, não visto no robô;
- o referencial dos pontos (corpo do robô, odômetro ou mundo).

Ver Hipóteses.

### Frames de texto
JSON no envelope planejado para os streams: `{"topic": "connection", "ts": <float>, "data": {"state": "connected" | "disconnected" | "reconnecting"}}`. Os estados são os de `ConnectionState` (`app/robot/connection.py`). A api envia um frame ao aceitar o cliente e outro a cada mudança de estado.

- Frames de texto **nunca são descartados** pelo backpressure: vão por caminho próprio, separado da fila de frames binários.
- Fora de `connected`, não chegam frames binários. O WebSocket **continua aberto**, e os frames voltam sozinhos depois da reconexão.
- Limitação herdada: cada tentativa de reconexão trava o event loop da api por alguns segundos (`Go2Robot.keep_connected`). Durante isso não sai frame nem comando. Isso não é efeito desta feature, mas precisa ser lembrado ao ler A11/A12.

### Decodificação fora do event loop
A descompressão lz4 e a conversão voxel → pontos **não rodam na thread do event loop**.

A lib 2.2.0 chama `datachannel.decoder.decode(...)` dentro do handler do data channel, no loop (`webrtc_datachannel.py`, `deal_array_buffer_for_lidar`). Mecanismo, sem patch na lib e confinado a `app/robot/unitree.py`:

1. A cada `connect()`, a api põe em `datachannel.decoder` um **decoder de repasse**. Ele não descomprime nada: devolve os bytes comprimidos e os metadados (`src_size`, `origin`, `resolution`). Precisa ser refeito a cada conexão, porque o `datachannel` é recriado (pegadinha #7).
2. O callback do tópico (no loop) atribui o `seq` e põe a mensagem crua numa **fila de entrada do decoder**. A fila é limitada (`GO2_LIDAR_DECODE_QUEUE`, padrão `2`) e, cheia, descarta a mais antiga.
3. **Um único worker**, em thread fora do loop, consome a fila em ordem e chama o decoder `native` da lib (`lidar_decoder_native.LidarDecoder`).
4. O resultado vira frame e vai para as filas dos clientes.

Com um único worker, frames saem na ordem do `seq`, e o acúmulo antes do decoder é limitado.

Thread fora do loop não elimina a disputa de GIL e CPU. O efeito real sobre o loop é medido em A8 (software, carga sintética) e A13/A14 (robô).

### Cliente lento (backpressure)
Cada cliente tem fila própria de frames binários, de tamanho limitado (`GO2_LIDAR_CLIENT_QUEUE`, padrão `2`, decisão humana: o visualizador prefere a nuvem mais recente a receber todas). Com a fila cheia, a api descarta o frame **mais antigo** daquele cliente. Um cliente lento não atrasa os outros, o decoder nem o robô.

### Ativação do LiDAR no robô (refcount)
- **Gatilho:** existir pelo menos 1 cliente **e** o robô estar `connected`. Isso cobre o primeiro cliente com o robô no ar e a volta do robô com clientes esperando. Nesse momento a api:
  1. instala o decoder de repasse;
  2. chama `disableTrafficSaving(True)` com timeout `GO2_REQUEST_TIMEOUT_S`;
  3. assina `ULIDAR_ARRAY`.
- Com o robô fora do ar, a api **não** chama `subscribe`: a lib só faz `print` com o canal fechado (pegadinha #3). O cliente espera com o estado `disconnected`/`reconnecting`.
- **Ativação em andamento:** clientes que chegam enquanto a ativação está pendente não disparam outra. Se todos os clientes saem durante a ativação, a api termina a ativação e em seguida desativa.
- **Último cliente sai:** a api cancela a assinatura e remove o callback de `pub_sub.subscriptions` (a lib não remove: pegadinha #2). A api chama `disableTrafficSaving(False)` com timeout `GO2_REQUEST_TIMEOUT_S`, para devolver o link ao estado de antes da feature (decisão humana). Falha nessa chamada só é registrada em log: não há cliente para avisar. A fila de entrada do decoder é esvaziada. Sem clientes, nenhuma mensagem de LiDAR é decodificada.
- **Falha na ativação** (timeout, exceção ou resposta sem `info.execution == "ok"`, formato lido no código da lib e não visto no robô):
  - a api fecha os clientes de `/ws/lidar` com código `1011` e motivo `lidar_unavailable`;
  - registra o erro em log;
  - não repete a tentativa sozinha. Um cliente novo dispara uma nova tentativa.

  Isso vale também para a reativação depois de uma reconexão: clientes que funcionavam são fechados. Assim a falha fica visível, sem laço de timeouts.
- A ativação do LiDAR não altera a assinatura de `LOW_STATE`/`SPORT_MOD_STATE`, de que o `/status` depende.

### Limite de clientes
Com `GO2_LIDAR_MAX_CLIENTS` clientes conectados, a api aceita o próximo e o fecha logo em seguida com código `1013` (try again later). Padrão: `1` (decisão humana, 2026-11-17). `0` desliga a rota: todo cliente recebe `1013`.

### Instrumentação para o teste no robô
- Script `api/scripts/ws_lidar_client.py`: conecta, valida o cabeçalho e imprime a taxa (frames/s), `n_points`, bytes/frame, buracos no `seq` e as transições de estado. Abre o WebSocket com `max_size` explícito, porque o padrão de 1 MiB da biblioteca `websockets` corta acima de ~87 mil pontos. Opção para salvar N frames em arquivo, para visualizar.
- O loop de `move` registra em log (nível DEBUG) o intervalo real entre reenvios. Sem isso, A14 não é medível: hoje o loop não registra cada reenvio.

### Contrato
O formato do frame e dos códigos de fechamento vai para `specs/contracts/ws-lidar.md`, no mesmo commit da implementação. A tabela de `specs/contracts/README.md` ganha uma linha: dono `api`, consumidor `scripts/ws_lidar_client.py` (o `server/` ainda não). O OpenAPI não descreve frames de WebSocket, então **o CI não confere esse contrato**: só a revisão humana e os testes A1/A2.

## Critérios de aceite

| ID | Critério (observável) | Como verificar | Tipo | Verificação |
|---|---|---|---|---|
| A1 | Dado um cliente conectado e uma mensagem de LiDAR com payload lz4 gerado no teste, quando a mensagem chega, então o cliente recebe um frame com `version=1`, `header_len=40`, `n_points` correto, `resolution`/`origin` copiados e pontos iguais (tolerância float32) aos que o `LidarDecoder` `native` da lib produz para o mesmo payload | `tests/test_ws_lidar.py` | software | testado-software (2026-11-17 @ d9e450b) |
| A2 | Dada uma mensagem com 0 voxels ocupados, então o frame tem `n_points=0` e 40 bytes | teste | software | testado-software (2026-11-17 @ d9e450b) |
| A3 | Usando a classe **real** de data channel da lib (`WebRTCDataChannel.deal_array_buffer`) com o decoder de repasse instalado, nenhuma chamada de descompressão lz4 acontece na thread do event loop, e a descompressão acontece exatamente uma vez por mensagem, em outra thread | teste: buffer no formato da lib, `lz4.block.decompress` instrumentado registrando `threading.get_ident()` | software | testado-software (2026-11-17 @ d9e450b) |
| A4 | Dados 0 clientes e robô `connected`: quando o 1º conecta, a api instala o decoder, chama `disableTrafficSaving(True)` e assina `ULIDAR_ARRAY` uma vez; o 2º cliente não dispara nada novo; quando ambos saem, a api cancela a assinatura, o callback sai de `pub_sub.subscriptions` e a api chama `disableTrafficSaving(False)` uma vez | teste com fake pub_sub | software | testado-software (2026-11-17 @ d9e450b) |
| A5 | Dado o robô `disconnected`: quando um cliente conecta, ele recebe `connection: disconnected`, continua conectado e não há `subscribe`; quando o robô vai a `connected`, a ativação acontece e os frames começam | teste com fake link | software | testado-software (2026-11-17 @ d9e450b) |
| A6 | Dados clientes conectados: quando o robô passa por `reconnecting` → `connected`, cada cliente recebe as transições na ordem, o WebSocket não fecha, o decoder de repasse é reinstalado e os frames voltam sem o cliente reconectar | teste com fake link | software | testado-software (2026-11-17 @ d9e450b) |
| A7 | Dado `disableTrafficSaving` (a) sem resposta além de `GO2_REQUEST_TIMEOUT_S`, (b) com resposta sem `execution == "ok"` ou (c) lançando exceção, então os clientes são fechados com `1011`/`lidar_unavailable`, não há nova tentativa automática e outro endpoint da api responde durante a espera | teste, um caso por variante | software | testado-software (2026-11-17 @ d9e450b) |
| A8 | Com o worker decodificando sem parar (fila de entrada sempre cheia: pior caso, independe da taxa do robô) o payload real de maior `n_points` gravado no H1, o intervalo entre reenvios de um `move` simulado a `GO2_MOVE_RATE_HZ`: (a) no p99, desvia do nominal no máximo a linha de base sem decoder + 10% do período; (b) nunca passa de 2× o período. Até o H1, o teste roda com payload sintético e fica marcado provisório | teste de carga (pode ficar marcado `slow`) | software | testado-software (2026-11-17 @ d9e450b) (provisório: payload sintético até o H1) |
| A9 | Com `GO2_LIDAR_MAX_CLIENTS=2` só no teste, dado um cliente que não lê e outro que lê, quando chegam mais mensagens do que `GO2_LIDAR_CLIENT_QUEUE`, então o que lê recebe todas, com `seq` crescente, e o lento recebe as mais recentes, com buraco no `seq`; um frame `connection` emitido nesse meio chega aos dois | teste | software | testado-software (2026-11-17 @ d9e450b) |
| A10 | Dado um decoder mais lento que a chegada, a fila de entrada do decoder nunca passa do limite, os frames saem com `seq` crescente e o descarte aparece como buraco no `seq` | teste com decoder fake lento | software | testado-software (2026-11-17 @ d9e450b) |
| A11 | Com o LiDAR ativo, o `/status` continua atualizando `LOW_STATE`/`SPORT_MOD_STATE`; com `GO2_LIDAR_MAX_CLIENTS` clientes, o próximo é aceito e fechado com `1013`; com o limite `0`, todo cliente recebe `1013` | teste | software | testado-software (2026-11-17 @ d9e450b) |
| A12 | Com o robô real e um cliente, chegam frames com `n_points > 0`, e uma parede a distância medida com trena aparece na nuvem a essa distância do robô, com erro ≤ 0,05 m (registrar o erro medido; a meta é 0,01 m) | roteiro H1 | hardware-only | inferido |
| A13 | O tempo entre o `POST /commands/stop` e o robô parar, durante um `move`, com `GO2_LIDAR_MAX_CLIENTS` clientes no `/ws/lidar`, tem mediana no máximo 0,2 s acima da mediana da linha de base sem LiDAR, e nenhuma repetição passa 0,4 s acima dela | roteiro H2 (vídeo) | hardware-only | inferido |
| A14 | Durante um `move` com `GO2_LIDAR_MAX_CLIENTS` clientes, o intervalo entre reenvios (log DEBUG) (a) no p99, desvia do nominal no máximo o p99 da linha de base sem LiDAR + 10% do período (≈3,3 ms a 30 Hz); (b) nunca passa de 2× o período (≈67 ms a 30 Hz, um reenvio perdido) | roteiro H2 (log) | hardware-only | inferido |

Os limites de A8, A12, A13 e A14 são definidos por um humano **antes** de rodar H1/H2 e não mudam depois.

Origem dos limites (2026-11-17):
- **A13:** dado pelo humano ("0,2–0,4 s aceitável"): 0,2 s na mediana e 0,4 s no pior caso. Confirmado em 2026-11-17.
- **A12:** dado pelo humano: 1 a 5 cm. Passa com ≤ 5 cm; 1 cm é a meta. A nuvem é quantizada no tamanho do voxel (`resolution`; o padrão do decoder é 5 cm, não verificado no robô), então o erro de quantização sozinho pode chegar a meio voxel (≈2,5 cm), e 1 cm pode ser inalcançável. Registrar a `resolution` observada no H1.
- **A8/A14:** sugeridos pelo Claude a pedido do humano, sem medida no Go2, aceitos pelo humano em 2026-11-17. A regra de bolso da literatura de controle é que jitter abaixo de ~10% do período pode ser ignorado; há exemplos mais estritos, de 5%. O critério compara com a linha de base porque o jitter do `asyncio` e do Wi-Fi já existe sem LiDAR. O teto de 2× o período marca um reenvio perdido. Pela doc do G1 (outro robô, não verificado no Go2), cada `Move` vale ~1 s, então um reenvio perdido não deve parar o robô: afeta suavidade, não segurança. Por isso a régua de segurança é o A13, e o A14 mede qualidade.

## Fora de escopo
- `/ws/telemetry`, `/ws/video`, o `TopicHub` genérico (#9) e o `FakeHub` (#10). Generalizar fica para a spec do próximo stream.
- Uso dos dados pelo `server/` ou por qualquer lógica de movimento (desvio, parada automática). Feature futura, provavelmente tipo `seguranca`.
- Formato `libvoxel` (malha), repasse do payload comprimido cru ao cliente, downsampling, filtro por região.
- SLAM/mapeamento (`uslam`, `LIDAR_MAPPING_*`), `ULIDAR` não comprimido, `ULIDAR_STATE`, `ROBOTODOM`.
- Autenticação e lease (AGENTS.md raiz).
- Ligar/desligar o sensor por `rt/utlidar/switch`: só entra se H1 mostrar que é preciso.
- Patch na `unitree_webrtc_connect`.

## Segurança
- **Nenhum comando de movimento novo.** A feature só lê.
- **Risco principal: atrasar o `stop` e o reenvio do `move`.** Os dois rodam no mesmo event loop e no mesmo data channel WebRTC que passa a carregar o LiDAR. Isso vale também para o `python -m sense.stop`, a garantia independente de parada, que usa o mesmo `POST /commands/stop`.
- **Mitigação:**
  - decodificação fora do loop (A3);
  - assinatura só com cliente presente (A4);
  - filas limitadas antes e depois do decoder (A9, A10);
  - medida sob carga (A8) e no robô (A13, A14).
- **Régua:** a feature **pode** aumentar o tempo de parada, mas no máximo até o limite de A13, que um humano define antes do H2. Passou do limite: a feature não é adotada.
- `disableTrafficSaving(True)` muda o link com o robô de forma não documentada (provavelmente mais banda). O efeito sobre comandos está coberto por A13/A14.
- Os dados não podem ser usados para decisão de movimento antes da spec futura: referencial, latência e taxa ainda são `inferido`.

## Impacto HRI
Sem impacto HRI: o stream só é lido pela equipe, para visualização, e o robô não emite som, fala nem movimento novo.

A única ligação com quem está perto do robô é **indireta e de segurança percebida**: se o LiDAR atrasar o `stop`, o robô demora mais para parar perto de alguém. Isso é tratado como critério de segurança (A13, com limite definido antes do teste), não como retorno ao usuário.

A feature futura que usar o LiDAR para decidir movimento terá impacto HRI direto e precisa preencher esta seção.

## Hipóteses não verificadas
- Taxa de mensagens de LiDAR que o robô envia pelo WebRTC. `TODO(humano): medir` (H1, frames/s).
- `n_points` típico, `src_size` e bytes por frame no lab. `TODO(humano): medir` (H1). Alimenta a carga de A8.
- Custo de CPU da decodificação `native` por mensagem, na máquina onde a api roda. `TODO(humano): medir` (H1).
- O voxel map é a varredura do momento ou um mapa que **acumula** (e por quanto tempo um objeto que saiu continua aparecendo)? Na primeira observação do humano, mover uma caixa em volta do robô mudou pouco a cena. `TODO(humano): verificar` (roteiro H1.10).
- Se o robô fica no centro do grid de 128×128 voxels (`origin + 64 × resolution` em x e y). Inferido pelo formato do decoder; o visualizador marca esse ponto. `TODO(humano): verificar` (H1.8).
- Referencial dos pontos: o `origin` muda quando o robô anda? `TODO(humano): verificar` (H1.6).
- Formato de `origin`/`resolution` em `message["data"]`. Lido no código do decoder, não visto no robô.
- Formato da resposta de `disableTrafficSaving` (`info.execution`). Lido no código da lib, não visto no robô.
- Se é preciso publicar `"on"` em `rt/utlidar/switch`. `TODO(humano): verificar` (H1.4).
- O decoder de repasse funciona sem patch: a lib só chama `decoder.decode(binary, data)` e põe o retorno em `data["data"]`. Lido no código 2.2.0; confirmar na implementação (A3 usa a classe real).
- `ts` é o tempo de chegada na api. Se a mensagem do robô traz carimbo próprio, não se verificou.
- O que `disableTrafficSaving(True/False)` muda no robô e se o `False` de fato restaura o estado de fábrica. Não verificado; por isso a linha de base do H2 exige api recém-reiniciada.
- Se o efeito de `disableTrafficSaving` sobrevive a uma reconexão WebRTC. `TODO(humano): verificar`.

## Decisões

Tomadas (2026-11-17, humano):
- **Se o decoder de repasse não funcionar sem patch** (A3 falha com a classe real): a feature não para. A spec é revisada: o mecanismo e os critérios afetados (A3, A8) mudam, com aprovação humana, antes de seguir. Critério de feature pode ser alterado; isso não vale para experimento.
- **Ordem:** LiDAR antes de `/ws/telemetry`, que terá spec própria.
- **`GO2_LIDAR_MAX_CLIENTS`:** padrão `1`.
- **Filas:** `GO2_LIDAR_CLIENT_QUEUE` = `2`; a fila de entrada do decoder (`GO2_LIDAR_DECODE_QUEUE`) também `2`, por analogia.
- **`disableTrafficSaving`:** ligado enquanto houver cliente; `False` quando o último sai.
- **A13:** mediana +0,2 s, pior caso +0,4 s (confirmado).
- **A12:** erro ≤ 0,05 m; meta 0,01 m.
- **A8/A14:** limites sugeridos aceitos (p99 ≤ linha de base + 10% do período; teto 2× o período).

Pendentes (humano): nenhuma.

## Roteiro hardware-only

**Roteiro executável da sessão (F-001 + F-002 juntos):** [`specs/checklists/F-001-F-002.md`](../checklists/F-001-F-002.md). Lá, H1 é o H1 daqui, H2 é a parte "andando" (observação) e H3 é o H2 daqui. O log DEBUG do `move` só aparece com `--log-config logging-debug.json`, e `scripts/move_jitter.py` faz a conta do A14.
Preparação comum (H1 e H2): área livre de pessoas e obstáculos no raio de deslocamento, uma pessoa com `python -m sense.stop` pronto para rodar, robô em `balance_stand` (`stand_up` não basta para `move`), api subindo com log em DEBUG. Registrar o commit.

**H1 — dados reais (A12 e hipóteses)**
1. Robô parado num ponto do lab, com uma parede à frente a distância medida com trena a partir do centro do robô. Registrar a distância.
2. Rodar `uv run python scripts/ws_lidar_client.py` por 60 s.
3. Registrar: frames/s, `n_points` mín./médio/máx., bytes/frame, buracos no `seq`, CPU da api (`top`).
4. Se nenhum frame chegar: publicar `"on"` em `rt/utlidar/switch`, repetir o passo 2 e registrar o resultado.
5. Salvar alguns frames e abri-los (Open3D/matplotlib). Registrar onde o robô fica na nuvem (perto de `(0,0,0)`? perto do `origin`?).
6. Andar ~1 m em linha reta (`POST /commands/move`). Registrar se a parede e o `origin` mudam de lugar na nuvem. Com isso fica definido o referencial.
7. Só depois do passo 6: medir na nuvem a distância robô → parede e comparar com a trena e a tolerância de A12.

**H2 — interferência no `stop`/`move` (A13, A14)**
1. **Linha de base:** reiniciar a api e não conectar nenhum cliente de LiDAR desde o boot (`disableTrafficSaving` não pode ter sido chamado).
2. 10× `move` para a frente com `duration_s` de 2 s, `POST /commands/stop` no meio. Filmar com o envio do stop visível no quadro (por exemplo, o terminal na imagem) e registrar a taxa de quadros do vídeo, que é a resolução da medida. Medir o tempo do envio até o robô parar. Guardar o log DEBUG dos intervalos do `move`.
3. Conectar `GO2_LIDAR_MAX_CLIENTS` clientes ao `/ws/lidar` e repetir o passo 2.
4. Se houver queda de conexão durante uma repetição, descartar essa repetição: a reconexão trava o loop por motivo alheio à feature.
5. Comparar com os limites de A13/A14. Registrar vídeo, log e commit.

## Histórico
- 2026-11-17: criada (proposta). Decisões do humano:
  - frames de pontos float32, decodificados na api;
  - primeiro consumidor: visualização;
  - escopo: LiDAR com a infraestrutura mínima de stream;
  - decodificação fora do event loop;
  - LiDAR antes da telemetria (inverte §5 da arquitetura);
  - se o repasse sem patch falhar, revisar a spec em vez de abandonar a feature.
- 2026-11-17: **regra alterada pelo F-002**: o LiDAR é ativado e decodificado com cliente em `/ws/lidar` **ou** em `/ws/telemetry` (refcount comum). "Sem clientes" passa a significar sem cliente em nenhuma das duas rotas. Falha na ativação continua fechando o `/ws/lidar` com `1011`; a telemetria fica aberta.
- 2026-11-17: decisões do humano: `MAX_CLIENTS=1`, filas `2`, `disableTrafficSaving(False)` ao sair o último cliente, A13 0,2–0,4 s. Limites de A8/A14 sugeridos pelo Claude (10% do período sobre a linha de base, teto 2× o período), pendentes de aceite.

  Revisada pelo `spec-reviewer`: mecanismo de decodificação definido, worker único com fila limitada, estado `reconnecting`, ativação com casos de corrida e falha, `balance_stand` e linha de base no roteiro, instrumentação do `move`.
- 2026-11-17: A12 (≤ 5 cm, meta 1 cm) definido; A13 confirmado; A8/A14 aceitos. Sem decisões pendentes; pronta para `implement-spec`.
- 2026-11-17: implementada em `feat/ws-lidar` (em-implementacao). A1–A11 passam em teste automático, com dublês e com a classe real de data channel da lib em A3; nada disso prova comportamento no robô. A12–A14 pendentes (H1/H2).
