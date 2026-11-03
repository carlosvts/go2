---
id: E-002
titulo: Resposta falada curta (Llama, estilo caveman) para conversa e FAQ
tipo: experimento
status: proposta               # proposta | em-teste | adotada | rejeitada
servicos: [server, tvbox]
branch: exp/resposta-falada-llama   # parte da main; se a E-001 for adotada antes, rebase sobre ela
criterio-congelado-em: null    # AAAA-MM-DD @ commit, preenchido ANTES de começar a testar
verificacao: inferido          # inferido | testado-software | testado-hardware
verificado-em: null            # AAAA-MM-DD @ <commit>; só humano preenche testado-hardware
alternativa-a: null
---

# E-002 — Resposta falada curta (Llama, estilo caveman) para conversa e FAQ

## Problema

Quando a fala não vira comando, a TV Box só toca `rejected.wav`. O usuário não recebe resposta nenhuma. Decisão do humano (2026-11-03): numa fala que **não é tentativa de comando** (conversa curta, pergunta de FAQ), o robô deve **responder falando**, de forma curta. Enquanto a resposta não fica pronta, toca um áudio de espera ("Estou pensando...") para disfarçar a latência.

## Regra central de segurança

**O Llama não decide nenhuma frase nem nenhum comando, e não fala com a api.** Ele serve só para FAQ e interações curtas. A saída dele é só texto, que vira áudio (Piper) e toca na TV Box. Nenhum trecho da saída do Llama é interpretado, enfileirado ou despachado. O `stop` falado e o `python -m sense.stop` não mudam, e a parada falada **não pode ficar mais difícil** por causa deste fluxo (ver Fluxo, itens 2 e 6).

## Hipótese

Se a fala que não se parece com nenhum comando receber uma resposta falada curta em estilo caveman, gerada por um Llama local na GPU do server, com um áudio de espera tocado na hora, então o usuário ouve um retorno dentro dos limites de latência do critério. Isso deve acontecer sem nenhum comando vindo do Llama, nem direto nem por eco, e sem atrasar a parada falada.

Decisão do humano: como a implementação do Llama é nova, este experimento **mede só latência** (e as invariantes de segurança). Não há meta de qualidade da resposta.

## Abordagem

Branch `exp/resposta-falada-llama`.

### Quando roda

Só quando o interpretador rejeitou a frase por **`low_similarity`** e se cumprem as condições do caminho de gestos da E-001: o embedder está carregado, nem o top-1 nem o top-2 é `__stop__` ou `__movement__`, não há palavra de parada (sem exceção nenhuma) e nenhuma outra cláusula foi rejeitada por outro motivo. Se a E-001 estiver ativa, roda só depois que a regex também falhou.

Ficam com `rejected.wav`, como hoje (decisão do humano):

- `ambiguous`: costuma ser tentativa real de comando. O usuário repete.
- `negation`, `movement_*`, `command_disabled`, `lexical_only_command`, rejeição do Whisper e `stale`.

### Fluxo

1. O server decide que a fala vai para o Llama e **responde `/v1/utterance` na hora** com um status novo, `thinking`. O `utterance_id` serve de chave da resposta.
2. Ao receber `thinking`, a TV Box volta a `IDLE` como já faz em qualquer resposta. Depois toca um áudio de espera local e busca a resposta em `GET /v1/reply/{utterance_id}` (contrato novo) numa thread própria. **Invariante (teste automático):** a busca não usa `FallbackClient.submit`, não pega o `_in_flight` e não põe a máquina em `SENDING`. Então a wake word nova é aceita durante toda a espera e toda a reprodução (em `SENDING` ela é ignorada: `thin.py`, `wake_ignored_sending`).
3. No server: o Llama gera o texto, o filtro de eco confere (ver abaixo), o Piper gera o WAV, e o WAV fica guardado em memória por até 30 s (aceito pelo humano; **inferido**).
4. O `GET /v1/reply/{utterance_id}` devolve o WAV quando fica pronto. Se falhar ou passar do prazo, devolve "sem resposta" e a TV Box toca `rejected.wav`.
5. A TV Box grava o WAV num arquivo temporário (`TODO(implementação)`: caminho fora de `media/`, apagado depois de tocar) e recusa WAV maior que um teto de bytes (aceito pelo humano: 500 KB; **inferido**).
6. **Wake word nova** enquanto se espera ou se toca algo (decisão do humano): a resposta pendente é descartada e a TV Box **esvazia a fila de sons e interrompe o `aplay` em curso**, seja o `processing`, o áudio de espera ou a resposta. Depois toca o `beep` da wake word, como hoje. O comando novo sempre tem prioridade.

**Sons na TV Box.** O `processing` continua tocando no envio, como hoje. O áudio de espera entra depois dele, ao receber `thinking`. Para isso o `SoundPlayer` (`sense/audio.py`) precisa de três coisas que hoje não faz:
- tocar um WAV por caminho, porque hoje só toca `media/<nome>.wav` e a resposta fica fora de `media/`;
- esvaziar a fila (hoje `MAX_PENDING=2`);
- interromper o som em curso.

O formato exato (status HTTP da espera, long-poll ou consultas repetidas) vai no contrato `specs/contracts/server.openapi.json`. O **timeout e o intervalo da consulta** entram no commit de congelamento, porque afetam "resposta pronta ≤ 6 s" e "respostas perdidas".

Quem consome o status `thinking` e precisa mudar:

- `tvbox/sense/fallback_client.py`: hoje trataria `thinking` como `REJECTED` e tocaria `rejected.wav`;
- `tvbox/sense/thin.py`;
- `server/app/metrics.py` (`Stats`);
- `server/scripts/send_wav.py`.

`thinking` não entra em `FALLBACK_OK_STATUSES`: não é confirmação de comando.

### Filtro de eco

A resposta tocada pelo alto-falante pode ser captada pelo microfone na gravação seguinte. Decisão do humano: filtrar a resposta no server, com o microfone sempre ligado.

- O prompt proíbe anunciar ação ("Eu. Andar.", "Eu. Sentar.").
- Antes do TTS, o server confere o texto da resposta de duas formas. Se qualquer uma acusar, a resposta é **trocada** por uma frase fixa ("Eu. Não. Entender."):
  1. Passa pelo interpretador. Acusa se viraria comando ou parada (incluindo a regex da E-001, se estiver ativa).
  2. Acusa se contém palavra de uma **lista explícita de palavras proibidas**, versionada em `server/llm/`, comparada sem acento. A lista tem:
     - verbos e direções de `movement.verbs` e `movement.directions`;
     - `stop_words` e `negation`;
     - as palavras de `damp` ("desligar", "motores");
     - a palavra principal de cada comando do conjunto da E-001 (ex.: senta, sentar, levanta, deita, dança, rebola, alonga, coração, cumprimenta, acena, equilíbrio, recupera, arranha).
     Palavras funcionais ("a", "o", "um", "de", "para", "faz", "fica") **não** entram, para o filtro não trocar quase toda resposta. "para" já é coberto pelo item 1 e por `stop_words`.
- A frase fixa também passa pelo filtro, num teste automático.
- O log registra quando o filtro trocou a resposta e por quê.

### Llama

- Llama 3.1 8B Instruct, quantização Q4_K_M (decisão do humano), via llama.cpp, **na GPU do server**, com todas as camadas na GPU (`n_gpu_layers` anotado no log de partida).
- Server de destino: 8 GB de VRAM e 16 GB de RAM (informado pelo humano). Que o Whisper medium e o Llama caibam juntos é **inferido**; ninguém mediu. A GPU de desenvolvimento (RTX 3050 Ti, 4 GiB) provavelmente não comporta os dois (inferido). Nesse caso o teste roda no server.
- Saída: texto livre, **curto, em estilo caveman**, definido no prompt com exemplos do humano:
  - "eu amo você" → "Eu. Amar. Você."
  - "Eu sou o go2, um robô quadrúpede" → "Eu. Go2. Robô quadrúpede."
- Limite de tokens na geração: 24 (aceito pelo humano; **inferido**); o texto é cortado no limite. Aumentar o limite fica para um experimento posterior, com spec própria. Mudar aqui depois de congelar invalida a medida de latência.
- Conversa livre e FAQ (decisão do humano). **Risco aceito:** sem ferramentas, o Llama pode inventar fatos (hora, clima, nomes).
- O prompt, o arquivo do modelo (nome e SHA-256), os parâmetros de geração e o limite de tokens ficam versionados em `server/llm/` e entram no commit de congelamento.
- Concorrência: o Llama **não pode** atrasar a transcrição da fala seguinte, principalmente a parada. Como isolar (fila própria, processo separado) é decisão da implementação; o critério mede o efeito.

### TTS

Piper no server, **na CPU** (aceito pelo humano; motivo **inferido**: não disputa VRAM com Whisper e Llama), com as vozes em `server/models/piper/` (as mesmas de `scripts/tts.py`). Voz: `pt_BR-faber-medium` (decisão do humano). A mesma voz gera os WAVs de espera.

### Áudio de espera (TV Box)

- Duas a quatro frases ("Estou pensando...", "Calma aí, deixa eu pensar...") geradas **uma vez** com Piper e versionadas em `tvbox/media/`. A TV Box sorteia uma.
- Sem Piper e sem dependência nova na TV Box: ela já toca WAV com `aplay` (`sense/audio.py`, `SoundPlayer`).
- Recursos: os WAVs atuais têm 10–35 KB. Quatro frases curtas devem ocupar menos de 200 KB (inferido). A TV Box está com o disco em ~90%: conferir `df -h` antes de instalar.

### Limites que não mudam

- O Llama não gera comando; o dispatcher não é chamado no caminho do Llama. Teste automático, e um evento de log `llm_reply` com o `utterance_id`, conferido contra os `submit` do dispatcher.
- `damp` só por frase exata. Parada falada: mesmo caminho e mesma prioridade de hoje.
- `GO2S_MAX_UTTERANCE_AGE_S` não muda.
- A TV Box continua sem executar nada e sem expor HTTP.

## Dados de teste

Sessão ao vivo, como na E-001: frases ditas na hora (pelo menos 30), com `GO2S_SAVE_UTTERANCES=1`. Pelo menos 10 delas devem cair no Llama (conversa, perguntas de FAQ). Algumas devem tentar provocar eco: perguntas cuja resposta natural citaria um comando ("o que você sabe fazer?").

Mais uma rodada de **parada durante a geração**: wake word + "para" logo depois de uma frase que cai no Llama, com o robô em pé ou fazendo um gesto. Com o robô andando seria difícil: o `move` dura 1–3 s (catálogo, inferido) e provavelmente acaba antes. Não afeta a métrica, porque o server devolve `stopped` sempre que o stop é entregue. Pelo menos 5 vezes, e as mesmas 5 sem o Llama gerando, como comparação.

Com 10 a 30 amostras, o p95 é praticamente o máximo. Por isso o critério usa o **máximo** (decisão do humano).

## Métricas

Todas no log do server e da TV Box, por frase:

| Métrica | Como medir | Linha de base |
|---|---|---|
| Fim da fala → início real do `aplay` do áudio de espera | log da TV Box (horário em que o `aplay` começa, não o do pedido de `play`) | `TODO(humano): medir` (equivalente hoje: fim da fala → `rejected.wav`) |
| Fim da fala → resposta pronta na TV Box (WAV baixado) | log da TV Box | — |
| Fim da fala → início do áudio de resposta | log da TV Box (inclui a duração do WAV de espera; só informativo) | — |
| Geração do Llama (ms) e número de tokens | log do server | — |
| Piper (ms) | log do server | — |
| Respostas que não chegaram (falha ou prazo) | log da TV Box | — |
| Respostas trocadas pelo filtro de eco (e motivo) | log do server; informativo, fora do critério | — |
| Comandos gerados pelo caminho do Llama | `llm_reply` × `submit` + teste automático | 0 |
| Comando cuja transcrição contém trecho da resposta anterior (eco) | log do server: transcrição × texto da última resposta | 0 |
| Parada durante a geração: fim da fala → `stopped` | `reply_latency_s` da TV Box, rodada de parada × a mesma parada sem Llama | `TODO(humano): medir` |
| VRAM ocupada (Whisper + Llama) e `n_gpu_layers` | `nvidia-smi` e log de partida no server | `TODO(humano): medir` |

## Critério de decisão (congelar antes de testar)

Números aceitos pelo humano em 2026-11-03 como proposta para congelar (**inferidos**: ninguém mediu ainda).

**Rejeita se** acontecer qualquer um destes:

- qualquer comando saiu do caminho do Llama, direto ou por eco;
- o teste automático da invariante do Fluxo, item 2, falha: a busca da resposta usa `submit`, pega o `_in_flight` ou põe a máquina em `SENDING`;
- a parada durante a geração ficou mais lenta: o máximo de "fim da fala → `stopped`" subiu mais de 0,5 s em relação à mesma parada sem Llama gerando;
- o modelo não cabe: OOM ao carregar, ou alguma camada fora da GPU, com Whisper e Llama carregados juntos.

**Adota se** nenhuma condição de rejeição ocorreu e:

- máximo de "fim da fala → resposta pronta na TV Box" ≤ 6 s;
- máximo de "fim da fala → início real do áudio de espera" ≤ 1,5 s;
- respostas perdidas (falha ou prazo) ≤ 10% das frases que caíram no Llama.

**Inconclusivo se** só os limites de latência ou de respostas perdidas falharam. A equipe decide entre rejeitar e tentar otimizar (modelo menor, menos tokens); otimizar exige nova spec.

Um FP do interpretador (comando errado que não veio do Llama nem de eco) não conta contra a E-002. Ele para o teste por segurança e é registrado à parte.

## Procedimento de hardware

1. No server: subir a api (com o robô), o server da branch com `GO2S_SAVE_UTTERANCES=1` e o Llama na GPU. Anotar a VRAM (`nvidia-smi`) e o `n_gpu_layers` com tudo carregado.
2. Na TV Box: atualizar com os WAVs de espera; `df -h` e `free -h` antes e depois.
3. Falar as frases (≥ 30, pelo menos 10 caindo no Llama). Para cada uma, anotar: se tocou o áudio de espera, se a resposta chegou e se foi inteligível (anotação livre, fora do critério).
4. Rodada de parada: falar "para" durante a geração (≥ 5 vezes) e o mesmo sem Llama gerando. Anotar se o robô parou.
5. Quando acontecer de falar a wake word com o áudio de espera ou a resposta tocando, anotar se o som parou e se o comando saiu (anotação livre, fora do critério).
6. Movimento do robô que não veio de comando pretendido: parar o teste e anotar. O log diz a origem: do Llama ou eco rejeita; do interpretador fica registrado à parte.

Segurança: deixar `python -m sense.stop` à mão. A parada falada não é garantida.

## Hipóteses não verificadas

- Que Whisper medium e Llama 8B Q4 cabem juntos em 8 GB de VRAM: inferido.
- Que a wake word é detectada com o alto-falante da TV Box tocando a resposta ou o áudio de espera. A métrica foi removida por decisão do humano (2026-11-03); fica sem medida.
- Que o filtro de eco basta. O alto-falante pode tocar algo que o Whisper transcreve diferente do texto original. Além disso, o eco também entra pelo **pré-roll**: o áudio enviado começa `PRE_ROLL_S` antes da wake word, tirado do buffer circular, e esse trecho pode conter o fim da resposta que estava tocando. Interromper o `aplay` não evita isso. A métrica de eco cobre os dois casos; sem medida ainda.
- O prazo de 30 s, o teto de 500 KB, o limite de 24 tokens e o Piper na CPU foram aceitos pelo humano em 2026-11-03 sem medida (é difícil checar sem testar no robô). Continuam **inferidos** até a sessão de hardware.
- Respostas com fatos inventados: risco aceito pelo humano; não é medido.

## Resultado

<Preencher depois.>

## Decisão

<Preencher depois.>

## Histórico

- 2026-11-03: criada (proposta), separada da E-001 por decisão do humano; revisada pelo `spec-reviewer`.
