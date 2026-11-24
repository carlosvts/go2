# Pegadinhas da `unitree_webrtc_connect` em uma tela

**Em uma frase:** a lib funciona, mas falha em silêncio em vários pontos. Antes de mexer em `app/robot/`, saiba destes.

> Ficha para quem vai mexer no código. Termos como *callback* e *event loop* estão no [glossário](glossario.md).

| # | Pegadinha | Consequência | O que fazer |
|---|---|---|---|
| 1 | `subscribe(topic, cb)` guarda **um** callback por tópico | Um segundo `subscribe` **substitui** o primeiro (ex.: mata o cache do `/status`) | Reaproveitar o callback existente |
| 2 | `unsubscribe(topic)` não remove o callback | O callback continua sendo chamado | `pub_sub.subscriptions.pop(topic, None)` |
| 3 | Com o canal fechado, `subscribe`/`publish_without_callback` só fazem `print` | Assinatura ou comando perdido, sem exceção | Checar `is_connected` antes |
| 4 | `publish` / `publish_request_new` **sem timeout** | `await` eterno se o robô não responder | Sempre `asyncio.wait_for` |
| 5 | Callbacks rodam **dentro do event loop** | Callback lento atrasa tudo, até o reenvio do `Move` | Callbacks curtos; trabalho pesado em `to_thread` |
| 6 | `isConnected` continua `True` no estado `failed` | Conexão morta parece viva | Checar também `data_channel_opened` (já feito) |
| 7 | Tudo é recriado a cada `connect()` | Assinaturas, callbacks e decoder somem | Refazer a configuração após conectar |
| 8 | Callbacks de vídeo rodam **em sequência** e recebem a track | Só o primeiro funciona | Registrar um callback só |
| 9 | Decoder de LiDAR padrão devolve malha | Sem pontos | `set_decoder("native")` |
| 10 | A track de vídeo é entregue **durante** o `connect()`; callback registrado depois não a recebe | Vídeo mudo | Interceptar a criação de `conn.video` (`VideoHookedConnection`, `unitree.py`) |
| 11 | Os erros do robô (`errors`, `add_error`, `rm_error`) só são impressos | A api não fica sabendo | Gancho no `handle_response` do data channel, a cada `connect()` (F-004) |
| 12 | No aiortc, o envio de áudio **termina de vez** quando a track de um arquivo acaba | O próximo áudio sai mudo | Uma track própria que nunca termina e manda silêncio quando ociosa (`SpeakerTrack`, F-007) |
| 13 | `WebRTCAudioHub` sem timeout, upload só por caminho de arquivo e MP3 via pydub (exige `ffmpeg`) | Envio trava ou falha sem `ffmpeg` | Protocolo copiado em `unitree.py` com timeout por bloco; MP3 convertido com PyAV (F-006) |

## Mais detalhes

[`lib_unitree_webrtc_connect.md`](../lib_unitree_webrtc_connect.md), com as linhas do código-fonte de cada item.

## Termos desta ficha

- **Callback**: Função entregue a alguém para ser chamada depois, quando algo acontecer.
- **Event loop**: O "motor" do `asyncio`: executa as tarefas da API uma de cada vez. Se uma demora, todas esperam.
- **Subscribe / unsubscribe**: Assinar / cancelar a assinatura de um tópico (passar a receber / parar de receber as mensagens).
- **Timeout**: Limite de tempo de espera. Passou do limite, desiste com erro.
- **`await` / `wait_for` / `to_thread`**: `await`: esperar uma tarefa assíncrona. `wait_for`: esperar com timeout. `to_thread`: rodar algo pesado fora do event loop.
- **Data channel**: Canal de mensagens dentro da conexão WebRTC (comandos, estado, LiDAR).
- **Cache**: Cópia guardada em memória do último dado recebido, para responder rápido sem perguntar de novo ao robô.
- **Decoder**: O código que transforma o dado comprimido que chega do robô em algo utilizável.
