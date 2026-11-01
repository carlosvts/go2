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

Tipo: `software` (vira teste) ou `hardware-only` (precisa de robô/TV Box; roteiro abaixo).
Verificação: `inferido`, `testado-software` ou `testado-hardware (AAAA-MM-DD @ commit)`.

## Fora de escopo
<O que esta spec **não** cobre, de propósito.>

## Segurança
<Que regra de segurança do AGENTS.md raiz isto toca? O que acontece se der errado com o robô físico?>

## Hipóteses não verificadas
<Valores e suposições que ninguém mediu. Cada uma com `TODO(humano): medir` quando aplicável.>

## Roteiro hardware-only
<H1: passos numerados, o que observar, o que registrar (valores, vídeo, log).>

## Histórico
- AAAA-MM-DD: criada (proposta).
