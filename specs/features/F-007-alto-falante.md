---
id: F-007
titulo: Tocar áudio no alto-falante sem guardar no robô (/speaker/*)
tipo: comportamento
status: proposta
servicos: [api]
verificacao: inferido
verificado-em: null
depende-de: [F-004, F-005]     # tópico speaker no /ws/state (F-004); volume em /device/volume (F-005)
---

# F-007 — Tocar áudio no alto-falante sem guardar no robô (`/speaker/*`)

## Objetivo
Tocar um WAV ou MP3 no alto-falante do Go2 na hora, pela conexão WebRTC, sem gravar nada no robô. Uso livre para quem clonar a api. A biblioteca de áudios guardados é a F-006.

Base: exemplo `examples/go2/audio/mp3_player/play_mp3.py` do repositório do legion (`MediaPlayer` + `conn.pc.addTrack`). No código, a lib 2.2.0 (`WebRTCAudioChannel`) negocia um transceiver de áudio `sendrecv` a cada conexão.

## Comportamento

### Rotas

| Rota | O que faz | Resposta |
|---|---|---|
| `POST /speaker/play` (multipart: `file`) | Começa a tocar o arquivo | `202` `{"playback_id", "name", "duration_s"}` |
| `POST /speaker/stop` | Para o que estiver tocando | `202` `{"state": "idle"}` (também quando nada tocava) |
| `GET /speaker` | O que está tocando | `200` `{"state", "playback_id", "name", "started_at", "duration_s"}` |

- `state`: `idle` ou `playing`. Ao acabar o arquivo, volta sozinho a `idle`.
- O `/ws/state` (F-004) ganha o tópico `speaker`, com o conteúdo do `GET /speaker`, a cada mudança, pelo caminho sem descarte (como `errors`).
- `POST /audio/silence` (F-006) também para o alto-falante.

### Como toca
Verificado no código do aiortc 1.15.0 instalado (`rtcrtpsender.py`, `rtcpeerconnection.py`), não no robô:
- `addTrack` reaproveita o transceiver de áudio existente e chama `sender.replaceTrack(track)`, sem renegociar.
- O laço de envio do sender (`_run_rtp`) **termina de vez** quando a track lança `MediaStreamError` (fim do arquivo). Uma track nova depois disso não seria enviada.
- Com o sender sem track, o laço espera em silêncio (`sleep(0.02)`). A codificação (Opus) roda num executor, fora do event loop.

Por isso a api **não troca a track a cada arquivo**:
1. No primeiro `play` de uma conexão, a api põe no transceiver de áudio uma **track própria e persistente**, que nunca termina.
2. Ociosa, essa track entrega silêncio em tempo real: quadros de 20 ms, 48 kHz, estéreo, 16 bits.
3. Tocando, ela entrega os quadros do arquivo atual e, quando ele acaba, volta ao silêncio e muda o estado para `idle`.
4. A track fica até a conexão cair. Com a conexão nova, o próximo `play` põe a track de novo.

O manuseio da conexão (transceiver, sender) fica em `app/robot/unitree.py`.

**O arquivo é decodificado inteiro antes de tocar**, numa thread (PyAV, sem `ffmpeg` instalado), para PCM de 48 kHz, estéreo, 16 bits, em memória. Não há player em thread durante a reprodução nem arquivo temporário: o upload fica em memória e é descartado depois da decodificação.

### Um áudio por vez, sem corrida
- Um `play` novo substitui o atual. A troca é feita entre dois quadros pela track persistente.
- Cada `play` e cada `stop` recebe um número de ordem. Um `play` só começa a tocar se nenhum `stop` ou `play` mais novo chegou enquanto ele decodificava. Assim:
  - um `stop` que chega durante a decodificação de um `play` cancela esse `play` (que termina sem tocar; o `GET /speaker` fica `idle`);
  - entre dois `play` simultâneos, vale o último aceito.
- **Conexão que cai:** o áudio para, o estado vai a `idle`, e nada volta a tocar sozinho depois da reconexão.

### Validação (antes de tocar)
- Upload lido em streaming até `GO2_AUDIO_MAX_UPLOAD_MB` (o mesmo limite da F-006); acima disso, `413`.
- WAV ou MP3, detectado pelo conteúdo e decodificável: senão, `415`.
- Sem conexão: `503`.
- `duration_s` vem da decodificação (número de amostras ÷ taxa).

### `/capabilities`
Não muda (decisão do humano): as rotas ficam no OpenAPI e no README da api.

### Contrato
`specs/contracts/api.openapi.json` regenerado; o tópico `speaker` entra em `specs/contracts/ws-state.md`; `api/docs/arquitetura_go2_api.md` §4.3 atualizado.

## Critérios de aceite

| ID | Critério (observável) | Como verificar | Tipo | Verificação |
|---|---|---|---|---|
| A1 | `POST /speaker/play` com um WAV gerado no teste → `202`; a track persistente passa a entregar os quadros do arquivo (comparados com o PCM decodificado), e `GET /speaker` mostra `playing`, com nome e duração | teste com conexão fake | software | inferido |
| A2 | O mesmo com um MP3 gerado no teste | teste | software | inferido |
| A3 | Ociosa, a track entrega silêncio no ritmo de 20 ms (±5 ms em média por 1 s, relógio real); ao acabar o arquivo, volta ao silêncio, o estado vai a `idle` e o `/ws/state` envia `speaker` | teste | software | inferido |
| A4 | Um segundo `play` substitui o primeiro na track; `stop` volta ao silêncio e ao `idle`; `stop` sem nada tocando → `202` | teste | software | inferido |
| A5 | Com a decodificação de um `play` segurada por um evento do teste, um `stop` enviado nesse meio-tempo faz o `play` terminar sem tocar (`idle`); entre dois `play` com a decodificação segurada, toca o último aceito | teste com evento controlado | software | inferido |
| A6 | Com um par `RTCPeerConnection` real do aiortc em loopback, no processo do teste, com transceiver de áudio `sendrecv` como a lib: tocar um arquivo curto, esperar acabar, tocar outro. Chegam pacotes RTP de áudio do outro lado durante os dois | teste de integração | software | inferido |
| A7 | A conexão caindo durante a reprodução → `idle`; depois da reconexão, nada toca e o próximo `play` põe a track na conexão nova | teste | software | inferido |
| A8 | Arquivo acima do limite → `413`; formato inválido → `415`; sem conexão → `503`; nesses casos a track não muda | teste | software | inferido |
| A9 | A decodificação de um MP3 do tamanho máximo não roda na thread do event loop, e `POST /commands/stop` responde durante ela em menos de 100 ms | teste | software | inferido |
| A10 | Com o robô real: um WAV e um MP3 tocam no alto-falante do Go2; `stop` corta o som; um `play` durante outro troca o som. Registrar o atraso do `play` ao som e a qualidade | roteiro | hardware-only | inferido |
| A11 | Com o robô real, `PUT /device/volume` (F-005) muda o volume do que a F-007 toca. Registrar se muda | roteiro | hardware-only | inferido |
| A12 | Com o robô real, durante a reprodução de um áudio de ~30 s, o tempo entre `POST /commands/stop` e o robô parar, num `move`, tem mediana no máximo 0,2 s acima da mediana da linha de base sem áudio, e nenhuma repetição passa 0,4 s acima dela. Régua e protocolo do F-001 A13 | roteiro | hardware-only | inferido |
| A13 | Com o robô real, tocar um áudio da F-006 e um da F-007 ao mesmo tempo. Registrar o que se ouve | roteiro | hardware-only | inferido |

## Fora de escopo
- Tocar de URL (rádio, streaming): a api passaria a buscar endereços arbitrários na rede.
- Microfone do robô (`/ws/audio`): decisão do humano, 2026-11-21.
- Fila, mixagem ou mais de um áudio ao mesmo tempo pela F-007.
- Coordenar com microfone de outros serviços (eco): fica com quem integra.

## Segurança
- Nenhum movimento novo.
- Tocando, a api manda ~50 pacotes de áudio por segundo pelo mesmo link do `move` e do `stop`. Depois do primeiro `play`, manda silêncio até a conexão cair. A codificação roda num executor, mas o envio RTP e a track rodam no event loop. O custo é medido em A12.
- Som alto de repente: o volume é o do robô (F-005); por padrão sem teto. `POST /speaker/stop` e `POST /audio/silence` calam.

## Impacto HRI

| Pergunta | Resposta |
|---|---|
| Que interação da pessoa com o robô isto muda? | O robô passa a tocar um som na hora em que um cliente pede. |
| O que a pessoa percebe em sucesso, rejeição, erro e espera? | Perto do robô: o som começando, sendo trocado ou cortado. Rejeição e erro não fazem som: o retorno é só para quem chamou. |
| Latência percebida | Do `play` ao som: `inferido`; `TODO(humano): medir` (A10). |
| O retorno promete algo que o sistema não fez? | `202` é aceite: a api começou a enviar o áudio, sem garantia de que o robô o reproduziu. `playing` quer dizer "a api está enviando". |
| Pode surpreender ou assustar quem está perto? | Som inesperado e alto assusta, sobretudo criança. Eco num microfone de outro serviço fica com quem integra. |
| Quem usa? | Quem programa contra a api. Quem está perto do robô só ouve. |
| Como validar com uma pessoa que não conhece o sistema? | Sem critério `usuario`: a api não define o que tocar nem quando. |

## Hipóteses não verificadas
- Que o Go2 reproduz no alto-falante o áudio recebido pela track WebRTC (exemplo `play_mp3.py`). `TODO(humano): conferir` (A10).
- Que o robô aceita Opus 48 kHz estéreo (o aiortc negocia o codec).
- Que o volume do VUI (F-005) vale para esse áudio (A11).
- Que silêncio contínuo depois do primeiro `play` não incomoda o robô nem gasta muito link.
- O que acontece com F-006 e F-007 ao mesmo tempo (A13).
- Custo de CPU e efeito no `stop` (A12).

## Decisões
Tomadas (2026-11-21, humano):
- só tocar no alto-falante, sem microfone; uso livre; WAV e MP3;
- api independente do server e da TV Box;
- escritas `202`; `/capabilities` não muda;
- `POST /audio/silence` também para o alto-falante.

Tomadas pelo Claude (2026-11-22, a confirmar no relatório da rodada):
- rotas em `/speaker/*`, separadas de `/audio/*`;
- sem URL;
- track persistente com silêncio, em vez de trocar a track a cada arquivo;
- decodificar o arquivo inteiro antes de tocar;
- ordem por número para `play`/`stop`;
- régua do `stop` do F-001 (A12).

## Roteiro hardware-only
No roteiro único da rodada: [`specs/checklists/api-completa.md`](../checklists/api-completa.md).

## Histórico
- 2026-11-21: criada (proposta).
- 2026-11-22: revisada pelo `spec-reviewer` e com as decisões do humano. Mudanças:
  - track persistente, depois de verificar no aiortc que o envio termina no fim do arquivo;
  - corrida `play`/`stop` resolvida;
  - teste em loopback (A6);
  - decodificação em thread;
  - `202`;
  - dependências explícitas.
