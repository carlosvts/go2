---
id: F-003
titulo: Stream de vídeo da câmera frontal em JPEG (/ws/video)
tipo: comportamento
status: em-implementacao
servicos: [api]
verificacao: testado-software
verificado-em: null
depende-de: [F-001]            # mesmo estilo de stream; cria o contrato specs/contracts/ws-video.md junto com a implementação
---

# F-003 — Stream de vídeo da câmera frontal em JPEG (`/ws/video`)

## Objetivo
Dar a clientes da api acesso contínuo à imagem da câmera frontal do Go2, por WebSocket binário, sem que eles precisem de WebRTC nem de decodificador de H.264. O primeiro consumidor é **visualização no lab**: ver a imagem e avaliar o que a câmera entrega (resolução, taxa, qualidade). Uso por modelo de visão no `server/` é outra feature, com spec própria.

Corresponde à issue carlosvts/go2-api#4 (`api/docs/arquitetura_go2_api.md` §4.5). Segue o estilo do `/ws/lidar` (F-001): mesmo laço de WebSocket, frame de texto de estado da conexão, frame binário com cabeçalho versionado, refcount, filas curtas que descartam o mais antigo e trabalho pesado fora do event loop.

## Comportamento

### De onde vem o vídeo (lido no código da lib 2.2.0 e do aiortc 1.15.0, não visto no robô)
- A cada `connect()` a lib cria uma conexão nova (`UnitreeConnectionFactory` devolve um objeto novo; `conn.video` é recriado em `init_webrtc`) e negocia **uma track de vídeo** (`addTransceiver("video", direction="recvonly")`).
- A câmera liga/desliga por `switchVideoChannel(True/False)`, que publica `"on"`/`"off"` no data channel **sem resposta** (`publish_without_callback`).
- O aiortc decodifica o H.264 numa thread própria e entrega quadros já decodificados (`av.VideoFrame`) pela track. A fila interna da track (`RemoteStreamTrack._queue`) **não tem limite**: quadro que ninguém lê fica em memória.
- No evento `track`, **durante** o `connect()`, a lib descarta o 1º quadro e chama os callbacks de `conn.video` **em sequência, com `await`**. Callback registrado depois disso não recebe a track daquela conexão; callback que não retorna impede os seguintes.

Consequências que a api precisa cumprir:
- **Captura da track a cada conexão**, inclusive reconexão, confinada a `app/robot/unitree.py` (única fronteira com a lib), sem patch na lib. O callback só entrega a track à api e retorna; o laço de leitura roda numa task própria. Existe **um único leitor por track**.
- **Leitura contínua da track** enquanto ela existir: a api consome todo quadro que o aiortc entrega, com ou sem cliente, e descarta o que não vai usar. Assim a fila da track não cresce.
- **Fim da track** (`MediaStreamError` no `recv()`, ou conexão fechada): o leitor termina sem erro; a próxima conexão traz track e leitor novos.

### Conexão
- Rota: `GET /ws/video` (upgrade para WebSocket). Sem autenticação: fora de escopo (AGENTS.md raiz).
- A api sempre aceita o upgrade antes de qualquer fechamento (o cliente recebe o código, não um HTTP 403).
- Ao aceitar, a api envia um frame de texto `connection` com o estado atual da conexão com o robô (igual ao F-001) e, se a câmera estiver ativa, o estado `video` atual. Com o robô fora do ar o cliente fica conectado esperando.
- Com pelo menos um cliente, o robô `connected` e a câmera ativa, a api envia **um frame binário por quadro codificado**, respeitando os descartes descritos abaixo.
- O cliente não envia nada; a api ignora o que vier dele.
- Restrição: um processo só (sem `uvicorn --workers`), como no F-001.

### Câmera ativa
"Câmera ativa" = a api chamou `switchVideoChannel(True)` nesta conexão e ainda não chamou `False` nem fechou os clientes com `1011`. Só com a câmera ativa há quadros admitidos, `seq` novo e frames `video`.

### Frame binário (versão 1)
Little-endian, cabeçalho de 32 bytes, seguido do JPEG.

| Offset | Tipo | Campo | Significado |
|---|---|---|---|
| 0 | u8 | `version` | `1`. Versão desconhecida: o cliente descarta o frame. |
| 1 | u8 | `flags` | `0`; reservado. |
| 2 | u16 | `header_len` | `32`. O JPEG começa em `header_len`. |
| 4 | u32 | `seq` | Contador da api: +1 a cada quadro **admitido** (câmera ativa, com cliente, passou o teto de taxa), comum a todos os clientes. Volta a 0 depois de 2³²−1 e quando a api reinicia. Buraco = quadro admitido e descartado depois (fila do codificador, erro de codificação ou fila do cliente); a causa está nos contadores da api (ver "Contadores"). |
| 8 | f64 | `ts` | Instante em que a api leu o quadro da track (Unix, segundos). Não é o instante da captura no robô. |
| 16 | u16 | `width` | Largura do quadro em pixels, como o aiortc entregou. |
| 18 | u16 | `height` | Altura em pixels. |
| 20 | u32 | `jpeg_len` | Tamanho do JPEG em bytes. Frame = `header_len + jpeg_len`. |
| 24 | f64 | `media_time` | Tempo do quadro na track (`frame.time`, segundos, relógio RTP do robô, origem arbitrária). `NaN` se o aiortc não informar. Serve para medir a taxa e o intervalo no robô, não para comparar com `ts`. |
| 32 | bytes | `jpeg` | Imagem JPEG (baseline, cor) na resolução original do quadro. |

- Resolução: a do quadro recebido, sem redimensionar. O dossiê diz 1280×720; não foi visto no robô.
- Qualidade do JPEG: `GO2_VIDEO_JPEG_QUALITY` (inteiro 1–100; fora disso a api não sobe).
- Codificador: **PyAV** (codec `mjpeg` do FFmpeg que vem dentro do PyAV), sem OpenCV nem bibliotecas de sistema. `GO2_VIDEO_JPEG_QUALITY` (1–100) vira o `qscale` do MJPEG de forma linear (100 → 2, 1 → 31); não é a mesma escala do libjpeg. Até 2026-11-22 era `cv2.imencode`, escolha do Claude que quebrou a imagem Docker (o `opencv-python` exige `libxcb`/`libGL`); trocado a pedido do humano.

### Teto de taxa
- `GO2_VIDEO_MAX_FPS` (número ≥ 0; negativo: a api não sobe). A api admite um quadro quando passou pelo menos `1 / GO2_VIDEO_MAX_FPS` segundos desde o último admitido, por **relógio monotônico** (`ts` fica só no cabeçalho). Os outros quadros são lidos da track e descartados sem codificar e sem `seq`.
- `0` = sem teto: todo quadro lido com a câmera ativa e cliente presente é admitido.
- A taxa efetiva pode ficar abaixo do teto: com a câmera a 30 fps e teto 20, o intervalo mínimo de 50 ms admite 1 quadro a cada 2, ou seja, 15 fps.
- Quadros lidos **antes** da última chamada a `switchVideoChannel(True)` nunca são admitidos, para que `streaming` só apareça com quadro pedido agora.

### Codificação fora do event loop
A conversão do quadro para imagem (`to_ndarray`) e a codificação JPEG **não rodam na thread do event loop**.
1. A leitura da track (no loop) aplica o teto, atribui o `seq` e põe o quadro numa **fila de entrada do codificador** (`GO2_VIDEO_ENCODE_QUEUE`), que, cheia, descarta o mais antigo.
2. **Um único worker**, em thread fora do loop, converte e codifica em ordem.
3. O frame pronto vai para as filas dos clientes.
4. **Erro ao converter ou codificar** um quadro: o worker pula o quadro (buraco no `seq`), soma no contador de erros, registra em log e continua.
5. Quadro que termina de codificar depois de a câmera deixar de estar ativa é descartado sem envio.

Com um único worker, os frames saem na ordem do `seq`. Thread fora do loop não elimina a disputa de GIL e CPU; o efeito é medido em A14 (software) e A17/A18 (robô).

### Cliente lento (backpressure)
Cada cliente tem fila própria de frames binários (`GO2_VIDEO_CLIENT_QUEUE`). Cheia, a api descarta o frame **mais antigo** daquele cliente: o visualizador quer o quadro mais recente. Um cliente lento não atrasa os outros, o codificador nem o robô.

### Frames de texto
Mesmo envelope do F-001: `{"topic", "ts", "data"}`. Frames de texto **nunca são descartados** (caminho separado da fila binária).
- `connection`: `{"state": "connected" | "disconnected" | "reconnecting"}`, ao aceitar e a cada mudança, como no F-001.
- `video`: `{"state": "starting" | "streaming" | "stalled"}`, a cada mudança, só com a câmera ativa:
  - `starting`: a api acabou de chamar `switchVideoChannel(True)` (inclusive depois de uma reconexão) e ainda não houve quadro admitido. Só diz que a câmera foi **pedida**: o comando não tem resposta.
  - `streaming`: houve quadro admitido.
  - `stalled`: com a câmera ativa, passou `GO2_VIDEO_STALL_S` (relógio monotônico) sem nenhum quadro lido da track, contando desde o `True` ou do último quadro. Inclui a track que nunca chegou, a track que terminou e a câmera que não respondeu ao `True`. O WebSocket continua aberto; volta a `streaming` no próximo quadro admitido.
  - Fora de `connected` não há frame `video`: o estado da conexão já explica a ausência de quadros.

### Ativação da câmera no robô (refcount)
- **Gatilho:** pelo menos 1 cliente **e** robô `connected` (cobre o 1º cliente com o robô no ar e a volta do robô com clientes esperando). A api:
  1. garante `disableTrafficSaving(True)` pelo refcount comum (abaixo), com timeout `GO2_REQUEST_TIMEOUT_S`;
  2. chama `switchVideoChannel(True)` e manda `video: starting`.
- Com o robô fora do ar, a api não chama nada (o data channel está fechado; a lib só faria `print`, pegadinha #3 do F-001).
- Clientes que chegam com a câmera já ativa não disparam outra chamada.
- **Reconexão:** a track é nova; a api passa a ler a track nova, chama `switchVideoChannel(True)` de novo e manda `video: starting`, sem o cliente reconectar.
- **Último cliente sai:** a api chama `switchVideoChannel(False)` (decisão humana), esvazia a fila do codificador e continua drenando a track, se ainda vierem quadros. Sem clientes, nenhum quadro é admitido nem codificado. O `disableTrafficSaving(False)` segue o refcount comum.
- **Falha na ativação:**
  - `disableTrafficSaving(True)` com timeout, exceção ou resposta sem `info.execution == "ok"` (mesma regra do F-001), ou `switchVideoChannel(True)` lançando exceção: a api fecha os clientes de `/ws/video` com `1011` / `video_unavailable`, registra em log e não tenta de novo sozinha; um cliente novo dispara nova tentativa. Os clientes de `/ws/lidar` e `/ws/telemetry` seguem as regras deles (F-001/F-002).
  - Como `switchVideoChannel` não tem resposta, a falha mais provável é **silenciosa**: a câmera não manda quadro. O retorno ao operador é `video: stalled`. Junto, a api registra em log (WARNING) que a câmera está ativa sem quadros há `GO2_VIDEO_STALL_S`, com o total de quadros lidos da track nesta conexão. O visualizador mostra o estado e sugere reconectar o cliente.

### `disableTrafficSaving` comum com LiDAR e telemetria
O vídeo usa o mesmo data channel/pub-sub do LiDAR, então a api trata o `disableTrafficSaving` como **um só refcount** para as três rotas (decisão humana, 2026-11-21):
- `True` quando aparece o 1º cliente em qualquer de `/ws/lidar`, `/ws/telemetry` ou `/ws/video` com o robô `connected` (e de novo depois de cada reconexão), uma vez só enquanto houver cliente em alguma delas;
- `False` só quando não sobra cliente em **nenhuma** das três.

Isso **altera o F-001/F-002**: hoje o LiDAR chama `False` quando sai o último cliente de LiDAR/telemetria, o que cortaria o vídeo. A spec do F-001 ganha uma linha de histórico ("regra alterada pelo F-003") no mesmo commit da implementação, como o F-002 fez.

O resto é independente: a assinatura de `ULIDAR_ARRAY` (refcount do LiDAR) não muda por causa do vídeo, nem a de `LOW_STATE`/`SPORT_MOD_STATE` (`/status`). Vídeo e LiDAR ativos juntos são **permitidos e não medidos** (ver Segurança).

### Limite de clientes
Com `GO2_VIDEO_MAX_CLIENTS` clientes conectados, a api aceita o próximo e o fecha com `1013` / `max_clients`. `0` desliga a rota.

### Contadores
A api registra em log (INFO), a cada 1 s enquanto houver track, uma linha `video_metrics` com os totais da janela:
- quadros lidos da track;
- admitidos;
- descartados pelo teto;
- descartados na fila do codificador;
- erros de codificação;
- codificados;
- descartados na fila de cada cliente.

Sem cliente, a linha continua saindo se a track receber quadros. É assim que se vê se o robô manda vídeo com a câmera "desligada".

### Configuração (`.env`, todos customizáveis)

| Variável | Padrão | Origem |
|---|---|---|
| `GO2_VIDEO_MAX_CLIENTS` | `2` | humano (2026-11-21), para testar visualizador + gravador juntos |
| `GO2_VIDEO_CLIENT_QUEUE` | `1` | humano (2026-11-21) |
| `GO2_VIDEO_ENCODE_QUEUE` | `1` | humano (2026-11-21), "fila = 1" |
| `GO2_VIDEO_MAX_FPS` | `0` (sem teto) | ninguém mediu a taxa do robô; decidir depois do H1 |
| `GO2_VIDEO_JPEG_QUALITY` | `80` | sugerido pelo Claude, sem medida; decidir depois do H1 |
| `GO2_VIDEO_STALL_S` | `3` | sugerido pelo Claude, sem medida; aceito pelo humano (2026-11-21) |

### Instrumentação do lab
- `api/scripts/video_viewer.html`: mostra a imagem (Blob → `<img>`), o estado `connection`/`video` com o que fazer em `stalled`, fps recebido, `seq` e buracos, resolução e bytes/quadro.
- `api/scripts/ws_video_client.py`: conecta, valida o cabeçalho, decodifica cada JPEG e imprime por janela de 1 s: frames/s, bytes/quadro (mín./médio/máx.), resolução, JPEGs que não decodificaram, buracos no `seq`, atraso `received_at − ts`, intervalo de `media_time` e transições de estado. Abre o WebSocket com `max_size` explícito (o padrão de 1 MiB da `websockets` pode cortar JPEG grande).
- `api/scripts/record_video.py`: grava N segundos (ou N quadros) em disco: os JPEGs e um arquivo com o cabeçalho de cada um (`seq`, `ts`, `received_at`, `media_time`, tamanho). Grava por padrão em `gravacoes/` (já no `.gitignore`), nunca dentro do repo versionado.
- O log DEBUG do reenvio do `move` (F-001) continua valendo para o A18.

### Contrato
O formato do frame, os tópicos de texto e os códigos de fechamento vão para `specs/contracts/ws-video.md`, no mesmo commit da implementação. A tabela de `specs/contracts/README.md` ganha uma linha (dono `api`, consumidores os três scripts). O CI não confere contrato de WebSocket: só a revisão humana e o teste A1.

## Critérios de aceite

| ID | Critério (observável) | Como verificar | Tipo | Verificação |
|---|---|---|---|---|
| A1 | Dado um cliente e uma track fake que entrega um `av.VideoFrame` 1280×720 com um gradiente suave e um quadrado vermelho puro (RGB 255,0,0) em posição conhecida, então o cliente recebe um frame com `version=1`, `header_len=32`, `width=1280`, `height=720`, `jpeg_len` igual ao tamanho do corpo e `media_time` igual ao `frame.time` (ou `NaN` sem ele). O JPEG decodifica (PyAV, `mjpeg`) em 1280×720, com PSNR ≥ 30 dB contra a imagem original na qualidade padrão, e o centro do quadrado decodifica vermelho: R ≥ 200, G e B ≤ 60 | `tests/api/test_ws_video.py` | software | testado-software (2026-11-21 @ 548f89b) |
| A2 | `to_ndarray` e a codificação JPEG nunca rodam na thread do event loop. Rodam no máximo uma vez por quadro admitido e exatamente uma vez por quadro que sai da fila do codificador, sempre na mesma thread de worker | teste: funções instrumentadas registrando `threading.get_ident()` | software | testado-software (2026-11-21 @ 548f89b) |
| A3 | Um fake de conexão dispara o evento `track` **durante** o `connect()` e chama os callbacks em sequência com `await`, como a lib 2.2.0. A cada `connect()`, o callback da api retorna sem bloquear e a api passa a ler a track dessa conexão. Depois de 3 reconexões, há exatamente um leitor ativo, o da track mais nova | teste com fake de conexão | software | testado-software (2026-11-21 @ 548f89b) |
| A4 | Dados 0 clientes e robô `connected`: o 1º cliente dispara `switchVideoChannel(True)` uma vez; o 2º não dispara nada; quando ambos saem, `switchVideoChannel(False)` é chamado uma vez. Um quadro que estava no worker nesse momento termina e não é enviado, e nenhum quadro é admitido depois | teste com fake e worker controlado | software | testado-software (2026-11-21 @ 548f89b) |
| A5 | Dado o robô `disconnected`: o cliente recebe `connection: disconnected`, continua conectado e não há `switchVideoChannel`; quando o robô vai a `connected`, a ativação acontece e os frames começam | teste com fake link | software | testado-software (2026-11-21 @ 548f89b) |
| A6 | Dados clientes conectados, quando o robô passa por `reconnecting` → `connected`: cada cliente recebe as transições na ordem, o WebSocket não fecha, `switchVideoChannel(True)` é chamado de novo, cada cliente recebe `video: starting` e depois `streaming`, e os frames voltam sem o cliente reconectar | teste com fake link | software | testado-software (2026-11-21 @ 548f89b) |
| A7 | Com `GO2_VIDEO_MAX_FPS=F` (F>0) e uma track fake entregando quadros a 3F, com relógio monotônico controlado: em toda janela de 1 s são admitidos no máximo F quadros, os admitidos têm `seq` contínuo e todos os quadros são lidos da track. Com `0`, todo quadro é admitido. `GO2_VIDEO_MAX_FPS` negativo ou `GO2_VIDEO_JPEG_QUALITY` fora de 1–100 impedem a api de subir | teste com relógio fake; teste de config | software | testado-software (2026-11-21 @ 548f89b) |
| A8 | Com `GO2_VIDEO_MAX_CLIENTS=2` e `GO2_VIDEO_CLIENT_QUEUE=1`, dado um cliente que não lê e outro que lê, quando chegam mais quadros que a fila: o que lê recebe todos, com `seq` crescente; o lento recebe o mais recente, com buraco no `seq`; um frame `connection` emitido no meio chega aos dois | teste | software | testado-software (2026-11-21 @ 548f89b) |
| A9 | Dado um codificador mais lento que a chegada, a fila de entrada do codificador nunca passa de `GO2_VIDEO_ENCODE_QUEUE`, os frames saem com `seq` crescente e o descarte aparece como buraco e no contador da fila do codificador | teste com codificador fake lento | software | testado-software (2026-11-21 @ 548f89b) |
| A10 | Sem clientes e com a track entregando quadros, a api continua lendo a track (nunca há mais de 1 quadro pendente na fila da track fake), não admite nem codifica nenhum quadro, e a linha `video_metrics` mostra os quadros lidos | teste com track fake | software | testado-software (2026-11-21 @ 548f89b) |
| A11 | Com `GO2_VIDEO_MAX_CLIENTS` clientes, o próximo é aceito e fechado com `1013`/`max_clients`; com `0`, todo cliente recebe `1013` | teste | software | testado-software (2026-11-21 @ 548f89b) |
| A12 | Com o vídeo ativo, o `/status` continua atualizando `LOW_STATE`/`SPORT_MOD_STATE`, e a câmera não assina nem cancela `ULIDAR_ARRAY` | teste | software | testado-software (2026-11-21 @ 548f89b) |
| A12b | Refcount comum de `disableTrafficSaving`: (a) com clientes em `/ws/lidar` e `/ws/video`, o `True` é chamado uma vez; (b) saindo todos os de um deles, `False` não é chamado; (c) saindo o último das três rotas, `False` é chamado uma vez; (d) depois de uma reconexão com clientes, `True` é chamado de novo uma vez; (e) `disableTrafficSaving(True)` com timeout, resposta não `ok` ou exceção fecha os clientes de vídeo com `1011`/`video_unavailable`, sem nova tentativa automática. Os testes A4 e A7 do F-001 continuam passando | teste com fake pub_sub, um caso por item | software | testado-software (2026-11-21 @ 548f89b) |
| A13 | Estados `video`, um caso por transição:<br>(a) após a ativação, `starting`; no 1º quadro admitido, `streaming`;<br>(b) sem quadro lido por `GO2_VIDEO_STALL_S`, `stalled`, também quando a track nunca chega ou termina (`MediaStreamError`); no quadro seguinte, `streaming`;<br>(c) quadros lidos antes do `True` não produzem `streaming`;<br>(d) o WebSocket não fecha em nenhum desses casos;<br>(e) `switchVideoChannel(True)` lançando exceção fecha os clientes com `1011`/`video_unavailable`, sem nova tentativa automática;<br>(f) um quadro que faz a conversão ou o JPEG lançar exceção é pulado, conta no contador de erros e o próximo quadro é enviado | teste com relógio fake | software | testado-software (2026-11-21 @ 548f89b) |
| A14 | Com o worker codificando sem parar (fila de entrada sempre cheia; pior caso) quadros sintéticos 1280×720 e os frames sendo enviados a 2 clientes WebSocket que leem, o intervalo entre reenvios de um `move` simulado a `GO2_MOVE_RATE_HZ`: (a) no p99, desvia do nominal no máximo a linha de base sem vídeo + 10% do período; (b) nunca passa de 2× o período. Mesma régua do F-001 A8. Não cobre o RTP/SRTP do aiortc no loop: passar aqui **não prevê** A17/A18 | teste de carga (`slow`) | software | testado-software (2026-11-21 @ 548f89b) |
| A15 | Com o robô real, um cliente (`ws_video_client.py`) e a câmera ativa por 60 s: toda janela de 1 s tem ≥ 1 frame; 100% dos JPEGs recebidos decodificam; cada buraco no `seq` corresponde a um descarte contado no `video_metrics` da api (fila do codificador, erro ou fila do cliente). Registrar resolução, frames/s, bytes/quadro, atraso `received_at − ts`, intervalo de `media_time` e CPU da api | roteiro H1 | hardware-only | inferido |
| A16 | Com o robô real, depois de o último cliente sair (`switchVideoChannel(False)`), o `video_metrics` da api mostra 0 quadros lidos da track em todas as janelas a partir de 2 s depois do `False`, por 30 s. Se não for 0, registrar a taxa: o robô continua mandando e o aiortc decodifica à toa | roteiro H1 | hardware-only | inferido |
| A17 | O tempo entre o `POST /commands/stop` e o robô parar, durante um `move`, com `GO2_VIDEO_MAX_CLIENTS` clientes no `/ws/video` e o LiDAR desligado, tem mediana no máximo 0,2 s acima da mediana da linha de base sem vídeo, e nenhuma repetição passa 0,4 s acima da mediana da linha de base (mesma régua do F-001 A13) | roteiro H2 (vídeo) | hardware-only | inferido |
| A18 | Durante um `move` com `GO2_VIDEO_MAX_CLIENTS` clientes no `/ws/video` (LiDAR desligado), o intervalo entre reenvios (log DEBUG): (a) no p99, desvia do nominal no máximo o p99 da linha de base sem vídeo + 10% do período; (b) nunca passa de 2× o período (mesma régua do F-001 A14) | roteiro H2 (log) | hardware-only | inferido |

Notas sobre os limites:
- **A14, A17 e A18** usam os limites do F-001, confirmados pelo humano para o vídeo em 2026-11-21. Não mudam depois de rodar o H2.
- **A17/A18** valem só para os `GO2_VIDEO_MAX_FPS` e `GO2_VIDEO_JPEG_QUALITY` usados no H2, que ficam registrados. Mudar esses padrões depois exige repetir o H2.
- **O PSNR e as faixas de cor de A1** são limiares de teste de software, sugeridos pelo Claude. Não afirmam nada sobre a câmera.
- **A15 e A16** checam existência, integridade e registro. A avaliação da imagem (nitidez, cor, se serve para o que o lab quer) é humana: fica em Resultados, sem limiar numérico.

## Fora de escopo
- Uso do vídeo pelo `server/` (visão, detecção, rastreamento) e qualquer decisão de movimento a partir da imagem.
- **Sinal perceptível de "câmera ligada"** (cor da lanterna do Go2): depende de uma rota de device que ainda não existe (carlosvts/go2-api#2/#3). Fica para spec própria; ver Impacto HRI.
- Vídeo + LiDAR ativos ao mesmo tempo **como cenário medido**: só depois de o A13/A14 do F-001 serem medidos. A api não impede a combinação.
- Repasse do H.264 original, reencodar em H.264, RGB cru, redimensionar, recortar.
- Gravação pela api (só o script do lab grava).
- Áudio (`WebRTCAudioChannel`), foto pelo `rt/api/videohub/request`, câmera RealSense.
- `TopicHub` genérico. O que é comum com o F-001/F-002 **é extraído** nesta feature (decisão humana): fila que descarta o mais antigo, cliente de stream, laço de `serve` e o refcount de `disableTrafficSaving`.
- Autenticação e lease (AGENTS.md raiz). Patch na `unitree_webrtc_connect`.

## Segurança
- **Nenhum comando de movimento novo.** A feature só lê.
- **Risco principal: atrasar o `stop` e o reenvio do `move`.** O vídeo divide com eles o event loop e o link WebRTC. Isso vale também para `python -m sense.stop`, que usa o mesmo `POST /commands/stop`.
  - O vídeo é provavelmente o stream de mais banda (inferido).
  - Ao contrário do LiDAR, os quadros chegam por RTP/SRTP. O aiortc processa os pacotes no event loop, e só a decodificação roda em thread. Esse custo não está no A14.
- **Mitigação:**
  - conversão e JPEG fora do loop (A2);
  - câmera ligada só com cliente (A4), e verificação de que o robô para de mandar (A16);
  - leitura contínua da track, sem fila crescendo (A10);
  - filas limitadas (A8, A9) e teto de taxa (A7);
  - medida sob carga (A14) e no robô (A17, A18).
- **Régua:** a feature pode aumentar o tempo de parada até o limite de A17. Passou: não é adotada.
- O dado informal do F-001 (reenvio do `move` até 76 ms com o LiDAR ativo e o A8 passando) mostra que um stream pesado pode afetar o `move` mesmo com o teste de software aprovado. Até A17/A18 passarem, **não mover o robô com o vídeo ativo** fora do roteiro H2. Isso vale também com vídeo e LiDAR juntos.
- O visualizador só mostra a imagem: não tem nenhum controle do robô.
- Se o robô mandar vídeo mesmo sem `True` ou depois do `False` (A16), o custo de decodificação vale para a api toda, também quando a voz manda `move`. Isso também contamina a linha de base do H2. Nesse caso a spec é revista antes do H2.

## Impacto HRI

| Pergunta | Resposta |
|---|---|
| Que interação da pessoa com o robô isto muda? | Nenhuma interação por voz ou gesto. Muda que **a câmera do robô passa a transmitir** para um computador do lab enquanto houver cliente. |
| O que a pessoa percebe em sucesso, rejeição, erro e espera? | Quem está perto do robô provavelmente não percebe nada. **Inferido:** ninguém verificou se o Go2 tem indicador de câmera ou faz algum som ao ligar o vídeo (`TODO(humano): verificar`, H1.2). Quem opera o visualizador vê os estados `connection`/`video` (`starting`, `streaming`, `stalled`) com o que fazer em `stalled`, nunca tela parada sem explicação. |
| Latência percebida | Não se aplica à interação por voz. Atraso da imagem no visualizador: `inferido`; `TODO(humano): medir` (H1.7). |
| O retorno promete algo que o sistema não fez? | `starting` só diz que a api pediu a câmera (o comando não tem resposta); `streaming` só aparece com quadro de fato recebido depois do pedido (A13c). |
| Pode surpreender ou assustar quem está perto? | **Privacidade:** a pessoa pode estar sendo filmada sem saber, porque nada no robô indica câmera ligada. Sem autenticação, qualquer máquina na rede do lab que alcance a api pode abrir o `/ws/video` (até `GO2_VIDEO_MAX_CLIENTS`). Regra de uso até existir o sinal (aceita pelo humano, 2026-11-21): avisar as pessoas no lab antes de ligar o vídeo e não gravar quem não foi avisado. Risco indireto, de segurança: atraso do `stop` (A17). O robô não emite som, então não há eco no microfone. |
| Quem usa? | A equipe do lab, no visualizador. Leigos, crianças e plateia só aparecem **na imagem**: são filmados, não usam. |
| Como validar com uma pessoa que não conhece o sistema? | Sem critério `usuario` nesta spec: não há retorno a quem está perto do robô. A spec futura da lanterna terá um ("a pessoa percebe que está sendo filmada"). |

Pedido do humano (2026-11-21): quando existir a rota de device para a cor da lanterna, especificar uma cor para "câmera transmitindo". `TODO(humano)`: abrir a spec da lanterna depois da rota de device.

## Hipóteses não verificadas
- Resolução 1280×720 (dossiê). `TODO(humano): medir` (H1).
- Taxa de quadros da câmera pelo WebRTC. `TODO(humano): medir` (H1); define `GO2_VIDEO_MAX_FPS`.
- Se o robô manda vídeo **antes** do `True` (desde o `connect()`) e se para com o `False`. Lido no código; `TODO(humano): verificar` (H1.1, A16).
- Que a track chega a cada conexão mesmo com a câmera desligada (o transceiver é negociado no `connect`). Lido no código.
- Se o vídeo de fato precisa de `disableTrafficSaving(True)`. A api chama de qualquer forma, pelo refcount comum (decisão humana); não se verificou se sem ele os quadros chegam.
- Que `frame.time` vem preenchido nos quadros do Go2.
- Quanto da codificação MJPEG do PyAV solta o GIL (o A14 passou: p99 1,13 ms com vídeo contra 1,93 ms de base, 1 339 JPEGs em 3 s nesta máquina).
- Custo de CPU da decodificação H.264 (thread do aiortc), do RTP/SRTP no loop e da codificação JPEG na máquina da api. `TODO(humano): medir` (H1, `top`).
- Tamanho do JPEG por quadro na qualidade padrão (provavelmente < 1 MiB a 1280×720, inferido).
- Atraso câmera → visualizador. `TODO(humano): medir` (H1.7).
- Se o Go2 indica de alguma forma que a câmera está transmitindo (luz, som). `TODO(humano): verificar` (H1.2).
- Efeito no `stop`/`move` (A17/A18).
- **Pausas do GC do Python** na api real. Na suíte completa, o teste de carga do F-002 (A15) passou a falhar em cerca de metade das execuções com os testes de vídeo coletados (picos de 66–77 ms no reenvio do `move`, para período de 33 ms). Com o GC desligado ou com `gc.freeze()` antes da medida, passou em todas. Causa provável: mais objetos no heap (OpenCV, av, lixo de testes anteriores) e pausas maiores do coletor. Os testes de carga agora isolam o heap antes de medir (limites inalterados). A api real também carrega o OpenCV: o efeito do GC lá não foi medido. `TODO(humano): medir` (H2, A17/A18).

## Decisões

Tomadas (2026-11-21, humano):
- JPEG por quadro; primeiro consumidor: visualização no lab.
- Teto de taxa e qualidade configuráveis; resolução original.
- Filas e limites no `.env`; padrões para testar: 2 clientes, fila do cliente 1, fila do codificador 1.
- Desligar a câmera (`switchVideoChannel(False)`) quando o último cliente sai.
- Régua do `stop`/`move` igual à do LiDAR (F-001 A13/A14).
- Ferramentas: visualizador HTML, cliente de diagnóstico e gravador.
- Sinal de câmera ligada (lanterna): fora desta spec, depende da rota de device.
- `disableTrafficSaving` com refcount comum às três rotas (o vídeo é pub-sub como o LiDAR).
- Extrair agora o código comum com o F-001/F-002.
- Sem regra de teleoperação: o visualizador é só para ver.

- Privacidade: `GO2_VIDEO_MAX_CLIENTS=2` por padrão (rota ligada); regra de uso "avisar antes de ligar, não gravar quem não foi avisado".
- Ordem: `GO2_VIDEO_JPEG_QUALITY` e `GO2_VIDEO_MAX_FPS` fixados depois do H1; o H2 roda com eles. `GO2_VIDEO_STALL_S` = `3` s.
- Estados `video` `starting`/`streaming`/`stalled` (propostos pelo Claude, aceitos).

Pendentes (humano): nenhuma que bloqueie a implementação. Em aberto, sem proposta: por quanto tempo as gravações de `gravacoes/` ficam guardadas (`TODO(humano)`).

## Roteiro hardware-only

**Roteiro executável da sessão:** [`specs/checklists/F-003.md`](../checklists/F-003.md), com os comandos, as tabelas a preencher e os critérios de passa/falha. O resumo abaixo é a referência da spec.

Ordem: **H1 → humano decide `GO2_VIDEO_MAX_FPS` e `GO2_VIDEO_JPEG_QUALITY` → H2 com esses valores**.

Preparação comum: api com log DEBUG (`--log-config logging-debug.json`), `GO2_LIDAR_MAX_CLIENTS=0` e `GO2_TELEMETRY_MAX_CLIENTS=0` (LiDAR desligado), pessoas no lab avisadas de que a câmera vai transmitir. Registrar o commit e os valores de todas as `GO2_VIDEO_*`.

**H1 — imagem real (A15, A16 e hipóteses)**
1. Api recém-iniciada, robô `connected`, **nenhum cliente** de vídeo. Por 30 s, registrar os quadros lidos no `video_metrics` (o robô manda vídeo sem `True`?).
2. Abrir `scripts/video_viewer.html` e observar o robô: alguma luz ou som muda ao ligar a câmera? Registrar.
3. Rodar `uv run python scripts/ws_video_client.py` por 60 s. Registrar o que o A15 pede e conferir os buracos do `seq` com o `video_metrics`.
4. Se ficar em `stalled`: registrar o log da api (resposta do `disableTrafficSaving`, `video_metrics`), fechar e reabrir o cliente e registrar se a imagem chega.
5. Com o visualizador, avaliar a imagem (nitidez, cor, campo de visão, luz do lab). Registrar em texto.
6. Fechar todos os clientes. Conferir no log o `switchVideoChannel(False)` e o A16 (30 s de `video_metrics`). Reabrir um cliente e conferir que a imagem volta.
7. Filmar um cronômetro (tela de celular) com a câmera do robô ao lado da tela do visualizador; a diferença entre os dois é o atraso câmera → tela. Registrar 5 medidas.
8. Repetir o passo 3 com `GO2_VIDEO_JPEG_QUALITY` em 2 outros valores e, se a taxa medida pedir, com um `GO2_VIDEO_MAX_FPS`. Registrar bytes/quadro, CPU e a impressão da imagem, para o humano decidir os padrões.

**H2 — interferência no `stop`/`move` (A17, A18)**
Igual ao H2 do F-001 (`specs/features/F-001-ws-lidar.md`), trocando os clientes de LiDAR por `GO2_VIDEO_MAX_CLIENTS` clientes de `/ws/video` (visualizador + `ws_video_client.py`), com os padrões decididos depois do H1:
1. Linha de base: api reiniciada, nenhum cliente de vídeo desde o boot. Se o H1.1 mostrou que o robô manda vídeo sem `True`, não rodar o H2 (ver Segurança).
2. 10× `move` para a frente com `duration_s` 2 s e `POST /commands/stop` no meio, filmando com o envio visível no quadro; registrar a taxa de quadros do vídeo. Guardar o log DEBUG.
3. Conectar os clientes de vídeo e repetir o passo 2.
4. Repetição com queda de conexão é descartada.
5. Comparar com A17/A18 (`scripts/move_jitter.py`). Registrar vídeo, log, commit e os valores de `GO2_VIDEO_*`.

Área livre de pessoas e obstáculos no raio do `move`, uma pessoa com `python -m sense.stop` pronto, robô em `balance_stand`.

## Histórico
- 2026-11-21: criada (proposta). Decisões do humano: JPEG por quadro, visualização no lab, teto de taxa e qualidade configuráveis, padrões 2 clientes / filas 1 no `.env`, câmera desligada sem cliente, régua do `stop` igual à do LiDAR, três ferramentas de lab, lanterna fora de escopo.
- 2026-11-21: revisada pelo `spec-reviewer`. Mudanças:
  - A2 corrigido (no máximo uma vez por admitido);
  - contadores `video_metrics` e A16 (o robô para de mandar?);
  - A15 observável;
  - A14 inclui o envio a clientes e não prevê A17/A18;
  - ordem H1 → padrões → H2;
  - relógio monotônico, quadros anteriores ao `True` não admitidos, fim de track, erro no worker, leitor único por track;
  - privacidade sem barreira de rede.

  Seis pendências para o humano.
- 2026-11-21: decisões do humano: `disableTrafficSaving` com refcount comum a `/ws/lidar`, `/ws/telemetry` e `/ws/video` (altera o F-001/F-002; novo A12b); extrair o código comum agora; sem regra de teleoperação (o visualizador é só para ver). Pendentes: privacidade, ordem dos padrões, estados `video`.
- 2026-11-21: propostas aceitas pelo humano (privacidade com rota ligada e regra de uso, ordem H1 → padrões → H2, `STALL_S` 3 s, estados `video`). Sem pendências bloqueantes; pronta para `implement-spec`.
- 2026-11-21: implementada em `feat/ws-video` (`548f89b`, em-implementacao). Os critérios `software` (A1–A14 e A12b) passam em teste automático com dublês: track e data channel falsos, e a classe real `WebRTCVideoChannel` da lib no A3. Nada disso prova comportamento no robô. A14 (carga, máquina de desenvolvimento): p99 do desvio do `move` 1,1 ms com vídeo contra 1,9 ms de base, máx. 34,5 ms para período de 33,3 ms, ~1 370 JPEGs 1280×720 sintéticos em 3 s para 2 clientes. A15–A18 pendentes (H1/H2).
- 2026-11-21: roteiro executável criado em `specs/checklists/F-003.md` (H1 com o robô parado, decisão dos padrões, H2 com `move`/`stop`).
- 2026-11-22: JPEG com o PyAV (MJPEG) no lugar do OpenCV, que quebrava a imagem Docker. O `opencv-python` (dependência declarada pela lib, mas nunca importada) saiu da instalação por um override no `pyproject`. A1, A2 e A14 passam de novo (`133a8f1`).
