---
name: new-spec
description: Cria uma spec nova (feature, segurança, experimento, decisão ou contrato) a partir dos templates em specs/_templates, entrevistando o humano para não inventar nada. Use quando um humano pedir uma spec, ou antes de implementar feature, mudança de contrato ou experimento que ainda não tem spec.
---

# new-spec

Escreve a spec **antes** do código. As decisões são humanas: você redige, ele decide.

## Passos

1. **Classifique** o pedido: `feature` (comportamento), `seguranca`, `experimento`, `decisao` ou `contrato`. Se não precisa de spec (config, limiar, bugfix pequeno), diga isso e pare. Veja a tabela em `specs/README.md`.
2. **Próximo ID**: liste `specs/features`, `specs/experimentos`, `specs/decisions` e use o maior número + 1 (`F-001`, `E-001`, `D-001`). Nome do arquivo: `F-001-slug-curto.md`.
3. **Leia o contexto**: `AGENTS.md` da raiz e do serviço tocado, `specs/glossario.md`, specs existentes relacionadas, os contratos em `specs/contracts/`. Não escreva spec que contradiga uma decisão aceita.
4. **Copie o template** de `specs/_templates/` e preencha. O que o humano não disse e você não pode confirmar no código vira:
   - `inferido` na coluna Verificação; e
   - `TODO(humano): ...` na seção Hipóteses não verificadas.
   Nunca preencha número que ninguém mediu.
5. **Critérios de aceite**: cada um observável e verificável (dado/quando/então). Classifique como `software` (vai virar teste) ou `hardware-only` (com roteiro). Critério vago ("rápido", "robusto") não vale; peça o número a um humano ou marque TODO.
6. **Experimento**: preencha hipótese, dados de teste, métricas com linha de base, e o **critério de decisão** com números. Deixe `criterio-congelado-em: null`; ele só é preenchido quando um humano aprovar o critério, antes de qualquer teste.
7. **Frontmatter**: `status: proposta`, `verificacao: inferido`, `verificado-em: null`. Nunca `testado-hardware`.
8. **Revise**: rode o agente `spec-reviewer` na spec e corrija o que ele apontar de ambiguidade ou critério não testável.
9. **Entregue**: caminho do arquivo, as perguntas abertas (TODOs) em lista curta e o que você precisa que o humano decida. Não comece a implementar; isso é a skill `implement-spec`, depois da aprovação dele.

## Não faça

- Não invente durações, payloads, latências ou limiares.
- Não escreva spec descrevendo implementação quando o comportamento basta.
- Não crie spec para o que já está decidido em `specs/decisions/`; referencie a decisão.
