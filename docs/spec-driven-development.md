# Spec-driven development no go2

O comportamento do sistema é escrito em `specs/` **antes** do código. Uma IA escreve a maior parte do código; quem decide e quem valida no robô é a equipe. As regras completas estão em [`specs/README.md`](../specs/README.md), e as regras para agentes, nos `AGENTS.md`.

## Precisa de spec?

| Mudança | Spec | Onde |
|---|---|---|
| Rota, campo ou status HTTP entre serviços | sim | `specs/contracts/` (regenerado do código) |
| Regra de segurança | sim | `specs/features/F-NNN-*.md`, `tipo: seguranca` |
| Feature com comportamento não trivial | sim | `specs/features/F-NNN-*.md` |
| Experimento (ex.: regex × LLM, calibração, política de fila) | sim | `specs/experimentos/E-NNN-*.md` |
| Decisão de escopo ("sem lease", "bípede fora") | sim | `specs/decisions/D-NNN-*.md` |
| Config, limiar, bugfix pequeno | não | — |
| Habilitar ou desabilitar comando, frases novas | não | `server/discovery/inferred.yaml` + `server/eval/phrases.yaml` |

## Estados de uma spec

```yaml
status: proposta | em-implementacao | em-teste | adotada | rejeitada | obsoleta
verificacao: inferido | testado-software | testado-hardware
verificado-em: null   # AAAA-MM-DD @ commit
```

- `inferido`: ninguém mediu nem testou. Número sem medida leva `TODO(humano): medir`.
- `testado-software`: os testes automáticos passam. Mock não prova o robô.
- `testado-hardware`: **só um humano** marca, depois de testar no robô ou na TV Box.

## As skills (Claude Code)

As skills ficam em `.claude/skills/`. Chame pelo nome (`/new-spec`) ou peça em texto ("cria uma spec para…").

| Skill | Quando |
|---|---|
| `new-spec` | antes de codar algo que precisa de spec |
| `spec-reviewer` (agente) | ao terminar a spec, ou ao mudá-la |
| `implement-spec` | a spec foi aprovada |
| `check-contracts` | mudou contrato HTTP, ou antes de abrir PR que toca `api/` ou `server/` |
| `hardware-checklist` | a spec tem critérios `hardware-only` e alguém vai ao lab |
| `close-experiment` | a equipe trouxe os resultados medidos de um experimento |

## Fluxo 1: feature nova (o mais comum)

1. **Pedir a spec:** `/new-spec` + o que a feature deve fazer. A IA pergunta o que não sabe e cria `specs/features/F-NNN-slug.md` com `status: proposta`.
2. **Revisar:** a IA roda o `spec-reviewer`. Você lê a spec, responde os `TODO(humano)` e aprova no chat.
3. **Implementar:** `/implement-spec F-NNN`. A IA cria a branch `feat/<slug>`, escreve um teste por critério `software` (que falha), implementa e roda os testes do serviço. Os critérios passam a `testado-software`.
4. **PR:** abrir para a `main`. O CI roda os testes do serviço e o `contracts-check`.
5. **Lab:** `/hardware-checklist F-NNN` gera o roteiro dos critérios `hardware-only`. A equipe testa e passa os números à IA, que registra critério por critério. Só depois disso `testado-hardware`, e a spec vira `adotada`.

## Fluxo 2: experimento

1. `/new-spec` com o problema e a ideia. A spec `E-NNN` sai com hipótese, dados de teste, métricas com linha de base e **critério de decisão em números**.
2. Você aprova o critério e ele é **congelado** (`criterio-congelado-em: AAAA-MM-DD @ commit`) antes de qualquer teste. Mudar a régua depois invalida o experimento.
3. `/implement-spec E-NNN` na branch `exp/<nome>`, com `status: em-teste`.
4. Teste no lab com `/hardware-checklist E-NNN`.
5. `/close-experiment E-NNN` compara o resultado com o critério e propõe a decisão. Você decide:
   - **adotada:** merge na `main`;
   - **rejeitada:** o código sai, e a spec fica com o resultado, como registro do que já foi tentado.

## Fluxo 3: mudança de contrato

Mudou `/v1/utterance`, `/v1/cancel`, `/health`, `/capabilities` ou qualquer rota da api:

```bash
# server
cd server && uv run python -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False))" > ../specs/contracts/server.openapi.json

# api (precisa do PortAudio instalado: portaudio-devel no Fedora, portaudio19-dev no Debian)
cd api && GO2_CONNECTION_METHOD=LocalAP GO2_CONNECT_ON_STARTUP=false uv run python -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False))" > ../specs/contracts/api.openapi.json
```

Ou só `/check-contracts`. Regras:
- O código e o contrato entram **no mesmo commit**.
- Atualize no mesmo PR os consumidores afetados (tabela em [`specs/contracts/README.md`](../specs/contracts/README.md)).
- Se o `contracts-check` falhar, o código mudou o contrato sem atualizar `specs/contracts/`.

## Fluxo 4: catálogo e frases (sem spec)

```bash
cd server
# editar discovery/inferred.yaml (ou discovery/phrases.json)
uv run python scripts/build_catalog.py          # regenera catalog.yaml; nunca edite à mão
# acrescentar as frases novas e as negativas em eval/phrases.yaml
uv run pytest && uv run pytest -m model         # -m model usa o modelo de embeddings em cache
uv run python scripts/calibrate.py --show 0.95,0.10
```

A meta é **0 falsos positivos**, principalmente em movimento e `damp`. Para subir a revocação, acrescente exemplos; não baixe o limiar.

## Antes de abrir PR

- [ ] Testes do serviço tocado passam (comandos no `AGENTS.md` dele).
- [ ] Mexeu em interpretação: eval com 0 falsos positivos.
- [ ] Mexeu em contrato: `specs/contracts/` atualizado no mesmo commit.
- [ ] A spec foi atualizada junto com o código, e nada está marcado `testado-hardware` sem teste no robô.
- [ ] O PR diz o que não foi possível testar.
