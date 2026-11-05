---
id: F-000
titulo: <título curto>
tipo: comportamento            # comportamento | seguranca
status: proposta               # proposta | em-implementacao | adotada | obsoleta
servicos: []                   # api | server | tvbox
verificacao: inferido          # inferido | testado-software | testado-hardware
verificado-em: null            # AAAA-MM-DD @ <commit>; só humano preenche testado-hardware
depende-de: []                 # outras specs (F-00N, D-00N, contratos)
---

# F-000 — <título>

## Objetivo
<Uma ou duas frases: que problema isto resolve e para quem.>

## Comportamento
<O que o sistema faz, em termos observáveis. Entradas, saídas, estados, erros.
Sem detalhes de implementação, a menos que sejam parte do contrato.>

## Critérios de aceite

| ID | Critério (observável) | Como verificar | Tipo | Verificação |
|---|---|---|---|---|
| A1 | <dado X, quando Y, então Z> | `<teste automático ou roteiro>` | software | inferido |
| A2 | <...> | roteiro H1 | hardware-only | inferido |
| A3 | <uma pessoa que não conhece o sistema, ao ouvir o retorno de rejeição X, diz o que fazer em seguida> | roteiro H2 | usuario | inferido |

Tipo: `software` (vira teste), `hardware-only` (precisa de robô/TV Box; roteiro abaixo) ou `usuario` (percepção de uma pessoa que não conhece o sistema; roteiro abaixo; só humano valida).
Verificação: `inferido`, `testado-software`, `testado-hardware (AAAA-MM-DD @ commit)` ou `testado-usuario (AAAA-MM-DD @ commit, n=<pessoas>)`.

## Fora de escopo
<O que esta spec **não** cobre, de propósito.>

## Segurança
<Que regra de segurança do AGENTS.md raiz isto toca? O que acontece se der errado com o robô físico?>

## Impacto HRI
<Obrigatória. Se a mudança não altera nada que a pessoa vê, ouve ou espera do robô, escreva `Sem impacto HRI: <motivo>` e apague a tabela. Resposta em branco não vale; sem dado, `inferido` + `TODO(humano)`.>

| Pergunta | Resposta |
|---|---|
| Que interação da pessoa com o robô isto muda? | |
| O que a pessoa percebe em sucesso, rejeição, erro e espera? (som, fala, gesto) | |
| Latência percebida: última palavra → primeiro retorno (antes → depois) | `<medido>` ou `inferido` + `TODO(humano): medir` |
| O retorno promete algo que o sistema não fez? (aceito ≠ executado) | |
| Pode surpreender ou assustar quem está perto? A fala/som do robô pode entrar no microfone? | |
| Quem usa (leigo, criança, plateia)? Algo muda para eles? | |
| Como validar com uma pessoa que não conhece o sistema? | critério `usuario` acima |

## Hipóteses não verificadas
<Valores e suposições que ninguém mediu. Cada uma com `TODO(humano): medir` quando aplicável. Inclua as de percepção ("a pessoa entende o som").>

## Roteiro hardware-only
<H1: passos numerados, o que observar, o que registrar (valores, vídeo, log).
Critérios `usuario`: H2 com a pessoa **sem explicar o sistema antes**; registrar o que ela disse e fez, o que a surpreendeu, e quantas pessoas (n).>

## Histórico
- AAAA-MM-DD: criada (proposta).
