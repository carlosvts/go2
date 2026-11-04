---
id: E-002
titulo: Resposta falada curta (Llama, estilo caveman) para conversa e FAQ
tipo: experimento
status: proposta               # proposta | em-teste | adotada | rejeitada (aprovada pelo humano em 2026-11-04; aguarda congelamento da etapa 1)
servicos: [server, tvbox]
branch: exp/resposta-falada-llama   # parte da main; se a E-001 for adotada antes, rebase sobre ela
criterio-congelado-em: null    # etapa 1 (antes de implementar): AAAA-MM-DD @ commit; só humano preenche
parametros-congelados-em: null # etapa 2 (antes do hardware): AAAA-MM-DD @ commit; só humano preenche
verificacao: inferido          # inferido | testado-software | testado-hardware
verificado-em: null            # AAAA-MM-DD @ <commit>; só humano preenche testado-hardware
alternativa-a: null
---

# E-002 — Resposta falada curta (Llama, estilo caveman) para conversa e FAQ

## Problema

Quando a fala não vira comando, a TV Box só toca `rejected.wav`. O usuário não recebe resposta nenhuma. Decisão do humano (2026-11-03): numa fala que **não é tentativa de comando** (conversa curta, pergunta de FAQ), o robô deve **responder falando**, de forma curta. Enquanto a resposta não fica pronta, toca um áudio de espera ("Estou pensando...") para disfarçar a latência.

Decisão do humano (2026-11-04): numa frase **mista**, com uma cláusula que vira comando e outra de conversa ("senta e fala seu nome"), o comando é despachado e a cláusula de conversa vai para o Llama. Hoje essa frase é rejeitada inteira. O **despacho parcial** é caminho novo desta spec, e um comando indevido saído dele rejeita o experimento (ver Critério).

## Regra central de segurança

**O Llama não decide nenhuma frase nem nenhum comando, e não fala com a api.** Ele serve só para FAQ e interações curtas. A saída dele é só texto, que vira áudio (Piper) e toca na TV Box. Nenhum trecho da saída do Llama é interpretado, enfileirado ou despachado. O `stop` falado e o `python -m sense.stop` não mudam, e a parada falada **não pode ficar mais difícil** por causa deste fluxo (ver Fluxo, itens 2 e 6; medido no Critério: parada perdida ou mais lenta rejeita).

## Hipótese

Se a fala (ou a cláusula) que não se parece com nenhum comando, mas passa no filtro de ruído, receber uma resposta falada curta em estilo caveman, gerada por um Llama local na GPU do server, com um áudio de espera tocado na hora, então o usuário ouve um retorno dentro dos limites de latência do critério. Isso deve acontecer sem nenhum comando vindo do Llama, nem direto nem por eco, sem comando indevido vindo do despacho parcial e sem atrasar a parada falada.

Decisão do humano: como a implementação do Llama é nova, este experimento **mede só latência** (e as invariantes de segurança). Não há meta de qualidade da resposta.

## Abordagem

Branch `exp/resposta-falada-llama`.

### Quando roda

A decisão é por cláusula. Uma cláusula é **de conversa** (vai para o Llama) só se cumprir todas estas condições:

- C1. Foi rejeitada por **`low_similarity`**.
- C2. O embedder está carregado.
- C3. Nem o rótulo top-1 nem o top-2 é `__stop__` ou `__movement__`. O top-2 é o **segundo rótulo distinto** no ranking por rótulo de `_nearest` (o mesmo que define a margem), não o segundo exemplo mais próximo. Para isso, `Clause` passa a registrar o top-1 e o top-2 mesmo quando rejeita; os dois vão para o log em `clauses[]`. A E-001 faz a mesma mudança; quem for para a main depois resolve o conflito e confere que as duas usam esta definição.
- C4. Passa no **filtro de ruído** (decisão do humano, 2026-11-04; números **inferidos**):
  - pelo menos 3 palavras depois de tirar o enchimento (`fillers` do catálogo);
  - pelo menos uma palavra de uma **lista de marcadores de conversa** versionada em `server/llm/`, comparada sem acento. Proposta inicial, congelada na etapa 1: qual, quem, como, onde, quando, porque, que, você, seu, sua, teu, tua, fala, conta, diz, me.
  - "banana" e "banana azul grande" são ruído; "fala seu nome" e "qual é o seu nome" passam.
  - **Efeito aceito:** conversa muito curta ("oi", "bom dia", "tudo bem?") não passa e fica com `rejected.wav`.
  - Se a E-001 estiver ativa, só conta depois que a regex também falhou.

**Só há caminho novo se existir candidata**: pelo menos uma cláusula `low_similarity` que cumpre C1–C4. Sem candidata, a frase segue o fluxo atual, sem mudança nenhuma ("senta" e "anda para frente" saem como hoje).

Com candidata, valem as condições sobre a **frase inteira**. Se alguma falhar, nada vai para o Llama e a frase segue exatamente como hoje, ou seja, rejeitada inteira (`low_similarity` ou o motivo de sempre):

- F1. Palavra de parada, conferida **depois** de `tokenize`, como no interpretador (então "pra" já virou "para"). Refinada por decisão do humano em 2026-11-04:
  - "pare", "parar", "stop" e qualquer outra palavra de `stop.words` que não seja "para", em qualquer lugar da frase: barram sempre.
  - **Posição**: conta nos tokens de cada cláusula como `_segment` devolve, ou seja, depois de tirar a wake word (`strip_wake_word`), de `tokenize`, de cortar nos separadores e de tirar os fillers. Exemplo: em "robô para de me seguir", "para" é a primeira palavra.
  - "para" barra, **exceto** quando é preposição nestes dois casos:
    - dentro de uma cláusula aceita como movimento (`slots`), onde o interpretador já a tratou como preposição (`movement.ignore`). Exemplo: "andar para frente e qual é o seu nome" passa;
    - no **meio** da cláusula de conversa, ou seja, nem a primeira nem a última palavra dela, e sem "de" ou "com" logo depois. Exemplo: "fala pra mim quem é você" passa.
  - Barram sempre (decisões do humano, 2026-11-04):
    - "para" como **primeira** palavra da cláusula de conversa ("para com isso", "pra que você serve");
    - "para" como **última** palavra de **qualquer** cláusula. Exemplo: em "você vai bater para e anda para trás", sem esta regra sairia `move_backward` mais o Llama;
    - "para de" e "para com", em **qualquer** posição de qualquer cláusula de conversa ou não aceita ("ei para de me seguir", "olha para com isso"), porque são a forma típica da tentativa de parada;
    - "para" em cláusula aceita que não é de movimento, como [para senta] aceita por embedding. Nesse caso barra por exclusão.
  - O que o interpretador já trata como parada não muda: cláusula só de palavras de parada, ou frase terminada em "para", continuam `stop` antes de qualquer regra da E-002.
  - Risco aceito pelo humano: uma tentativa de parada com "para" no meio, fora das formas acima ("você para já que eu mandei"), fica protegida só pelo C3 (top-1/top-2 não pode ser `__stop__`) e pelo limiar do embedding. O eval da etapa 1 e a rodada de parada no hardware têm casos para isso.
- F2. Nenhuma cláusula foi rejeitada por motivo diferente de `low_similarity`.
- F3. **Exatamente uma** cláusula é de conversa (decisão do humano, 2026-11-04). Cláusula `low_similarity` que não cumpre C2–C4 rejeita a frase inteira (`low_similarity`, como hoje), e duas ou mais cláusulas de conversa também.
- F4. As demais cláusulas foram aceitas, nenhuma é `damp` e **todas casaram sem embedding** (decisão do humano, 2026-11-04). Vale `method: lexical` (frase exata do catálogo) ou `method: slots` com todos os slots resolvidos pelo léxico (`_slot_lexical`, incluindo a distância de edição 1 que já existe). Ficam de fora:
  - cláusula aceita por embedding ("a gente senta"), slot resolvido por embedding e cláusula recuperada pela regex da E-001. Qualquer uma dessas faz a frase inteira ser rejeitada, como hoje;
  - `damp`, que só sai por frase exata e nunca acompanha uma resposta.

  Os outros comandos do catálogo podem ser despachados junto, com as regras de sempre (`move` exige `balance_stand`, garantido pelo dispatch).
- F5. A fala não está velha: `time.monotonic() - received ≤ max_utterance_age_s`, checado antes de chamar o Llama, **também na conversa pura**. Passou do limite: `rejected`, `stale`, como hoje.
- F6. O `llama-server` está saudável segundo o estado mantido em segundo plano (ver Llama). Fora do ar: a frase segue como hoje.

Os dois casos que vão para o Llama:

- **Só conversa**: a frase tem uma cláusula só, e ela é de conversa. Nada é despachado.
- **Mista**: uma cláusula de conversa e uma ou mais cláusulas aceitas que cumprem F4. Os comandos aceitos vão para a fila (`_enqueue`, com `stale`, fila cheia etc. como hoje). **Se a fila recusar, o Llama não roda**: a frase é rejeitada com o motivo da fila, como hoje. O texto mandado ao Llama é só o da cláusula de conversa.

**Todo o resto** fica como hoje (`rejected.wav` ou o som de sempre). Por decisão do humano, entram aqui `ambiguous`, que costuma ser tentativa real de comando (o usuário repete), e todos os motivos de rejeição que não são `low_similarity`.

### Fluxo

1. O server decide que a fala vai para o Llama e **responde `/v1/utterance` na hora**. O `utterance_id` serve de chave da resposta. Contrato (decisão do humano, 2026-11-04):
   - só conversa: status novo `thinking`, `reply_pending: true`, `commands: []`, `reject_reason: null`, e `confidence` com o score da cláusula de conversa (informativo);
   - mista: status `enqueued` com os `commands` de sempre e um campo novo, `reply_pending: true`;
   - em **qualquer outra** resposta, `reply_pending: false`. Cliente que não conhece o campo continua funcionando.
2. Ao receber `thinking`, ou `enqueued` com `reply_pending`, a TV Box volta a `IDLE` como já faz em qualquer resposta. No caso misto toca `confirmed` antes, como hoje. Depois toca um áudio de espera local e busca a resposta em `GET /v1/reply/{utterance_id}` (contrato novo) numa thread própria. **Invariante (teste automático):** a busca não usa `FallbackClient.submit`, não pega o `_in_flight` e não põe a máquina em `SENDING`. Então a wake word nova é aceita durante toda a espera e toda a reprodução (em `SENDING` ela é ignorada: `thin.py`, `wake_ignored_sending`).
3. No server: o Llama gera o texto, o filtro de eco confere (ver abaixo), o Piper gera o WAV, e o WAV fica guardado em memória. O registro da resposta (WAV ou "sem resposta") vive até 30 s depois da resposta ao `/v1/utterance` (aceito pelo humano; **inferido**). Os 30 s servem só para o GET que chega atrasado: depois disso o registro some e o GET dá `404`.
4. O `GET /v1/reply/{utterance_id}` é **long-poll** (decisão do humano, 2026-11-04): o server segura a requisição até o WAV ficar pronto ou até **10 s** depois da resposta ao `/v1/utterance` (prazo **inferido**). Respostas:
   - `200` com o WAV;
   - `204` para "sem resposta": falhou, passou do prazo ou o Llama estava ocupado. WAV que fica pronto depois dos 10 s é descartado, e o registro fica "sem resposta" (`204`) até expirar;
   - `404` para `utterance_id` desconhecido ou expirado.

   O timeout do cliente é 12 s (**inferido**). Em `204`, `404`, erro ou timeout:
   - só conversa: a TV Box toca `rejected.wav`;
   - mista: o comando já foi aceito e o `confirmed` já tocou. Por decisão do humano (2026-11-04), a TV Box toca um som próprio, `reply_failed`, que diz que **a resposta** não veio, sem sugerir que o comando foi recusado. As frases estão em "Áudio de espera".
5. A TV Box grava o WAV num arquivo temporário (`TODO(implementação)`: caminho fora de `media/`, apagado depois de tocar) e recusa WAV maior que um teto de bytes (aceito pelo humano: 500 KB; **inferido**).
6. **Wake word nova** enquanto se espera ou se toca algo (decisão do humano): a resposta pendente é descartada e a TV Box **esvazia a fila de sons e interrompe o `aplay` em curso**, qualquer que seja o som: `processing`, `confirmed`, `rejected`, o áudio de espera ou a resposta. Depois toca o `beep` da wake word, como hoje. O comando novo sempre tem prioridade.

**Sons na TV Box.** O `processing` continua tocando no envio, como hoje. O áudio de espera entra depois dele, ao receber `thinking` ou `enqueued` com `reply_pending`; na mista, entra depois do `confirmed`. Para isso o `SoundPlayer` (`sense/audio.py`) precisa de quatro coisas que hoje não faz:
- tocar um WAV por caminho, porque hoje só toca `media/<nome>.wav` e a resposta fica fora de `media/`;
- esvaziar a fila;
- interromper o som em curso;
- não descartar o áudio de espera na mista. Hoje `MAX_PENDING=2` descarta o mais antigo: `processing` em curso + `confirmed` + espera passa do limite. Teste automático: na sequência da mista, todos os sons pedidos tocam, em ordem.

O formato vai no contrato `specs/contracts/server.openapi.json`. O **prazo do long-poll (10 s) e o timeout do cliente (12 s)** entram no congelamento da etapa 1, porque afetam "resposta pronta ≤ 6 s" e "respostas perdidas".

O que precisa mudar:

- **tvbox**:
  - `sense/fallback_client.py`: hoje trataria `thinking` como `REJECTED` e tocaria `rejected.wav`. `send()` passa a ler `reply_pending`, e `Reply` ganha o campo;
  - `sense/thin.py`;
  - `sense/audio.py` (`SoundPlayer`).
- **server**:
  - `app/service.py`: `UtteranceResponse.reply_pending`, F1–F6 e o disparo da resposta;
  - `app/interpret/interpreter.py`: a classificação de cada cláusula como "de conversa" e o registro do top-1/top-2 e da origem dos slots;
  - `app/main.py`: rota `GET /v1/reply/{utterance_id}`;
  - `app/metrics.py` (`Stats`): conta `thinking` e a mista separada de `enqueued`;
  - `scripts/send_wav.py`: mostra `reply_pending` e baixa a resposta;
  - `docker-compose.yml`: serviço `llama-server`;
  - `app/interpret/evaluate.py`: ganha o desfecho da camada da E-002 (`llm`, mista), usado por um teste novo (`-m model`) sobre `eval/conversation_e002.yaml`. O `scripts/calibrate.py` e o `eval/phrases.yaml` não mudam.

`thinking` não entra em `FALLBACK_OK_STATUSES`: não é confirmação de comando.

### Filtro de eco

A resposta tocada pelo alto-falante pode ser captada pelo microfone na gravação seguinte. Decisão do humano: filtrar a resposta no server, com o microfone sempre ligado.

- O prompt proíbe anunciar ação ("Eu. Andar.", "Eu. Sentar.").
- Antes do TTS, o server confere o texto da resposta de duas formas. Se qualquer uma acusar, a resposta é **trocada** por uma **frase fixa**, sorteada entre as variantes aprovadas pelo humano (2026-11-04) e versionadas em `server/llm/`: "Eu. Não. Entender.", "Eu. Confuso.", "Eu. Não. Saber.". As duas verificações:
  1. Passa pelo interpretador. Acusa se `is_stop_only` der verdadeiro, se o `Kind` for `STOP` ou `COMMANDS`, ou se **qualquer** cláusula tiver `command_id` aceito, mesmo que a frase seja rejeitada ou fosse mista. Inclui a regex da E-001, se estiver ativa.
  2. Acusa se contém palavra de uma **lista explícita de palavras proibidas**, versionada em `server/llm/`, comparada sem acento. A lista tem:
     - verbos e direções de `movement.verbs` e `movement.directions`;
     - `stop_words` e `negation`;
     - as palavras de `damp` ("desligar", "motores");
     - a palavra principal de cada comando habilitado no catálogo (ex.: senta, sentar, levanta, deita, dança, rebola, alonga, coração, cumprimenta, acena, equilíbrio, recupera, arranha).
     Palavras funcionais ("a", "o", "um", "de", "faz", "fica") e saudações ("oi", "tchau") **não** entram, para o filtro não trocar quase toda resposta. "para" está em `stop_words`.
- As frases fixas passam por um teste automático:
  - item 1 (interpretador): nenhuma pode virar comando nem parada;
  - item 2 (lista proibida): nenhuma pode conter palavra da lista, **exceto "não"**. Essa exceção foi aceita pelo humano em 2026-11-04, como na frase "Não sei te responder isso." do `reply_failed`. Se "não" vazar no pré-roll, a próxima frase pode ser rejeitada por `negation`, o que é seguro.
  - A exceção vale só para as frases fixas. Uma resposta do Llama com "não" continua sendo trocada.
- O log registra quando o filtro trocou a resposta e por quê.

### Llama

- Llama 3.1 8B Instruct, quantização Q4_K_M (decisão do humano), via llama.cpp, **na GPU do server**, com todas as camadas na GPU (`n_gpu_layers` anotado no log de partida).
- Server de destino: 8 GB de VRAM e 16 GB de RAM (informado pelo humano). Que o Whisper medium e o Llama caibam juntos é **inferido**; ninguém mediu. A GPU de desenvolvimento (RTX 3050 Ti, 4 GiB) provavelmente não comporta os dois (inferido). Nesse caso o teste roda no server.
- Saída: texto livre, **curto, em estilo caveman**, definido no prompt com exemplos do humano:
  - "eu amo você" → "Eu. Amar. Você."
  - "Eu sou o go2, um robô quadrúpede" → "Eu. Go2. Robô quadrúpede."
- Limite de tokens na geração: 24 (aceito pelo humano; **inferido**); o texto é cortado no limite. Aumentar o limite fica para um experimento posterior, com spec própria. Mudar aqui depois de congelar invalida a medida de latência.
- Conversa livre e FAQ (decisão do humano). **Risco aceito:** sem ferramentas, o Llama pode inventar fatos (hora, clima, nomes).
- O prompt, o arquivo do modelo (nome e SHA-256), os parâmetros de geração e o limite de tokens ficam versionados em `server/llm/` e entram no congelamento da etapa 2.
- Concorrência: o Llama **não pode** atrasar a transcrição da fala seguinte, principalmente a parada. Isolamento (decisão do humano, 2026-11-04): o `llama-server` oficial do llama.cpp roda em **processo separado** (serviço próprio no `docker-compose.yml` do server, imagem CUDA), e o go2-server fala com ele por HTTP em localhost.
  - Roda **uma geração por vez**; se chegar outra com uma em curso, a nova fica "sem resposta" (`204`).
  - O processo separado isola CPU, GIL e falhas, mas **não** a disputa de GPU com o Whisper. O efeito sobre o STT da parada continua sem medida. Só o critério de parada o cobre, com 5 amostras e um limiar de 0,5 s, ambos **inferidos**.
- Saúde do `llama-server` (F6): uma tarefa em segundo plano consulta o `/health` dele periodicamente, e o caminho de `/v1/utterance` só lê o último estado, **sem chamada síncrona**. Assim um llama-server travado não segura a resposta nem deixa a TV Box em `SENDING`, onde a wake word da parada seria ignorada. A consulta roda a cada 2 s, com timeout de 0,5 s (aprovado pelo humano em 2026-11-04; **inferido**). A chamada de geração tem timeout igual ao prazo do long-poll.
- Sem o `llama-server` saudável, a frase de conversa segue como hoje (`rejected`, `low_similarity`) e a mista é rejeitada inteira, também como hoje.

### TTS

Piper no server, **na CPU** (aceito pelo humano; motivo **inferido**: não disputa VRAM com Whisper e Llama), com as vozes em `server/models/piper/` (as mesmas de `scripts/tts.py`). Voz: `pt_BR-faber-medium` (decisão do humano). A mesma voz gera os WAVs de espera.

### Áudio de espera (TV Box)

- Dois sons novos, gerados **uma vez** com Piper e versionados em `tvbox/media/`, com pelo menos 4 variantes cada, para redundância. A TV Box sorteia uma sem repetir a anterior, como nos outros sons. Frases aprovadas pelo humano em 2026-11-04:
  - `thinking` (espera, teto de 1,5 s por frase):
    - "Hum, deixa eu pensar."
    - "Boa pergunta, peraí."
    - "Pensando aqui..."
    - "Calma, já te respondo."
    - "Opa, deixa eu ver isso."
    - "Hum... pensando."
  - `reply_failed` (resposta não veio, só na mista; teto de 2,8 s, igual ao `rejected`):
    - "Essa pergunta eu fiquei devendo."
    - "Hum, a resposta me escapou."
    - "Dessa vez fiquei sem resposta."
    - "Deu branco na resposta, desculpa."
    - "Essa eu vou ficar devendo."
    - "Não sei te responder isso."
- As frases evitam "para" (parada), "não" (negação) e nomes de comando, porque o fim do som pode entrar no pré-roll da frase seguinte. A exceção é "Não sei te responder isso.", aceita pelo humano. Se vazar no pré-roll, a próxima frase pode ser rejeitada por `negation`, o que é seguro.
- São gerados por `tvbox/scripts/generate_voice.py`, como os outros, e recebem o silêncio inicial de `scripts/add_lead_silence.py` (250 ms), para o Anker não cortar o começo.
- O WAV da resposta do Llama, gerado no server, recebe o mesmo silêncio inicial de 250 ms, pelo mesmo motivo.
- Sem Piper e sem dependência nova na TV Box: ela já toca WAV com `aplay` (`sense/audio.py`, `SoundPlayer`).
- Recursos: os WAVs atuais têm 10–35 KB. As 12 frases novas devem ocupar menos de 500 KB (inferido). A TV Box está com o disco em ~90%: conferir `df -h` antes de instalar.

### Limites que não mudam

- O Llama não gera comando; o dispatcher não é chamado no caminho do Llama. Na frase mista, o `submit` recebe só os comandos das cláusulas aceitas pelo interpretador. Ele é chamado **antes** de o Llama rodar, e nada da saída do Llama entra nele.
- **Invariante de auditoria:** para cada `utterance_id` com evento `llm_reply`, há no máximo um `submit` com esse `utterance_id`. Esse `submit` é registrado **antes** do `llm_reply` e tem exatamente os `command_id` das cláusulas aceitas em `clauses[]`. Nenhum `submit` com esse `utterance_id` depois do `llm_reply`. Teste automático nos dois casos: só conversa (0 `submit`) e mista (1 `submit`, igual às cláusulas aceitas). A mesma conferência roda sobre o log da sessão de hardware.
- `damp` só por frase exata. Parada falada: mesmo caminho e mesma prioridade de hoje.
- `GO2S_MAX_UTTERANCE_AGE_S` não muda.
- A TV Box continua sem executar nada e sem expor HTTP.

## Dados de teste

**Antes do hardware (software):** um conjunto próprio, `server/eval/conversation_e002.yaml`, com o resultado esperado de cada frase. Ele é separado do `eval/phrases.yaml` (decisão do humano, 2026-11-04) porque o `phrases.yaml` mede só o interpretador: lá a frase de conversa continua `reject`, e está certo, porque nada é executado. Este conjunto mede a camada da E-002 por cima do interpretador, com os rótulos `llm` e `{commands: [...], llm: true}`. O `phrases.yaml` continua passando sem mudança, e a meta de 0 FP vale para os dois. Categorias do conjunto novo:
- mistas com pedido ("senta e fala seu nome"): despacha o comando e vai para o Llama;
- mistas com ruído ("senta e banana"): rejeita tudo;
- conversa no meio de fala que não é comando ("a gente senta e depois você me conta como foi"): rejeita tudo. Quem segura esse caso é o F4 ("a gente senta" só casa por embedding), não o filtro de ruído: a cláusula de conversa tem marcadores e passaria;
- conversa pura que deve ir ao Llama, e ruído puro que não deve;
- regressão: comandos simples ("senta", "anda para frente") e paradas continuam com o desfecho de hoje.

Meta: **0 falsos positivos**, como no resto do eval. As frases novas, a lista de marcadores e a lista de palavras proibidas são congeladas na etapa 1, **antes** de implementar, para não serem afinadas até o eval passar. `TODO(humano)`: revisar e aprovar as frases antes do congelamento.

**Hardware:** sessão ao vivo, como na E-001: frases ditas na hora (pelo menos 30), com `GO2S_SAVE_UTTERANCES=1`. Antes de falar cada frase, o humano anota o **desfecho pretendido** (comando(s), Llama sim/não ou rejeição) e não muda depois, como na E-001.
- Pelo menos 10 frases devem cair no Llama (conversa, perguntas de FAQ), e pelo menos 5 delas devem ser mistas.
- Outras 5 devem ser mistas com ruído ou conversa que não é comando, para tentar provocar despacho parcial indevido.
- Algumas devem tentar provocar eco: perguntas cuja resposta natural citaria um comando ("o que você sabe fazer?").

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
| Despachos parciais (frase mista) e quantos foram indevidos | log do server (`partial_dispatch`) × desfecho pretendido anotado **antes** de falar | indevidos: 0 |
| Cláusulas barradas pelo filtro de ruído | log do server; informativo | — |
| Comando por eco | log do server: comando aceito cuja transcrição tem **≥ 2 palavras consecutivas** da última resposta tocada, comparadas com `fold`, numa fala até 10 s depois do fim real do som da resposta, tocado inteiro ou interrompido pela wake word (regra e números **inferidos**, congelados na etapa 1) | 0 |
| Parada durante a geração: fim da fala → `stopped` | `reply_latency_s` da TV Box, rodada de parada × a mesma parada sem Llama | `TODO(humano): medir` |
| Tentativas de parada em frase que foram ao Llama ou despacharam comando | anotação humana (procedimento item 4) + log do server (`llm_reply`, `partial_dispatch`) | 0 |
| Paradas perdidas (o robô não parou) | **anotação humana** do procedimento, item 4 (uma wake word não detectada não deixa log); log da TV Box e do server como apoio. Contagem por rodada: com Llama × sem Llama | 0 |
| VRAM ocupada (Whisper + Llama) e `n_gpu_layers` | `nvidia-smi` e log de partida no server | `TODO(humano): medir` |

## Critério de decisão (congelar em duas etapas)

Decisão do humano (2026-11-04), exceção registrada ao fluxo de `specs/README.md`, que congela tudo de uma vez antes de implementar:
- **Etapa 1, antes de implementar** (`criterio-congelado-em`): esta seção, as regras de "Quando roda" (C1–C4, com o mínimo de 3 palavras, e F1–F6), `eval/conversation_e002.yaml`, a lista de marcadores de conversa, a lista de palavras proibidas, as frases fixas do filtro de eco, a regra de eco, o prazo do long-poll e o timeout do cliente.
- **Etapa 2, antes do hardware** (`parametros-congelados-em`): prompt, modelo (nome e SHA-256), parâmetros de geração e limite de tokens, porque só existem depois da implementação.

Mudar algo da etapa 1 depois de congelado invalida o experimento. Os dois campos, só humano preenche.

Números do critério aceitos pelo humano em 2026-11-03; os de 2026-11-04 (10 s, 12 s, 3 palavras, uma cláusula de conversa por frase) vêm do Histórico. Todos **inferidos**: ninguém mediu ainda.

**Rejeita se** acontecer qualquer um destes:

- qualquer comando saiu do caminho do Llama, direto ou por eco;
- algum comando não pretendido saiu do **despacho parcial**: uma frase mista que hoje seria rejeitada inteira executou um comando que ninguém pediu. Exemplo: "a gente senta e depois você me conta como foi" e o robô senta;
- `eval/conversation_e002.yaml` ou `eval/phrases.yaml` tem algum falso positivo, ou seja, algum comando despachado fora do `expect`;
- o teste automático da invariante do Fluxo, item 2, falha: a busca da resposta usa `submit`, pega o `_in_flight` ou põe a máquina em `SENDING`;
- a parada durante a geração ficou mais lenta: o máximo de "fim da fala → `stopped`" subiu mais de 0,5 s em relação à mesma parada sem Llama gerando;
- alguma tentativa de parada em frase (eval ou rodada de hardware, procedimento item 4) foi ao Llama ou despachou comando, em vez de virar `stopped` ou `rejected` (decisão do humano, 2026-11-04);
- parada perdida com Llama (decisão do humano, 2026-11-04): na rodada com Llama, o número de paradas em que o robô não parou é maior que zero **e** maior que o da rodada sem Llama. Se as duas rodadas perderem paradas, a comparação é inconclusiva e as duas rodadas se repetem;
- o modelo não cabe: OOM ao carregar, ou alguma camada fora da GPU, com Whisper e Llama carregados juntos.

**Adota se** nenhuma condição de rejeição ocorreu e:

- máximo de "fim da fala → resposta pronta na TV Box" ≤ 6 s;
- máximo de "fim da fala → início real do áudio de espera" ≤ 1,5 s, medido só nas frases de conversa pura. Na mista o `confirmed` toca antes e atrasa o áudio de espera; ali a medida é só informativa;
- respostas perdidas (falha ou prazo) ≤ 10% das frases que caíram no Llama.

**Inconclusivo se** só os limites de latência ou de respostas perdidas falharam. A equipe decide entre rejeitar e tentar otimizar (modelo menor, menos tokens); otimizar exige nova spec.

Um FP do interpretador numa frase **sem** cláusula de conversa (comando errado que não veio do Llama, de eco nem do despacho parcial) não conta contra a E-002. Ele para o teste por segurança e é registrado à parte.

## Procedimento de hardware

1. No server: subir a api (com o robô), o server da branch com `GO2S_SAVE_UTTERANCES=1` e o Llama na GPU. Anotar a VRAM (`nvidia-smi`) e o `n_gpu_layers` com tudo carregado.
2. Na TV Box: atualizar com os WAVs de espera; `df -h` e `free -h` antes e depois.
3. Falar as frases (≥ 30, pelo menos 10 caindo no Llama). **Antes** de cada uma, anotar o desfecho pretendido. Depois, anotar se tocou o áudio de espera, se a resposta chegou e se foi inteligível (anotação livre, fora do critério).
4. Rodada de parada: falar "para" durante a geração (≥ 5 vezes) e o mesmo sem Llama gerando. Anotar se o robô parou; uma parada perdida só com Llama rejeita.
   - Mais ≥ 5 **tentativas de parada em frase**, com o robô andando ou fazendo gesto: "ei, para de me seguir", "olha, para com isso", "você para já que eu mandei". Para cada uma, anotar se foi ao Llama (tocou o áudio de espera) ou se despachou comando. Qualquer uma assim rejeita o experimento (decisão do humano, 2026-11-04). O que se espera é `stopped` ou `rejected`.
5. Quando acontecer de falar a wake word com o áudio de espera ou a resposta tocando, anotar se o som parou e se o comando saiu (anotação livre, fora do critério).
6. Movimento do robô que não veio de comando pretendido: parar o teste e anotar. O log diz a origem: do Llama, de eco ou do despacho parcial (`partial_dispatch`) rejeita; do interpretador numa frase sem cláusula de conversa fica registrado à parte.
7. Para cada frase mista, conferir o comando despachado contra o desfecho anotado antes.

Segurança: deixar `python -m sense.stop` à mão. A parada falada não é garantida.

## Hipóteses não verificadas

- Que Whisper medium e Llama 8B Q4 cabem juntos em 8 GB de VRAM: inferido.
- Que a wake word é detectada com o alto-falante da TV Box tocando a resposta ou o áudio de espera. A métrica foi removida por decisão do humano (2026-11-03); fica sem medida.
- Que o filtro de eco basta. O alto-falante pode tocar algo que o Whisper transcreve diferente do texto original. Além disso, o eco também entra pelo **pré-roll**: o áudio enviado começa `PRE_ROLL_S` antes da wake word, tirado do buffer circular, e esse trecho pode conter o fim da resposta que estava tocando. Interromper o `aplay` não evita isso. A métrica de eco cobre os dois casos; sem medida ainda.
- O prazo de 30 s, o teto de 500 KB, o limite de 24 tokens e o Piper na CPU foram aceitos pelo humano em 2026-11-03 sem medida (é difícil checar sem testar no robô). Continuam **inferidos** até a sessão de hardware.
- Respostas com fatos inventados: risco aceito pelo humano; não é medido.
- Que o filtro de ruído (3 palavras + marcador) separa pedido de ruído: inferido. Contra a conversa alheia ele não protege, porque ela costuma ter marcadores ("você", "me conta"). Quem protege é o F4 (comando só sem embedding na mista), e isso também é inferido.
- O prazo de 10 s do long-poll, o timeout de 12 s do cliente, o mínimo de 3 palavras, a lista de marcadores, a regra de eco (≥ 2 palavras, 10 s) e o intervalo de saúde do llama-server: decididos em 2026-11-04 sem medida; **inferidos**.
- Que o processo separado basta para o Llama não atrasar o Whisper da parada. A GPU é compartilhada; sem medida.

## Resultado

<Preencher depois.>

## Decisão

<Preencher depois.>

## Histórico

- 2026-11-03: criada (proposta), separada da E-001 por decisão do humano; revisada pelo `spec-reviewer`.
- 2026-11-04: revisada antes de implementar, por decisões do humano:
  - frase mista com despacho parcial (qualquer comando menos `damp`; restringido depois pelo F4);
  - filtro de ruído (3 palavras + marcador) também na conversa pura;
  - despacho parcial indevido rejeita o experimento;
  - contrato `thinking` / `reply_pending`;
  - long-poll de 10 s;
  - `llama-server` em processo separado;
  - congelamento em duas etapas: critério e listas antes de implementar; prompt, SHA e parâmetros antes do hardware.
- 2026-11-04: corrigida após o `spec-reviewer`, com decisões do humano:
  - na mista, a cláusula de comando só casa sem embedding (F4), o que exclui a regex da E-001;
  - parada perdida com Llama rejeita;
  - no máximo uma cláusula de conversa por frase (F3);
  - som próprio `reply_failed` quando a resposta da mista não vem.

  Também: invariante de auditoria `llm_reply` × `submit`, `stale` também na conversa pura (F5), saúde do llama-server em segundo plano (F6), regra de eco definida, desfecho pretendido anotado antes de falar e lista de arquivos completa.
- 2026-11-04: aprovada pelo humano, com as frases de `thinking` e `reply_failed` (≥ 4 de cada), saúde do llama-server a cada 2 s com timeout de 0,5 s e os demais números inferidos da tabela de revisão.
- 2026-11-04: frases fixas do filtro de eco com variantes ("Eu. Não. Entender.", "Eu. Confuso.", "Eu. Não. Saber."), com exceção para "não" só nelas; eval da E-002 em arquivo próprio (`eval/conversation_e002.yaml`).
- 2026-11-04: o humano voltou atrás no bloqueio de movimento na mista (vale o F4 anterior). F1 refinado: "para" como preposição não conta dentro de movimento aceito nem no meio da cláusula de conversa; "para" abrindo a cláusula e as demais palavras de parada continuam barrando.
- 2026-11-04: F1 corrigido após o `spec-reviewer`, com decisões do humano:
  - posição contada nos tokens de `_segment`;
  - "para" no fim de qualquer cláusula barra;
  - "para de" e "para com" barram em qualquer posição;
  - tentativa de parada em frase que vai ao Llama ou despacha comando rejeita o experimento, medida no eval e numa rodada nova de hardware.
