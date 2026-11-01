# specs/

Fonte da verdade do **comportamento** do sistema. O README de cada serviço diz só como rodar.

```
specs/
├── contracts/     contratos HTTP entre serviços (openapi.json de api e server, schema do catálogo)
├── features/      F-001-...  comportamento e segurança
├── experimentos/  E-001-...  hipótese → teste → adota ou rejeita
├── decisions/     D-001-...  por que sim, por que não (inclui o que ficou de fora de propósito)
├── checklists/    roteiros hardware-only (criados pela skill hardware-checklist, se preferido)
├── glossario.md
└── _templates/
```

## Quando escrever spec

| Situação | Spec? |
|---|---|
| Contrato entre serviços (campo novo, status novo) | Sim, em `contracts/` |
| Regra de segurança | Sim, tipo `seguranca` |
| Feature nova com comportamento não trivial | Sim, em `features/` |
| Experimento (regex × LLM, calibração, política de fila) | Sim, em `experimentos/` |
| Decisão de escopo ("sem lease", "bípede fora") | Sim, em `decisions/` |
| Config, limiar, bugfix pequeno | Não |
| Habilitar/desabilitar comando | Não (é dado do catálogo), mas frases novas entram em `eval/phrases.yaml` |

## Frontmatter

```yaml
tipo: comportamento | contrato | seguranca | experimento
status: proposta | em-implementacao | em-teste | adotada | rejeitada | obsoleta
verificacao: inferido | testado-software | testado-hardware
verificado-em: null          # AAAA-MM-DD @ <commit>
```

- `verificacao` diz o que **se sabe**, não o que se espera.
  - `inferido`: ninguém mediu nem testou.
  - `testado-software`: testes automáticos passam (podem usar mock; isso não prova o robô).
  - `testado-hardware`: um humano da equipe rodou no robô/TV Box e relatou. **Só humano preenche.**
- `status` de experimento: `proposta → em-teste → adotada | rejeitada`.
- Critério individual também tem estado: cada linha da tabela de aceite marca `inferido`, `software` ou `hardware`.

## Regras

1. **Spec sem teste não conta.** Critério de aceite vira teste automático, ou fica marcado `hardware-only` com roteiro.
2. **Afirmação sem medida é `inferido`.** Número que ninguém mediu leva a marca explícita; nunca vira requisito firme.
3. **Experimento: critério de decisão escrito antes de testar** e congelado (`criterio-congelado-em`). Mudar a régua depois invalida o experimento.
4. **Rejeitado não é deletado.** O código sai; a spec fica com `status: rejeitada` e a seção Resultado preenchida. É o registro do que já foi tentado.
5. **Mesmo commit.** Mudança de comportamento ou contrato atualiza a spec junto com o código.
6. **Adotada ≠ eterna.** Feature removida vira `obsoleta` com o motivo; spec desatualizada é bug.

## Fluxo de experimento

```
spec E-00N (proposta) → critério congelado → branch exp/<nome> → implementa
  → roda testes de software → humano testa em hardware
     ├─ passou o critério → merge na main, spec "adotada"
     └─ falhou → descarta o código, spec "rejeitada" + resultado → próxima spec/branch
```

Skills em `.claude/skills/`: `new-spec`, `implement-spec`, `close-experiment`, `hardware-checklist`, `check-contracts`. Agente revisor: `spec-reviewer`.
