# `unitree_webrtc_connect` 2.2.0 — como a lib se comporta de verdade

> Referência para quem escreve código em `app/robot.py`. O conteúdo foi tirado
> da leitura do **fonte da versão 2.2.0**, a que está travada no `uv.lock`
> (wheel `unitree_webrtc_connect-2.2.0-py3-none-any.whl`). Os números de linha
> se referem a esse wheel.
>
> Se a versão no `uv.lock` mudar, revalide este documento.
> "**A confirmar**" marca o que o fonte não responde e precisa ser testado no robô.

Para entender a lib em alto nível (o que ela é e por que existe), veja
[`go2_modelo_mental.md`](go2_modelo_mental.md) §4. Para o mapa de tópicos, veja
[`dossie_go2.md`](dossie_go2.md) §12.

---

## 1. Estrutura de objetos

```
UnitreeWebRTCConnection          webrtc_driver.py
├── pc: RTCPeerConnection        (aiortc)
├── datachannel: WebRTCDataChannel        webrtc_datachannel.py
│   ├── pub_sub: WebRTCDataChannelPubSub  msgs/pub_sub.py
│   ├── heartbeat, validaton, rtc_inner_req
│   └── decoder: UnifiedLidarDecoder      lidar/
├── video: WebRTCVideoChannel     webrtc_video.py
└── audio: WebRTCAudioChannel     webrtc_audio.py
```

- **Tudo abaixo de `pc` é recriado a cada `connect()`**
  (`webrtc_driver.py:137-145`). Isso inclui assinaturas, callbacks e decoder:
  o que for configurado nesses objetos se perde numa reconexão e precisa ser
  refeito.
- `WebRTCAudioHub` (`webrtc_audiohub.py`) **não** é criado pela conexão e não é
  exportado no `__init__`. O import é
  `from unitree_webrtc_connect.webrtc_audiohub import WebRTCAudioHub`.

## 2. Em que thread os callbacks rodam

**Tudo roda na thread do event loop.** O aiortc entrega as mensagens do data
channel num handler `async` (`webrtc_datachannel.py:60-84`), e esse handler
chama, em sequência e de forma síncrona:

1. `pub_sub.run_resolve(msg)` → resolve futures pendentes e chama o callback
   do tópico (`msgs/pub_sub.py:18-26`);
2. `handle_response(msg)` → validação, heartbeat, erros.

Consequências:
- um callback de tópico pode chamar `asyncio.Queue.put_nowait` direto. Não
  precisa de `call_soon_threadsafe`;
- **um callback lento atrasa todo o data channel**, inclusive o reenvio do
  `Move` (`app/robot.py`, `_move_loop`). A decodificação do lidar já acontece
  aqui dentro (ver §6);
- exceções no callback são capturadas e logadas pela lib
  (`webrtc_datachannel.py:83-84`). Não derrubam nada, mas também não aparecem
  para quem chamou.

## 3. Pub/sub de tópicos (`msgs/pub_sub.py`)

| Método | O que faz de fato | Pegadinha |
|---|---|---|
| `subscribe(topic, cb)` (`:120-131`) | `self.subscriptions[topic] = cb` + envia `{"type":"subscribe","topic":...}` | **Um callback por tópico.** Um segundo `subscribe` no mesmo tópico **substitui** o primeiro, sem aviso. |
| `unsubscribe(topic)` (`:133-140`) | Só envia `{"type":"unsubscribe"}` | **Não remove o callback** de `subscriptions`. Para remover: `pub_sub.subscriptions.pop(topic, None)`. |
| `publish_without_callback(topic, data, type)` (`:64-84`) | `channel.send(json)` | Com o canal fechado, **não faz nada**: o código cria `Exception(...)` mas não faz `raise` (`:84`). |
| `publish(topic, data, type)` (`:29-61`) | Envia e aguarda o future da resposta | **Sem timeout.** Se o robô não responder, o future fica pendente para sempre em `FutureResolver.pending_callbacks`. |
| `publish_request_new(topic, options)` (`:87-118`) | Monta `header.identity` + `parameter` e chama `publish` | Mesmo problema: sem timeout. |

Também valem para todos os métodos acima:
- **com o canal fechado, `subscribe` e `unsubscribe` só fazem `print` e
  retornam** (`:123-125`, `:136-138`). O callback nem é registrado, e nenhuma
  exceção sobe;
- o callback recebe a mensagem inteira, `{"type", "topic", "data"}`. É o
  formato usado em `app/robot.py`, `_subscribe_state`.

**Regra para este repo:** `LOW_STATE` e `SPORT_MOD_STATE` já são assinados em
`RobotConnection._subscribe_state` para alimentar o `GET /status`. Qualquer
outro consumidor desses tópicos (por exemplo, o hub de WebSocket) precisa
**reaproveitar esses callbacks**, e não chamar `subscribe` de novo.

## 4. Estado da conexão

| Sinal | Onde | Quando muda |
|---|---|---|
| `conn.isConnected` | `webrtc_driver.py:171-183` | `True` em `connected`, `False` em `closed`. **Continua `True` em `failed`.** |
| `datachannel.data_channel_opened` | `webrtc_datachannel.py:30-57` | `True` depois da validação (`"Validation Ok."`), `False` no `close` do canal. |
| `heartbeat.heartbeat_response` | `msgs/heartbeat.py` | Timestamp da última resposta de heartbeat (enviado a cada 2 s). |

- A lib **não expõe callback de "caiu" ou "voltou"**. Para reagir, registre um
  handler próprio: `conn.pc.on("connectionstatechange", handler)`. O handler
  da lib, que só faz `print`, continua registrado.
- `conn.reconnect()` existe (`webrtc_driver.py:98-101`), mas cria `pc`,
  `datachannel`, `video` e `audio` novos (ver §1).
- `RobotConnection.is_connected` exige `isConnected` **e**
  `data_channel_opened`, o que cobre o caso `failed` assim que o canal fecha.
  **A confirmar no robô:** a ordem dos eventos e o tempo até a queda ser
  detectada.

## 5. Vídeo (`webrtc_video.py`, `webrtc_driver.py:197-216`)

- O vídeo chega como track WebRTC, não pelo pub/sub. Para ligá-lo:
  `conn.datachannel.switchVideoChannel(True)` (`webrtc_datachannel.py:183-190`).
- Quando a track chega, a lib descarta o primeiro quadro e chama
  `video.track_handler(track)` **uma única vez**.
- `track_handler` faz `await` de cada callback **em sequência**
  (`webrtc_video.py:25-33`). Cada callback recebe a **track** (não quadros) e
  precisa fazer o próprio loop `await track.recv()`. Por isso:
  - **registre um callback só.** Como o primeiro callback fica em loop até a
    track acabar, o segundo nunca roda;
  - não há como remover um callback.
- **Corrida:** `conn.video` só existe dentro de `conn.connect()`. Um callback
  registrado depois de `await conn.connect()` pode chegar tarde e perder a
  track. **A confirmar no robô.**
- Quadros: `av.VideoFrame`. O fim da track (`MediaStreamError`) é capturado
  pela lib.

## 6. LiDAR

- Tópico comprimido: `RTC_TOPIC["ULIDAR_ARRAY"]` = `rt/utlidar/voxel_map_compressed`.
- O decoder padrão é `libvoxel` (`webrtc_datachannel.py:28`), um binário WASM
  rodado via `wasmtime`. Ele devolve **malha de renderização**:
  `{"point_count","face_count","positions","uvs","indices"}`
  (`lidar/lidar_decoder_libvoxel.py:155-161`).
- Para obter **pontos**, sem patch na lib:

  ```python
  conn.datachannel.set_decoder("native")          # webrtc_datachannel.py:202-213
  await asyncio.wait_for(conn.datachannel.disableTrafficSaving(True), timeout)
  conn.datachannel.pub_sub.subscribe(RTC_TOPIC["ULIDAR_ARRAY"], on_lidar)
  ```

  No callback, `message["data"]["data"]` é `{"points": np.ndarray (N, 3)}` em
  metros (`points * resolution + origin`,
  `lidar/lidar_decoder_native.py:58-67`). O decoder lê `src_size`, `origin` e
  `resolution` do próprio `message["data"]`.
- O `set_decoder` precisa ser refeito **a cada `connect()`** (ver §1).
- `disableTrafficSaving` (`webrtc_datachannel.py:166-180`) usa `publish` e,
  portanto, também não tem timeout.
- **A decodificação roda dentro do event loop** (`webrtc_datachannel.py:126-163`),
  inclusive sem nenhum consumidor interessado, bastando o tópico estar assinado.
- `numpy.ndarray` não é serializável em JSON.
- **A confirmar:** se é preciso publicar `"on"` em `RTC_TOPIC["ULIDAR_SWITCH"]`
  (`rt/utlidar/switch`). O exemplo da lib não vem no pacote.

## 7. Áudio da biblioteca do robô (`webrtc_audiohub.py`)

- Todos os métodos usam `publish_request_new`, portanto **não têm timeout**.
- `upload_audio_file(path)` recebe um **caminho de arquivo**. MP3 é convertido
  com `pydub` (exige ffmpeg) para um `.wav` gravado ao lado do arquivo
  original. O envio é em blocos base64 de 4096 caracteres, com
  `sleep(0.1)` entre eles e um `print` de cada bloco. O `unique_id` gerado
  **não é devolvido**.
- Megafone são três chamadas: `enter_megaphone`, `upload_megaphone(path)` e
  `exit_megaphone`.
- api_ids em `AUDIO_API` (`constants.py:353-384`).

## 8. Constantes que importam

- `SPORT_CMD` (`constants.py:122-172`) e `SPORT_CMD_MCF` (`:174-222`) têm
  **espaços de ids diferentes para os mesmos nomes**. Exemplos: `BackFlip` vale
  1044 em um e 2043 no outro; `Handstand` vale 1301 em um e `HandStand` 2044
  no outro. O modo MCF existe desde o firmware 1.1.7. **A confirmar** qual
  espaço vale para o nosso robô antes de usar truques.
- `SPORT_CMD["FreeWalk"]` e `SPORT_CMD["LeadFollow"]` têm o **mesmo id**, 1045.
- `OBSTACLES_AVOID_API` (`:224-231`): `SWITCH_SET` 1001 `{"enable": bool}` e
  `SWITCH_GET` 1002. Os payloads só aparecem em comentário.
- **VUI:** só existem `RTC_TOPIC["VUI"]` e `VUI_COLOR` (`:343-350`). **Não há
  api_ids de volume, brilho ou LED nesta versão.** Os ids 1003–1007 citados no
  dossiê vêm de um exemplo upstream que não está no pacote, e ficam a confirmar.
- `rt/api/sport_lease/request` **não** está em `RTC_TOPIC`.

## 9. Instalação

`uv sync` compila o `pyaudio`, que precisa dos headers do PortAudio
(`portaudio-devel` no Fedora, `portaudio19-dev` no Debian/Ubuntu). A lib também
depende de `sounddevice`, `opencv-python`, `pydub` e `wasmtime`.

---

## Glossário deste documento

| Termo | Significado |
|---|---|
| **aiortc / aioice** | Bibliotecas Python que implementam WebRTC e ICE. A lib do projeto é construída em cima delas. |
| **base64** | Forma de escrever dados binários como texto (usada para mandar arquivos dentro de JSON). |
| **Bloco (chunk)** | Pedaço de um arquivo grande enviado em partes. |
| **Callback** | Função entregue a alguém para ser chamada depois, quando algo acontecer. |
| **Decoder** | Código que transforma o dado comprimido que chega do robô em algo utilizável. |
| **Event loop** | O "motor" do `asyncio`: executa as tarefas uma de cada vez, numa única thread. Se uma demora, todas esperam. |
| **ffmpeg** | Programa de conversão de áudio e vídeo (o `pydub` precisa dele para MP3). |
| **Future** | Objeto que representa um resultado que ainda vai chegar. `await` espera por ele. |
| **JSON** | *JavaScript Object Notation*: formato de texto para dados, como `{"chave": "valor"}`. |
| **MCF** | *Multi-Control Framework*: modo de locomoção do Go2 com ids de comando próprios. |
| **MP3 / WAV** | Formatos de arquivo de áudio. |
| **ndarray / numpy** | numpy: biblioteca de cálculo numérico em Python. `ndarray` é a matriz dela. |
| **Pub/sub** | *Publish/subscribe*: quem produz dados publica num tópico; quem quer, assina e recebe. Um não conhece o outro. |
| **Thread** | Linha de execução. Duas threads rodam "ao mesmo tempo" no mesmo processo. |
| **Timeout** | Limite de tempo de espera. Passou do limite, desiste com erro. |
| **Tópico** | Nome de um canal de mensagens (ex.: `rt/api/sport/request`). |
| **Track** | Fluxo de mídia (vídeo ou áudio) dentro da conexão WebRTC. |
| **UUID** | Identificador único gerado aleatoriamente (ex.: o id de um áudio no robô). |
| **VUI** | Nome que a Unitree dá ao serviço de volume, brilho e LED do Go2 (o significado da sigla não está documentado na lib). |
| **WASM / wasmtime** | WebAssembly (WASM): formato de programa compilado e portátil. `wasmtime` roda WASM dentro do Python. |
| **WebGL** | Tecnologia de gráficos 3D do navegador. |
| **WebRTC** | *Web Real-Time Communication*: protocolo de comunicação em tempo real. É o túnel até o DDS do robô. |
