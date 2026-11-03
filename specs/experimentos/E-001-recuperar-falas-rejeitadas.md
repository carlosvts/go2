---
id: E-001
titulo: Recuperar falas rejeitadas por incerteza com regex
tipo: experimento
status: em-teste               # proposta | em-teste | adotada | rejeitada
servicos: [server]
branch: exp/recuperar-rejeitadas
criterio-congelado-em: 2026-11-03 @ 5f23fe6   # aprovado pelo humano no chat
verificacao: testado-software  # inferido | testado-software | testado-hardware
verificado-em: null            # AAAA-MM-DD @ <commit>; só humano preenche testado-hardware
alternativa-a: null            # comparador interno: exemplos em discovery/inferred.yaml (ver Abordagem)
---

# E-001 — Recuperar falas rejeitadas por incerteza com regex

O que acontece quando a regex também falha (resposta falada do Llama) é a E-002. Nesta spec, o Llama **não** escolhe comando.

## Problema

O interpretador (`server/app/interpret/interpreter.py`) prioriza precisão: no limiar de produção (`accept=0.95`, `margin=0.10`), a cláusula que não bate por frase exata nem por slots de movimento e fica abaixo do limiar de embedding é rejeitada.

Linha de base em `eval/phrases.yaml` (178 frases **escritas à mão**, sem fala real: 81 comandos, 97 negativas ou parada), medida com `uv run python scripts/calibrate.py` em 2026-11-03 @ `2516071`:

| accept | margin | precisão | revocação | acertos | FP | perdidas |
|---|---|---|---|---|---|---|
| 0.95 | 0.10 | 1.000 | 0.815 | 66 | 0 | 15 |

Baixar o limiar sobe a revocação mas cria falsos positivos (ex.: 0.90/0.10 → revocação 0.840, 3 FP). A regra do serviço é subir revocação **sem** baixar limiar. A equipe avalia que hoje o sistema erra pouco; o ganho esperado é pequeno.

Este experimento ataca só as rejeições por **incerteza do interpretador**. Ficam de fora, com outra correção ou por serem corretas:

- `negation`, `too_many_clauses`, `command_disabled`, `lexical_only_command`: rejeição intencional.
- `movement_missing_direction`, `movement_ambiguous`, `movement_invalid_combination`: movimento sem direção, com duas direções ou com combinação inválida continua rejeitado. Só `movement_unknown_word` entra, e só com direção explícita e verbo determinado (ver Gatilho). `movement_missing_verb` também fica de fora: o código só o produz quando a cláusula é só direção ("para frente", "direita"), e direção sozinha nunca dispara.
- Rejeição da transcrição (Whisper) e `stale`: outra camada; `GO2S_MAX_UTTERANCE_AGE_S` não é relaxado.

## Hipótese

Se uma cláusula rejeitada por incerteza passar por padrões regex por comando, então pelo menos 2 frases da sessão de teste que a `main` rejeitaria passam a sair com o comando pretendido, com 0 comando errado e 0 parada convertida em comando.

## Abordagem

Na branch `exp/recuperar-rejeitadas`. A recuperação mora **dentro do `Interpreter`** (depois de `_resolve`), para que `scripts/calibrate.py` e `evaluate.outcome` meçam exatamente o caminho de produção.

### Onde ficam as regex

Num arquivo só: **`server/regex/patterns.yaml`**. Um bloco por comando, com os padrões e um comentário com exemplos do que cada padrão pretende pegar. Não fica em `discovery/` nem no `catalog.yaml` gerado: a regex não é frase de exemplo e não passa pelo `build_catalog.py`. O `server/AGENTS.md` passa a apontar para esse arquivo no commit da implementação.

### Gatilho

Há dois caminhos, conforme o motivo da rejeição.

**Gestos e posturas.** O motivo é `low_similarity` ou `ambiguous`, e a saída só pode ser gesto ou postura.

- G1. O embedder está carregado. Sem ele não dá para checar G2, e nada é recuperado. O `no_match` de cláusula só acontece sem embedder, então fica excluído aqui.
- G2. Nem o rótulo top-1 nem o top-2 do vizinho mais próximo é `__stop__` ou `__movement__`. Motivo: hoje uma tentativa de parada abaixo de `stop_accept` sai como `low_similarity`, e a recuperação poderia transformá-la em gesto.

**Movimento.** O motivo é `movement_unknown_word` (a cláusula tem palavra do léxico de movimento e sobra uma palavra desconhecida, ex.: "anda rapidinho para frente", "bora para frente"), e a saída só pode ser movimento.

- M1. A cláusula contém **exatamente uma** palavra de direção, reconhecida como o código já reconhece hoje (`_slot_lexical`): léxico `movement.directions` (frente, adiante, trás, atrás, ré, direita, esquerda), comparado sem acento (`fold`), com o erro de 1 letra que o código já aceita em palavras de 5 letras ou mais ("direito" → direita). O padrão **captura** essa palavra e o comando sai dela. Nenhum padrão assume uma direção. Sem palavra de direção, a regex nunca dispara um movimento.
- M2. O verbo (andar ou virar, que decide também entre `strafe_*` e `turn_*`) vem de **um** destes:
  - um verbo do léxico na cláusula (`movement.verbs`, mesmo reconhecimento de M1);
  - ou uma palavra listada no próprio padrão que fixa o verbo (ex.: "bora", "segue" → andar).
  Fora disso, nunca dispara. "pula para frente", "olha para a direita", "aponta para a esquerda", "dança para frente" e "rebola para a direita" continuam rejeitados (estão em `eval/phrases.yaml` como `reject`).
- M3. O `move` continua exigindo `balance_stand`, garantido pelo `prepare` do dispatch, como hoje.

**Para os dois caminhos:**

- C1. A cláusula não contém palavra de parada (`para`, `pare`, `parar`, `stop` e demais `stop_words`). Exceção, **só no caminho de movimento**: `para` usado como preposição **logo antes da direção**. No meio pode haver só um artigo opcional (`a`, `o`, `à`, `ao`, `as`, `os`) e a palavra `lado` opcional: "vai para a esquerda", "vira para o lado direito" (decisão do humano, 2026-11-03). Qualquer outro uso bloqueia, por exemplo "para de dançar", "pare com a dança", "para de andar".
  - A regex vê o texto **já normalizado** por `Catalog.tokenize`, que troca `pra → para`, `pro → para o`, `pras → para as`, `pros → para os` (`language.replacements`). Por isso "anda pra frente" chega como "anda para frente" e os padrões são escritos só com `para`.
  - No caminho de gestos a exceção não tem efeito: cláusula com palavra de direção sempre vai para a resolução de movimento.
- C2. Nenhuma outra cláusula da frase foi rejeitada por motivo fora dos dois caminhos (regra atual: uma cláusula rejeitada rejeita a frase).
- C3. No máximo **uma** cláusula recuperada por frase. Duas ou mais candidatas ⇒ a frase continua rejeitada.

Não roda no `no_match` de nível de frase (frase sem cláusula, só enchimento), na parada e na negação (decididas antes, como hoje).

Para auditoria, `Clause` passa a registrar o rótulo top-1 (e top-2) mesmo quando rejeita; vai para o log em `clauses[]`.

### Regras dos padrões

- Aplicados à cláusula normalizada e **ancorados na cláusula inteira** (match total, não busca parcial).
- Padrão que bate em mais de um comando ⇒ continua rejeitado.
- Nenhum padrão pode bater em frase com `expect: reject` ou `expect: stop` em `eval/phrases.yaml` (teste automático).

### Conjunto de saída permitido

Decisão do humano (2026-11-03): todos os gestos e posturas habilitados e os movimentos, conferidos no `catalog.yaml` de `2516071`, menos `damp`. Movimento só sai pelo caminho de movimento, com direção explícita.

| Entra | Fica fora |
|---|---|
| Gestos e posturas: `stand_up`, `sit`, `stand_down`, `hello`, `stretch`, `finger_heart`, `rise_sit`, `balance_stand`, `recovery_stand`, `wiggle_hips`, `dance1`, `dance2`, `scrape` | `damp` (só frase exata) |
| Movimento: `move_forward`, `move_backward`, `strafe_right`, `strafe_left`, `turn_right`, `turn_left` | `stop` (decidido antes, sem regex) |
| | comandos desabilitados (`content`, `pose`) |

Mudou o catálogo? A lista não muda sozinha; é editada aqui.

**Riscos aceitos:**

- Um FP vira gesto despachado, que **não é cancelável** pela frase seguinte; só o `stop` interrompe. As danças são gestos longos.
- Um FP de `balance_stand` deixa o robô pronto para `move`.
- Um FP de movimento desloca o robô. Até o `stop`, ele anda pelo `duration_s` da regra (inferido). O desvio de obstáculo só faz o robô parar antes de bater; ele não contorna.

### Comparador (alternativa A)

`server/AGENTS.md` manda subir revocação com mais exemplos em `discovery/inferred.yaml`. Para saber se a regex vale mais que isso, quem escreve os padrões escreve também, **antes da sessão**, as frases de exemplo que cada padrão pretende cobrir. Numa execução só em texto, essas frases entram como exemplos em `inferred.yaml` (sem regex) e são avaliadas sobre as mesmas transcrições da sessão.

Efeito colateral: os exemplos exigem rodar `build_catalog.py`, o que muda o `catalog.yaml` e o índice de embeddings inteiro. Por isso o comparador também é medido no conjunto 1 e só conta com segurança OK. O `catalog.yaml` do comparador não entra na branch.

### Limites que não mudam

- A interpretação nunca gera comando fora do catálogo; `_enqueue` continua conferindo os IDs.
- `damp` só por frase exata, nunca por regex.
- Limiares de embedding (`Thresholds`) não mudam.
- `GO2S_MAX_UTTERANCE_AGE_S` não muda.
- O contrato HTTP (`/v1/utterance`) não muda. `clauses[].method` ganha o valor `regex`, só no log. Hoje só os testes leem `method`; ninguém em `app/` ou `scripts/` depende dos valores atuais.

### Ferramenta de medida

`scripts/calibrate.py` ganha:

- um modo de limiar fixo (0.95/0.10), que reporta acertos e FP por `method` e conta a métrica "parada virou comando";
- leitura das transcrições salvas em `captures/` com o rótulo anotado na sessão.

## Dados de teste

1. **Conjunto 1, regressão:** `eval/phrases.yaml` como está em `2516071` (178 frases). Tem de manter 0 FP, 0 parada virando comando e todos os acertos atuais.
2. **Conjunto 2, sessão ao vivo:** decisão do humano, frases ditas na hora, sem arquivo pronto.
   - Pelo menos 30 frases, faladas no robô com o server da branch e `GO2S_SAVE_UTTERANCES=1`.
   - **Antes de cada frase**, o humano anota o desfecho pretendido (comando, `stop` ou `reject`). A anotação não muda depois de ver o resultado.
   - Depois da sessão, as mesmas transcrições salvas passam, em texto, pelo interpretador da `main`, da branch e do comparador. Assim cada frase é falada uma vez só.
   - Pelo menos 10 das 30 são negativas, ou seja, não são comando (decisão do humano, 2026-11-03). Entram vizinhas de `damp` ("desliga", "desligar o robô"), paradas mal faladas e movimento **sem direção** ("anda rapidinho", "bora lá"), que têm de continuar rejeitados.

**Limitações registradas** (aceitas pela equipe):

- A regex é escrita por quem conhece as frases que a equipe costuma falar, então o ganho tende a ser otimista para fala nova.
- Os negativos do conjunto 1 são usados para escrever e checar os padrões, então "0 FP no conjunto 1" não é teste independente.

## Métricas

| Métrica | Como medir | Linha de base |
|---|---|---|
| Frases recuperadas pela regex | conjunto 2: frases com desfecho pretendido = comando, que a `main` rejeita e a branch acerta com `method: regex` | 0 |
| Frases recuperadas pelo comparador | idem, com os exemplos em `inferred.yaml` e sem regex | 0 |
| Comando errado ou indevido (FP) | calibrate, modo fixo, conjuntos 1 e 2; mais o que o robô fez ao vivo | 0 no conjunto 1 |
| Parada virou comando (`expect: stop` → comando) | calibrate, modo fixo | 0 no conjunto 1 |
| Acertos do conjunto 1 perdidos | calibrate, branch × `main` | 0 |
| Custo da regex | microbenchmark em software: p95 do tempo extra por cláusula sobre os conjuntos 1 e 2 | 0 (não existe na main) |

## Critério de decisão (congelar antes de testar)

Definições:

- **Segurança OK**: 0 FP com `method: regex` e 0 parada virando comando nos conjuntos 1 e 2, nenhum acerto do conjunto 1 perdido e nenhum comando errado executado ao vivo vindo da regex.
- **FP atribuído a outro método** (`lexical`, `slots`, `embedding`), que a `main` também cometeria: não conta contra a regex. É registrado no Resultado e vira problema separado.

| Segurança OK | Regex recupera ≥ 2 | Comparador recupera ≥ o mesmo número, com segurança OK | p95 extra ≤ 10 ms (aceito pelo humano; **inferido**) | Resultado |
|---|---|---|---|---|
| não | — | — | — | **Rejeita** |
| sim | não | — | — | **Rejeita** |
| sim | sim | sim | — | **Rejeita a regex**; a recomendação é adotar os exemplos em `inferred.yaml` (fora deste experimento) |
| sim | sim | não | não | **Inconclusivo**: a equipe decide se o custo vale |
| sim | sim | não | sim | **Adota** |

O limite de 2 frases recuperadas é decisão do humano (2026-11-03).

## Procedimento de hardware

1. Critério congelado em `5f23fe6` (decisão do humano). `server/regex/patterns.yaml` e a lista de exemplos do comparador são escritos na implementação e ficam commitados **antes da sessão**; não mudam depois de ver o resultado.
2. Subir a api com o robô e o server da branch com `GO2S_SAVE_UTTERANCES=1`.
3. Para cada frase (≥ 30): anotar o desfecho pretendido, falar depois da wake word e anotar o que o robô fez.
4. Comando executado que não era o pretendido: parar o teste e anotar. Depois, o log (`clauses[].method`) diz se veio da regex (rejeita) ou de outro método (registrado à parte).
5. Depois: rodar o calibrate (modo fixo) sobre as transcrições salvas com a `main`, a branch e o comparador, e preencher Resultado.

Segurança: gesto despachado não é cancelável. Deixar `python -m sense.stop` à mão durante o teste; a parada falada não é garantida.

## Hipóteses não verificadas

- Que a regex dá ganho perceptível é expectativa da equipe, ainda sem medida.
- Limitações do código atual, que a regex não resolve:
  - gesto dito com verbo de movimento ("vai sentar", "vai dançar") sai como `movement_unknown_word` e só poderia virar movimento, que exige direção; continua rejeitado;
  - "vira pro lado direito" chega como "vira para o lado direito": "lado" é palavra desconhecida (cai em `movement_unknown_word`), e "direito" conta como direita pelo erro de 1 letra que o código aceita. É recuperável pela exceção do C1; entra no conjunto 2 como positiva.
- O limite de 10 ms para o custo da regex foi aceito pelo humano em 2026-11-03, mas ninguém mediu: continua **inferido**.

## Resultado

<Preencher depois.>

## Decisão

<Preencher depois.>

## Histórico

- 2026-11-03: implementado na branch (testes de software passam; ver abaixo). Conjunto 1, `calibrate.py --fixed`: main 66 acertos / 0 FP; regex 79 / 0 FP / 0 parada→comando / 0 acerto perdido (13 recuperadas); comparador 78 / 0 FP (12 recuperadas); custo da regex p95 0,104 ms por cláusula. **Atenção:** os padrões foram escritos olhando as 15 perdidas do conjunto 1, então esses números são otimistas; quem decide é a sessão ao vivo (conjunto 2). As 2 que continuam perdidas ("dá um oi para a gente", "acena para mim") têm "para" fora de movimento e ficam bloqueadas por C1, como a spec manda. Nada disso foi testado no robô.
- 2026-11-03: critério congelado em `5f23fe6` (aprovado pelo humano); status `em-teste`, branch `exp/recuperar-rejeitadas`.
- 2026-11-03: criada (proposta), revisada pelo `spec-reviewer`. Mesmo dia: o Llama saiu desta spec e foi para a E-002 (decisão do humano: o Llama não escolhe comando).
