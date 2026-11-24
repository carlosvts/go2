---
id: F-006
titulo: Biblioteca de áudio do robô (/audio/*)
tipo: comportamento
status: em-implementacao
servicos: [api]
verificacao: testado-software
verificado-em: null
depende-de: [F-004, F-005]     # tópico audio_player no /ws/state (F-004); volume em /device/volume (F-005)
---

# F-006 — Biblioteca de áudio do robô (`/audio/*`)

## Objetivo
Gerenciar os áudios guardados no próprio Go2 e tocá-los: listar, enviar (WAV ou MP3), renomear, apagar, tocar, pausar, retomar, escolher o modo de reprodução e silenciar tudo. Uso livre para quem clonar a api. Tocar um arquivo sem guardá-lo no robô é a F-007.

Base: `api/docs/cobertura_lib.md` §5 e a classe `WebRTCAudioHub` da lib 2.2.0 (`webrtc_audiohub.py`; tópico `rt/api/audiohub/request`; `AUDIO_API` em `constants.py`).

## Comportamento

### Rotas

| Rota | `AUDIO_API` | `parameter` (string JSON, como a lib) | Resposta |
|---|---|---|---|
| `GET /audio/files` | `GET_AUDIO_LIST` 1001 | `{}` | `200` `[{"id", "name", "extra"}]` |
| `POST /audio/files` (multipart: `file`, `name`?) | `UPLOAD_AUDIO_FILE` 2001 | ver "Envio" | `202` `{"upload_id", "name", "total_chunks"}` |
| `GET /audio/uploads/{upload_id}` | — | — | `200` (ver "Envio") |
| `PATCH /audio/files/{id}` `{"name"}` | `SELECT_RENAME` 1008 | `{"unique_id", "new_name"}` | `202` |
| `DELETE /audio/files/{id}` | `SELECT_DELETE` 1009 | `{"unique_id"}` | `202` |
| `POST /audio/files/{id}/play` | `SELECT_START_PLAY` 1002 | `{"unique_id"}` | `202` |
| `POST /audio/pause` | `PAUSE` 1003 | `{}` | `202` |
| `POST /audio/resume` | `UNSUSPEND` 1004 | `{}` | `202` |
| `GET /audio/play-mode` | `GET_PLAY_MODE` 1010 | `{}` | `200` `{"mode"}` |
| `PUT /audio/play-mode` `{"mode"}` | `SET_PLAY_MODE` 1007 | `{"play_mode"}` | `202` `{"mode"}` |
| `POST /audio/silence` | `PAUSE` 1003 + `/speaker/stop` (F-007) | `{}` | `202` |
| `GET /audio/player` | tópico `AUDIO_HUB_PLAY_STATE` | — | `200` `{"data", "age_s"}`, cru |

- `id` é o `UNIQUE_ID` e `name` o `CUSTOM_NAME` de cada item de `json.loads(data.data)["audio_list"]` (exemplo `webrtc_audio_player.py`). Os outros campos do item vão em `extra`, sem interpretação.
- `mode`: `single_cycle`, `no_cycle` ou `list_loop` (docstring da lib); outro valor → `422`.
- `POST /audio/silence` pausa o hub **e** para o alto-falante da F-007, para quem está perto ter um jeito único de calar o robô (decisão do humano). Ele não toca no movimento. O `POST /commands/stop` continua só de movimento e não mexe no som.
- O `AUDIO_HUB_PLAY_STATE` é assinado a cada `connect()`, junto com os tópicos de estado da F-004, num callback próprio (um por tópico). O `/ws/state` ganha o tópico `audio_player`, com o `data` cru, sob as mesmas regras de taxa da F-004.

### Respostas e erros (mesmas convenções da F-005)
- Cada chamada usa `publish_request_new` com timeout `GO2_REQUEST_TIMEOUT_S`; a lib não tem timeout.
- **`202`** depois de `data.header.status.code == 0`: o robô **aceitou**. Em "tocar", isso não quer dizer que o áudio terminou.
- **`502`**: código ≠ 0, resposta sem `header.status` ou lista/modo malformados. **`503`**: sem conexão. **`504`**: sem resposta. Em `502`/`504`, o estado do robô é desconhecido.
- `id` inexistente: a api **não** consulta a lista antes (evita uma corrida e dobrar a latência). O robô responde, e código ≠ 0 vira `502`.

### Envio (`POST /audio/files`)
1. **Leitura:** o upload é lido em streaming. Se passar de `GO2_AUDIO_MAX_UPLOAD_MB`, a leitura para e a resposta é `413`.
2. **Formato:** WAV ou MP3, detectado pelo conteúdo. A api decodifica para conferir; arquivo que não decodifica leva `415`.
3. **Conversão:** igual à da lib, que converte só o MP3, para WAV PCM 16 bits a 44,1 kHz, mantendo os canais. A api converte com o PyAV, declarado como dependência direta, em vez do pydub da lib: não precisa do `ffmpeg` instalado. O WAV de entrada vai como veio. Decodificar e converter rodam numa thread, fora do event loop.
4. **Limite no que vai ao robô:** o WAV final também precisa caber em `GO2_AUDIO_MAX_UPLOAD_MB` (decisão do humano). Senão, `413` com o tamanho convertido no `detail`. Um MP3 pequeno pode virar um WAV grande.
5. **Nome:** `name` é o nome no robô. Sem ele, vale o nome do arquivo sem extensão. Depois de tirar os espaços das pontas, precisa ter de 1 a 64 caracteres, sem `/`, `\` nem caracteres de controle; senão, `422`. Nome que já existe na lista leva **`409`** (decisão do humano). A lista é consultada antes de aceitar.
6. **Um envio por vez:** com outro em andamento, `409`. As outras rotas do hub funcionam durante o envio.
7. A api responde `202` e envia em segundo plano, **no protocolo de `upload_audio_file` da lib** (`webrtc_audiohub.py`), copiado exatamente:
   - `file_md5`: MD5 dos bytes do WAV;
   - a string base64 do WAV é cortada em blocos de **4096 caracteres**;
   - para cada bloco `i` de 1 a N, um `publish_request_new` com `api_id` 2001 e `parameter = json.dumps(p, ensure_ascii=True)`, sendo `p` = `{"file_name": name, "file_type": "wav", "file_size": len(wav), "current_block_index": i, "total_block_number": N, "block_content": bloco, "current_block_size": len(bloco), "file_md5": md5, "create_time": ms_unix}`;
   - `asyncio.sleep(0.1)` entre blocos;
   - cada bloco tem timeout `GO2_REQUEST_TIMEOUT_S`, coisa que a lib não tem.

   O código fica em `app/robot/unitree.py`, a fronteira com a lib.
8. **Estado:** `GET /audio/uploads/{upload_id}` devolve `{"state", "name", "sent_chunks", "total_chunks", "file_id", "error"}`:
   - `state`: `uploading`, `done` ou `failed`;
   - `done` quando o último bloco teve `code == 0`. Aí a api lista de novo e põe em `file_id` o id que não existia antes do envio (`null` se não aparecer);
   - `failed` em timeout, código ≠ 0 ou queda, com o motivo em `error`.
9. **Conexão:** a api anota a conexão no começo do envio. Se ela mudar (caiu, ou caiu e voltou) antes do próximo bloco, o envio vira `failed` com `error: "disconnected"`. A api não retoma.
10. A api guarda os últimos 20 envios em memória; `upload_id` desconhecido leva `404`.

### Concorrência (decidido pelo Claude, a confirmar)
- Tocar, pausar, renomear e apagar durante um envio: permitido.
- Apagar o áudio que está tocando: o robô decide; a api repassa.
- Tocar um áudio da F-006 e outro da F-007 ao mesmo tempo: permitido. O resultado (mistura, um corta o outro) é observado no roteiro.

### `/capabilities`
Não muda (decisão do humano): as rotas ficam no OpenAPI e no README da api.

### Configuração (`.env`)

| Variável | Padrão | Origem |
|---|---|---|
| `GO2_AUDIO_MAX_UPLOAD_MB` | `5` | sugerido pelo Claude (`inferido`). Vale para o arquivo recebido e para o WAV enviado. 5 MB de WAV estéreo 44,1 kHz são ~30 s de áudio e ~1 700 blocos, ou seja, ≥ 3 min de envio |

### Contrato
`specs/contracts/api.openapi.json` regenerado; o tópico `audio_player` entra em `specs/contracts/ws-state.md`; `api/docs/arquitetura_go2_api.md` §4.3 atualizado.

## Critérios de aceite

| ID | Critério (observável) | Como verificar | Tipo | Verificação |
|---|---|---|---|---|
| A1 | Cada rota publica no tópico do hub o api_id e o `parameter` (string JSON) da tabela | teste com fake pub_sub | software | testado-software (2026-11-22 @ 29ad0cb) |
| A2 | `GET /audio/files` transforma `data.data` em `[{"id", "name", "extra"}]`; resposta malformada → `502`; códigos 502/503/504 como na F-005 | teste | software | testado-software (2026-11-22 @ 29ad0cb) |
| A3 | Envio de um WAV gerado no teste: `202`; concatenando o `block_content` de todos os blocos e decodificando de base64, sai exatamente o arquivo; o `file_md5`, o `total_block_number` e os índices (1 a N, em ordem) estão certos e cada bloco tem ≤ 4096 caracteres; o estado termina `done` com o `file_id` novo da lista | teste com fake pub_sub | software | testado-software (2026-11-22 @ 29ad0cb) |
| A4 | Envio de um MP3 gerado no teste: o que vai ao robô é WAV PCM 16 bits, 44,1 kHz, com os canais do original e a mesma duração (±50 ms) | teste | software | testado-software (2026-11-22 @ 29ad0cb) |
| A5 | Arquivo acima do limite → `413` sem ler o resto; MP3 abaixo do limite cujo WAV passa do limite → `413`; arquivo que não é WAV/MP3 ou corrompido → `415`; nome inválido → `422`; nome que já existe → `409`; segundo envio durante um em andamento → `409`. Nada é publicado no hub nesses casos (fora a consulta da lista) | teste, um caso por regra | software | testado-software (2026-11-22 @ 29ad0cb) |
| A6 | Bloco sem resposta em `GO2_REQUEST_TIMEOUT_S` → `failed`; conexão que cai e volta entre os blocos k e k+1 → `failed: disconnected`, sem publicar o bloco k+1 em nenhuma conexão | teste | software | testado-software (2026-11-22 @ 29ad0cb) |
| A7 | Durante um envio e durante a conversão de um MP3 do tamanho máximo, `POST /commands/stop` responde e é publicado em menos de 100 ms (teste de software, mesma máquina) | teste | software | testado-software (2026-11-22 @ 29ad0cb) |
| A8 | `PUT /audio/play-mode` com modo fora dos três → `422`; `POST /audio/silence` publica o `PAUSE` e para o alto-falante (F-007) | teste | software | testado-software (2026-11-22 @ 29ad0cb) |
| A9 | Com o robô real: enviar um WAV curto e um MP3 curto; os dois aparecem em `GET /audio/files`, tocam com `play`, pausam e retomam; renomear e apagar funcionam; `POST /audio/silence` cala o robô. Registrar o tempo de envio e o tamanho de cada um | roteiro | hardware-only | inferido |
| A10 | Com o robô real: `PUT /audio/play-mode` com cada modo e `GET` devolve o mesmo. Registrar o que cada modo faz e o que o `GET /audio/player` mostra parado, tocando e pausado | roteiro | hardware-only | inferido |
| A11 | Com o robô real, durante um envio de um WAV de ~1 MB (tamanho do que vai ao robô), o tempo entre `POST /commands/stop` e o robô parar, num `move`, tem mediana no máximo 0,2 s acima da mediana da linha de base sem envio, e nenhuma repetição passa 0,4 s acima dela. Régua do F-001 A13, com o mesmo protocolo: 10 repetições, api recém-reiniciada na linha de base, `balance_stand` antes | roteiro | hardware-only | inferido |
| A12 | Com o robô real, cortar a conexão (desligar o Wi-Fi da máquina da api) no meio de um envio: registrar se fica um arquivo parcial na lista | roteiro | hardware-only | inferido |

## Fora de escopo
- **Megafone** (`ENTER/UPLOAD/EXIT_MEGAPHONE`): tocar sem guardar é a F-007, por outro caminho; o protocolo do megafone (quando chamar o `exit`) não é conhecido.
- Anterior/próximo (1005/1006) e falas internas do robô (3001–3004, 5001–5003): só constantes, sem método nem payload conhecido.
- Outros formatos (OGG, AAC…), cortar ou normalizar áudio.
- Coordenar com microfone de outros serviços (eco): fica com quem integra (decisão do humano, 2026-11-21).

## Segurança
- Nenhum movimento novo.
- **O envio ocupa o data channel do `move` e do `stop`** por minutos. Mitigação:
  - um envio por vez;
  - 0,1 s entre blocos (da lib) e timeout por bloco;
  - limite no WAV que vai ao robô;
  - conversão fora do loop;
  - medida em software (A7) e no robô (A11).
- Som alto perto de gente: o volume é o do robô (`/device/volume`, F-005, `inferido` que valha para o hub). Por padrão não há teto. `POST /audio/silence` é o jeito único de calar.
- A reprodução do hub é do robô: continua mesmo se a api cair (`inferido`).

## Impacto HRI

| Pergunta | Resposta |
|---|---|
| Que interação da pessoa com o robô isto muda? | O robô passa a tocar áudios quando um cliente da api pede. |
| O que a pessoa percebe em sucesso, rejeição, erro e espera? | Perto do robô: o som tocando, pausando, voltando, calando. Rejeição e erro não fazem som; o retorno é só para quem chamou (`4xx`/`5xx`). Durante o envio, provavelmente nada muda no robô (`inferido`); quem chamou acompanha pelo `GET /audio/uploads/{id}`. |
| Latência percebida | Do `play` ao som: `inferido`; `TODO(humano): medir` (A9). |
| O retorno promete algo que o sistema não fez? | `202` no `play` é aceite do robô, não fim nem garantia de que alguém ouviu. `done` no envio quer dizer que o robô aceitou os blocos; a confirmação é o `file_id` aparecer na lista. |
| Pode surpreender ou assustar quem está perto? | Som inesperado e alto assusta, sobretudo criança. `list_loop` pode tocar sem fim: `POST /audio/silence` cala. Eco num microfone de outro serviço fica com quem integra. |
| Quem usa? | Quem programa contra a api (uso livre). Quem está perto do robô só ouve. |
| Como validar com uma pessoa que não conhece o sistema? | Sem critério `usuario`: a api não define o que tocar nem quando. |

## Hipóteses não verificadas
- Formato da lista (`data.data` JSON com `audio_list`, itens com `UNIQUE_ID` e `CUSTOM_NAME`), do exemplo.
- Que o robô aceita WAV em qualquer taxa e só o MP3 precisa ser convertido (a lib só converte MP3).
- Que cada bloco recebe resposta com `status.code`; a lib só devolve a do último.
- Os modos `single_cycle`, `no_cycle` e `list_loop` e o formato da resposta de `GET_PLAY_MODE`.
- Conteúdo e taxa do tópico `AUDIO_HUB_PLAY_STATE` (A10).
- Tempo de envio e efeito no `stop` (A9, A11). Espaço disponível no robô para áudios.
- Se uma falha no meio deixa arquivo parcial (A12).
- Se o volume do VUI vale para o hub (F-005 A8).

## Decisões
Tomadas (2026-11-21, humano):
- áudio de uso livre; WAV e MP3;
- api independente do server e da TV Box; eco fora da api;
- escritas `202`; `/capabilities` não muda;
- `POST /audio/silence`;
- conversão como a lib, com o limite aplicado ao WAV enviado;
- nome repetido → `409`.

Tomadas pelo Claude (2026-11-22, a confirmar no relatório da rodada):
- envio assíncrono (`202` + `GET /audio/uploads/{id}`);
- megafone fora;
- `GO2_AUDIO_MAX_UPLOAD_MB` = `5`;
- PyAV em vez de pydub;
- sem consulta prévia do `id`;
- concorrência permitida (ver acima);
- validação do nome (1–64 caracteres);
- régua do `stop` do F-001 para o envio (A11).

## Roteiro hardware-only
No roteiro único da rodada: [`specs/checklists/api-completa.md`](../checklists/api-completa.md).

## Histórico
- 2026-11-21: criada (proposta).
- 2026-11-22: revisada pelo `spec-reviewer` e com as decisões do humano. Mudanças:
  - limite no WAV enviado;
  - payload exato da lib;
  - detecção de reconexão;
  - `POST /audio/silence`;
  - `409` para nome repetido;
  - conversão em thread;
  - `202`;
  - dependências explícitas.
- 2026-11-22: implementada em software (`29ad0cb`); A1–A8 `testado-software` com fake pub_sub (não prova o robô). Pendentes: A9–A12 (hardware-only) e a ligação do `audio_player` ao `/ws/state` (F-004) e do `silence` ao `/speaker/stop` (F-007), feitas por ganchos (`AudioHub.subscribe_player_state`, `AudioHub.set_speaker_stopper`). `specs/contracts/ws-state.md` não foi tocado nesta rodada. Decisões tomadas na implementação, a confirmar: 1 MB = 1 MiB; `name` vazio no formulário = ausente; corpo sem `file` ou que não é multipart → `422`; a vaga do envio é reservada antes de ler o corpo (o `409` de concorrência sai sem ler nada); `UNIQUE_ID` e `CUSTOM_NAME` só em texto (outro tipo → `502`); `GET_PLAY_MODE` lido de `json.loads(data.data)["play_mode"]` (`inferido`); `silence` para o alto-falante antes do `PAUSE` e tenta os dois mesmo se um falhar; pausa de 0,1 s só entre blocos (a lib também dorme depois do último); `disconnect()` da api encerra o envio como `failed: disconnected`; `file_id` com mais de um id novo fica o de mesmo nome.
