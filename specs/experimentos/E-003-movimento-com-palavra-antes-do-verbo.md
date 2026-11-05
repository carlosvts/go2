---
id: E-003
titulo: Movimento com palavra antes do verbo e verbo repetido
tipo: experimento
status: em-teste               # proposta | em-teste | adotada | rejeitada
servicos: [server]
branch: exp/movimento-prefixo
criterio-congelado-em: 2026-11-05 @ a5396dc   # aprovado pelo humano no chat
verificacao: testado-software  # inferido | testado-software | testado-hardware
verificado-em: null            # AAAA-MM-DD @ <commit>; só humano preenche testado-hardware
alternativa-a: null            # sucede a E-001 (rejeitada em 2026-11-05); ver Histórico
---

# E-003 — Movimento com palavra antes do verbo e verbo repetido

## Problema

Sessão da E-001 no robô (2026-11-04, 25 falas; transcrições na seção Resultado de `E-001-recuperar-falas-rejeitadas.md`). Das 9 falas com intenção de comando que foram rejeitadas, 8 eram movimento com direção explícita:

| Transcrição | Vezes | Motivo | Causa |
|---|---|---|---|
| "Vamos andar para frente / pra frente" | 3 | `movement_unknown_word` | "vamos" não é verbo, direção nem palavra ignorada |
| "Vamos andar para trás" | 3 | `movement_unknown_word` | idem |
| "Mas vamos andar para frente" | 1 | `movement_unknown_word` | "mas" e "vamos" |
| "Vai andar para frente" | 1 | `movement_ambiguous` | "vai" e "andar" são os dois do léxico de `andar` e contam como dois verbos |

Pretendido deduzido da fala; não houve anotação antes (ver E-001).

Como o código trata hoje (conferido em `server/app/interpret/interpreter.py` @ `f0862f3`):

- Toda palavra da cláusula de movimento tem de ser verbo, direção ou estar em `movement.ignore` (`discovery/inferred.yaml`, hoje `[para, a, o, à, ao]`). Qualquer outra dá `movement_unknown_word`.
- `_resolve_movement` rejeita com `movement_ambiguous` quando há mais de um verbo, **mesmo que os dois levem ao mesmo verbo** (`andar`).

Linha de base do conjunto 1 (`eval/phrases.yaml`), medida na E-001 em `2516071`, no limiar 0.95/0.10: 66 acertos, 0 FP, 15 perdidas. `git diff --stat 2516071 f0862f3 -- server/` vem vazio (conferido em 2026-11-05), então a linha de base continua valendo.

Fora deste experimento:

- "Santar" (erro do Whisper para "senta") e os gestos que não convergiam ("vamos sentar", "olá"…): tratados à parte, com exemplos em `discovery/inferred.yaml`, na branch `feat/frases-parada-gestos` (`ac8720d`).
- Frases de parada ("para tudo", "chega", "para de andar"…): mesma branch.
- Pontuação do Whisper que quebra a frase em duas cláusulas ("Vamos, anda pra frente", "Vai, anda pra frente", "Anda... pra frente"): fora por decisão do humano (2026-11-05). Continua rejeitada; é um candidato a outro experimento.
- "Vamos caminhar 5 passos à frente": o move não aceita distância, então a rejeição é correta.
- Limiares de embedding: não mudam.
- Gestos: não mudam.

## Hipótese

Se a cláusula de movimento passar a ignorar uma **lista fechada** de palavras ("vamos", "bora", "lado") e verbos repetidos que levam ao mesmo verbo do catálogo contarem como um só, então, numa sessão nova no robô, pelo menos 2 frases de movimento que a `main` rejeita saem com o comando pretendido, com 0 comando errado e 0 parada virando comando.

## Abordagem

Na branch `exp/movimento-prefixo`.

### Mudança 1: lista fechada de palavras ignoradas

As palavras novas entram em `movement.ignore` de `discovery/inferred.yaml`, e o `catalog.yaml` é regenerado com `scripts/build_catalog.py`. O mecanismo já existe, então não entra código novo de interpretação para isso.

Lista decidida pelo humano em 2026-11-05, a partir dos edge cases em texto (ver Problema):

| Palavra | Origem |
|---|---|
| `vamos` | sessão de 2026-11-04 (7×) |
| `bora` | inferida; sem FP nos edge cases |
| `lado` | inferida; já aceita na E-001 (C1). "anda pro lado direito" → `strafe_right`, "vira pro lado esquerdo" → `turn_left`, "anda pro lado" continua rejeitada |

Ficam **fora**, com o motivo medido nos edge cases:

| Palavra | Motivo |
|---|---|
| `mas` | autocorreção vira dois movimentos: "Vai pra frente, mas vai pra trás." → `move_forward` + `move_backward` |
| `você` | afirmação vira comando: "Você vai pra frente" → `move_forward`; "Você vai para trás?" → `move_backward` |
| `que`, `quero` | iriam junto com `você` ("quero que você ande…") |
| `pode`, `consegue` | pergunta vira comando ("Pode andar para frente?") |
| `de`, `em` | **"Para de andar pra frente" → `move_forward`**, porque `para` já é ignorado. Só serviriam como expressão fechada ("de ré", "em frente"), o que fica fora deste experimento |

Efeitos que valem para qualquer palavra da lista:

- `movement.ignore` vale em **qualquer posição** da cláusula de movimento, não só antes do verbo. É o mecanismo atual, sem código novo; com `vamos`, `bora` e `lado` não apareceu caso ruim nos edge cases.
- A lista só age na resolução de movimento (`_resolve_movement`). Chega-se a ela por palavra do léxico (exata ou com uma letra de erro, como o código já aceita) ou por embedding com rótulo `__movement__`. Frase exata, parada, negação e o embedding de gesto usam a cláusula inteira, então `damp`, parada e gestos não mudam. "vamos desligar" não passa pela lista.

### Mudança 2: verbo repetido conta como um

Decidido pelo humano em 2026-11-05. Em `_resolve_movement`, os verbos são deduplicados pelo verbo do catálogo (`andar`, `virar`) antes de checar ambiguidade. `score` e `margin` continuam sendo o mínimo sobre **todos** os slots, como hoje.

Origem dos slots: um verbo pode vir do léxico exato, do erro de uma letra (`_slot_lexical`) ou do embedding (`_slot_embedding`). Decisão do humano (2026-11-05): deduplicar **só os verbos do léxico exato**. Uma palavra mal transcrita, aproximada de `andar` por erro de letra ou por embedding, continua dando `movement_ambiguous` ao lado de "anda".

Exemplos:

- "vai andar para frente": `vai` → andar, `andar` → andar ⇒ um verbo ⇒ `move_forward`.
- "anda vira para a direita": andar e virar ⇒ continua `movement_ambiguous`.
- Direção repetida ("anda para frente frente") não muda: continua `movement_ambiguous`.

### Ferramenta de medida (trazida da E-001)

O `calibrate.py` da `main` só tem `--data`, `--models` e `--show`. O modo de limiar fixo (`--fixed`) e o `--dump-captures` foram feitos na branch da E-001, que não foi para a `main`, e são trazidos para `exp/movimento-prefixo`, sem a parte de regex e sem o comparador:

- `scripts/calibrate.py`: `--fixed` (`main` × branch, acertos e FP por `method`, "parada virou comando") e `--dump-captures`;
- `app/service.py`: os campos `received_at` e `received_unix` no JSON das capturas, que só servem para ordená-las. É uma mudança em `app/`, mas só no log de captura; o contrato HTTP não muda.

### Testes automáticos (`software`)

Novos em `server/tests/`, com o catálogo regenerado:

| Frase | Esperado |
|---|---|
| "vai andar para frente" | `move_forward` |
| "vamos andar para trás" | `move_backward` |
| "vamos andar pra frente" | `move_forward` |
| "anda vira para a direita" | `movement_ambiguous` |
| "vai virar para a direita" | `movement_ambiguous` |
| "vamos andar" | `movement_missing_direction` |
| "banana andar pra frente" | `movement_unknown_word` |
| "vamos caminhar 5 passos à frente" | rejeitada |
| "bora andar pra frente" | `move_forward` |
| "anda pro lado direito" | `strafe_right` |
| "vira pro lado esquerdo" | `turn_left` |
| "anda pro lado" | `movement_missing_direction` |
| "vai pra frente, mas vai pra trás" | rejeitada (`mas` fora da lista) |
| "você vai pra frente" | rejeitada (`você` fora da lista) |
| "pode andar para frente?" | rejeitada (`pode` fora da lista) |
| "para de andar pra frente" | não pode virar movimento |

Em `server/tests/test_movement_prefix.py`, todos passam: `testado-software` (2026-11-05, branch `exp/movimento-prefixo`). Há também um teste de que verbo aproximado por erro de letra não é deduplicado ("caminhat anda para frente" → `movement_ambiguous`).

Mais o conjunto 1 inteiro com 0 FP (`pytest -m model`). O conjunto 3 é `hardware-only`, com roteiro em `specs/checklists/E-003.md`, que será criado antes de congelar o critério.

### Limites que não mudam

- A direção continua obrigatória e explícita; nunca é assumida.
- Palavra fora do léxico e fora da lista continua dando `movement_unknown_word`. "banana andar pra frente" continua rejeitada.
- `move` continua exigindo `balance_stand`, garantido pelo `prepare` do dispatch.
- A interpretação nunca gera comando fora do catálogo; `damp` só por frase exata.
- Limiares (`Thresholds`) e `GO2S_MAX_UTTERANCE_AGE_S` não mudam.
- O contrato HTTP não muda.

### Comparador

Não há comparador por exemplos em `inferred.yaml`, como havia na E-001: cláusula com verbo ou direção do léxico vai direto para slots e não passa pelo embedding, então exemplos de frase não mudam o resultado de movimento. A comparação é **branch × `main`**.

### Riscos aceitos

- Um FP de movimento desloca o robô por até `duration_s` ou até o `stop`, o que vier antes. `duration_s` vem de `discovery/phrases.json` (3 s para `move_*`, 1 s para `strafe_*`/`turn_*`) e não foi medido no robô. A distância (0,5 m/s × 3 s ≈ 1,5 m) é **inferida**: TODO(humano): medir. O desvio de obstáculo só faz o robô parar antes de bater; não contorna.
- Uma fala que não era pedido ("mas vamos andar para frente depois") pode virar movimento. Ainda não há caso medido.

## Dados de teste

1. **Conjunto 1, regressão:** `eval/phrases.yaml` como está em `a5396dc` (merge de `feat/frases-parada-gestos`): 78 acertos, 0 FP, 40 de 40 paradas no limiar 0.95/0.10. Tem de manter 0 FP, 0 parada virando comando e todos os acertos atuais.
2. **Conjunto 2, sessão de 2026-11-04:** as transcrições registradas na E-001, num arquivo novo `server/eval/sessao-2026-11-04.yaml`, no formato de `eval/phrases.yaml` (`text`/`expect`), com o pretendido deduzido. Ficam de fora: #1 (sem transcrição) e #18 "Amaralre" (pretendido indefinido). #6 "caminhar 5 passos" entra como `reject`. **Não é teste independente**: a lista e a mudança 2 foram escritas olhando essas falas. Serve só como regressão e conferência.
3. **Conjunto 3, sessão nova no robô** (é o conjunto que decide):
   - Pelo menos 30 frases, com o server da branch e `GO2S_SAVE_UTTERANCES=1`.
   - O desfecho pretendido é anotado **antes** de cada frase e não muda depois.
   - Pelo menos 10 frases-alvo (decisão do humano, 2026-11-05), ou seja, movimento com palavra da lista antes do verbo ou com verbo repetido, escritas no roteiro antes da sessão.
   - Pelo menos 10 negativas, entre elas autocorreção ("vai pra frente, mas vai pra trás"), afirmação com "você" ("você vai pra frente"), "para de andar pra frente", movimento sem direção ("vamos andar", "vamos lá"), palavra fora da lista ("banana andar pra frente"), verbos diferentes ("anda vira para a direita") e frases com palavras da lista que não são pedido. TODO(humano): exemplos dessas últimas.
   - Antes da sessão, liberar espaço na TV Box. Na sessão de 2026-11-04 ela não salvou nenhum áudio (`No space left on device`).
   - Depois, as transcrições salvas passam, em texto, pelo interpretador da `main` e da branch.

## Métricas

| Métrica | Como medir | Linha de base |
|---|---|---|
| Frases recuperadas | conjunto 3: desfecho pretendido = movimento, a `main` rejeita e a branch acerta | 0 |
| Comando errado ou indevido (FP) | `calibrate.py` no limiar fixo 0.95/0.10, conjuntos 1, 2 e 3; mais o que o robô fez ao vivo | 0 no conjunto 1 |
| Parada virou comando | idem | 0 no conjunto 1 |
| Acertos do conjunto 1 perdidos | `calibrate.py`, branch × `main` | 0 |

Não há métrica de latência: lista e deduplicação são consulta em conjunto, sem modelo novo. O custo esperado é desprezível, mas é **inferido**.

## Critério de decisão (congelar antes de testar)

Definições:

- **Segurança OK**: 0 FP e 0 parada virando comando nos conjuntos 1, 2 e 3; nenhum acerto do conjunto 1 perdido; nenhum comando errado executado ao vivo.
- Um FP de método que a `main` também cometeria (embedding, frase exata) não conta contra o experimento; é registrado à parte.

| Segurança OK | Recupera ≥ 2 no conjunto 3 | Resultado |
|---|---|---|
| não | — | **Rejeita** |
| sim | não | **Rejeita** |
| sim | sim | **Adota** |

- N = 2 (decisão do humano, 2026-11-05).
- Se o conjunto 3 tiver menos de 30 frases, menos de 10 negativas ou menos de 10 frases-alvo, a sessão não vale e é repetida, sem mudar a lista nem o código (proposta aceita junto com o congelamento, 2026-11-05).
- Se adotada, as frases-alvo e as negativas do conjunto 3 entram em `eval/phrases.yaml`, no mesmo commit do merge.

## Procedimento de hardware

1. Criar `specs/checklists/E-003.md` (skill `hardware-checklist`). Congelar o critério e a lista de palavras antes da sessão; `discovery/inferred.yaml` não muda depois de ver o resultado.
2. Liberar espaço na TV Box (`df -h`) e conferir que os áudios estão sendo salvos.
3. Subir a api com o robô e o server da branch com `GO2S_SAVE_UTTERANCES=1`. Anotar o commit.
4. Para cada frase (≥ 30): anotar o desfecho pretendido, falar depois da wake word e anotar o que o robô fez, inclusive a direção.
5. Se o robô executar um comando que não era o pretendido, parar o teste e anotar a hora.
6. Depois da sessão: `calibrate.py --dump-captures`, rotular com a folha e rodar `--fixed` na `main` e na branch.

Segurança: área livre na direção do movimento; `python -m sense.stop` e o controle à mão. A parada falada não é garantida.

## Hipóteses não verificadas

- Edge cases em texto, com o modelo real e no limiar de produção, sem Whisper e sem robô, em 2026-11-05 @ `f0862f3`: 140 frases, entre alvos, negativas, parada, gestos, `damp`, várias cláusulas, alucinações do Whisper e wake word. A E-003 foi **simulada** num script fora do repo. Com a lista `vamos` e a deduplicação: 0 FP, e 7 das 8 falas de movimento rejeitadas na sessão passam. Com a lista ampla (`mas`, `você`, `pode`…): 4 FP (ver tabela da Mudança 1). Isso não prova nada sobre fala nova.

- Que "vamos", "mas" e as outras palavras da lista sejam frequentes em fala nova. A sessão de 2026-11-04 tinha um falante só e frases repetidas.
- Que nenhuma frase comum com palavra da lista e direção deixe de ser pedido. TODO(humano): pensar em contraexemplos.
- `duration_s` das regras de movimento vem de `discovery/phrases.json`, sem medida no robô; a distância percorrida é **inferida**.

## Resultado

<Preencher depois.>

## Decisão

<Preencher depois.>

## Histórico

- 2026-11-05: implementado na branch. Testes passam (194 rápidos e 4 com o modelo real). `calibrate.py --fixed`:
  - conjunto 1: main 78 / 0 FP / 40 de 40 paradas; branch 78 / 0 FP / 40 de 40, sem nada recuperado e nada perdido;
  - conjunto 2 (`eval/sessao-2026-11-04.yaml`): main 11 acertos / 0 FP; branch 18 / 0 FP, com 7 recuperadas. A única que continua perdida é "Mas vamos andar para frente" (`mas` fora da lista).
  Otimista: o conjunto 2 foi usado para escrever a mudança. Só texto; nada no robô.
  Para reproduzir a `main` no mesmo processo, o `Interpreter` ganhou `dedupe_verbs`, ligado por padrão; só o `calibrate.py` o desliga.
- 2026-11-05: critério congelado (N = 2, M = 10, deduplicação só do léxico exato, linha de base `a5396dc`); status `em-teste`, branch `exp/movimento-prefixo`.
- 2026-11-05: decisões do humano: lista `vamos`, `bora`, `lado`; deduplicação de verbo sim; pontuação do Whisper fora. Edge cases em texto registrados.
- 2026-11-05: revisada pelo `spec-reviewer`. Entraram: ferramenta trazida da E-001, testes de software, risco de autocorreção com `mas`, origem dos verbos deduplicados e mínimo de frases-alvo.
- 2026-11-05: criada (proposta), a partir da sessão da E-001 de 2026-11-04. Sucede a E-001 (rejeitada).
