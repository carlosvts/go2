---
name: implement-spec
description: Implementa uma spec aprovada (feature, segurança ou experimento) criando os testes a partir dos critérios de aceite antes do código. Use quando o um humano mandar implementar uma spec F-/E- existente.
---

# implement-spec

Implementa o que a spec diz, nada além, e deixa claro o que ficou sem verificar.

## Pré-condições

- A spec existe em `specs/` e um humano a aprovou (`status: proposta` aprovada no chat, ou `em-implementacao`). Spec sem aprovação: pare e peça.
- Experimento: `criterio-congelado-em` precisa estar preenchido. Se estiver `null`, pare e peça a um humano para congelar o critério. **Não congele você mesmo.**
- Se houver TODO ou ponto ambíguo que muda o comportamento, pergunte antes de codar.

## Passos

1. **Leia**: a spec inteira, `AGENTS.md` raiz e do serviço, `specs/glossario.md`, contratos tocados.
2. **Branch**: feature em `feat/<slug>`; experimento na branch do frontmatter (`exp/<nome>`). Atualize `status: em-implementacao` (feature) ou `em-teste` (experimento).
3. **Testes primeiro**: para cada critério `software`, escreva o teste que o expressa e confirme que ele **falha** antes da implementação. Critério `hardware-only` não vira teste; ele vira item do roteiro (skill `hardware-checklist`).
4. **Implemente** o mínimo para os testes passarem. Respeite as regras de segurança do `AGENTS.md` raiz. Não adicione comportamento que a spec não pede.
5. **Contrato**: se mudou rota, campo ou status HTTP, atualize `specs/contracts/` no mesmo commit (skill `check-contracts`).
6. **Rode** os testes do serviço tocado (comandos no `AGENTS.md` dele) e, se mexeu em interpretação, `eval/phrases.yaml` (meta: 0 falsos positivos).
7. **Atualize a spec**:
   - coluna Verificação dos critérios `software` que passaram: `testado-software (AAAA-MM-DD @ commit)`;
   - `verificacao: testado-software` no frontmatter só se **todos** os critérios `software` passaram;
   - **nunca** `testado-hardware` nem `verificado-em`.
8. **Entregue** um resumo curto: o que mudou, testes que passam, critérios `hardware-only` pendentes, o que não pôde ser rodado, e o próximo passo (`hardware-checklist`). Se for experimento, não decida adotar ou rejeitar; isso é `close-experiment`, depois do teste humano.

## Não faça

- Não marque spec como `adotada` sem o teste de hardware dos critérios `hardware-only`, quando existirem.
- Não ajuste limiar, dado de teste ou critério para fazer um teste passar.
- Não trate teste com mock como prova de comportamento no robô.
- Não implemente fora do escopo (ver "Fora de escopo" da spec); se achar algo necessário, proponha spec nova.
