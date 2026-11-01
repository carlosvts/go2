---
id: E-000
titulo: <título curto>
tipo: experimento
status: proposta               # proposta | em-teste | adotada | rejeitada
servicos: []                   # api | server | tvbox
branch: exp/<nome>
criterio-congelado-em: null    # AAAA-MM-DD @ commit, preenchido ANTES de começar a testar
verificacao: inferido          # inferido | testado-software | testado-hardware
verificado-em: null            # AAAA-MM-DD @ <commit>; só humano preenche testado-hardware
alternativa-a: null            # E-00N que este experimento substitui se for rejeitado/adotado
---

# E-000 — <título>

## Problema
<O que está ruim hoje, com números reais (de logs, `captures/`, testes). Separe causas: o que este experimento ataca e o que tem outra correção.>

## Hipótese
<Se fizermos X, então Y, medido por Z.>

## Abordagem
<O que será implementado na branch do experimento. Limites: o que não pode mudar
(ex.: nunca gerar comando fora do catálogo; `damp` só por frase exata).>

## Dados de teste
<Conjunto usado: arquivo, origem, tamanho, como foi rotulado. Congelado: não adicionar casos depois de ver o resultado para fazer passar.>

## Métricas
| Métrica | Como medir | Linha de base |
|---|---|---|
| Falsos positivos em movimento e `damp` | `<comando>` | 0 |
| Revocação | `<comando>` | <valor atual> |
| Latência p95 | `<comando>` | <valor atual> |

## Critério de decisão (congelar antes de testar)
- **Adota se:** <condições objetivas, com números>.
- **Rejeita se:** <condições objetivas>.
- **Inconclusivo se:** <condições; o que fazer nesse caso>.

## Procedimento de hardware
<Passos que o humano executa. O que registrar.>

## Resultado
<Preencher depois. Valores medidos, data, commit, comparação com a linha de base. Se rejeitado: por que falhou.>

## Decisão
<adotada | rejeitada, quem decidiu, quando. Se adotada: merge em main e spec de comportamento/contrato correspondente atualizada. Se rejeitada: código removido; esta spec permanece.>

## Histórico
- AAAA-MM-DD: criada (proposta).
