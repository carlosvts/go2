# go2

Controle por voz do robô Unitree Go2 (NEURON/UFLA). Três serviços independentes, que só conversam por HTTP:

```
TV Box (tvbox/) ──áudio──▶ go2-server (server/) ──HTTP──▶ go2-api (api/) ──WebRTC──▶ Go2
```

| Pasta | O que é | Onde roda |
|---|---|---|
| [`api/`](api/) | go2-api: dona da única conexão WebRTC com o robô, expõe os comandos por HTTP | PC do laboratório |
| [`server/`](server/) | go2-server: transcrição (Whisper), interpretação e fila de comandos de voz | PC do laboratório |
| [`tvbox/`](tvbox/) | Go2 Sense: wake word e envio do comando falado ao server | TV Box (ARM) |
| [`specs/`](specs/) | contratos, features e decisões (spec-driven, em construção) | — |

Cada serviço tem o próprio `pyproject.toml`, `uv.lock`, `.env` e README. Nenhum importa código de outro.

## Como rodar

Detalhes e configuração no README de cada pasta.

```bash
# api
cd api && cp .env.example .env && uv sync
uv run uvicorn app.main:create_app --factory

# server
cd server && cp .env.example .env && uv sync
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 9000

# tvbox (na TV Box; veja o clone parcial em tvbox/README.md)
cd tvbox && cp .env.example .env && uv sync --no-dev --extra capture --extra recognition
uv run python -m sense
```

Com Docker, api e server juntos (cada um com o seu `.env` na própria pasta):

```bash
docker compose --profile api --profile server up -d --build
```

## Como usar o spec-driven development

O comportamento do sistema é descrito em [`specs/`](specs/) antes do código. Os READMEs dos serviços dizem só como rodar. As regras completas estão em [`specs/README.md`](specs/README.md), e as regras para quem programa (inclusive agentes de IA) estão nos `AGENTS.md` da raiz e de cada serviço.

| Pasta | O que guarda |
|---|---|
| `specs/contracts/` | Contratos HTTP entre os serviços (`api.openapi.json`, `server.openapi.json`), conferidos contra o código no CI |
| `specs/features/` | `F-NNN`: comportamento e regras de segurança |
| `specs/experimentos/` | `E-NNN`: hipótese, critério de decisão congelado antes do teste, resultado |
| `specs/decisions/` | `D-NNN`: o que foi decidido e por quê, inclusive o que ficou de fora de propósito |
| `specs/_templates/` | Modelos de feature, experimento e decisão |
| `specs/glossario.md` | Termos do projeto e o que eles não significam |

Precisa de spec: contrato entre serviços, regra de segurança, feature com comportamento não trivial, experimento e decisão de escopo. Não precisa: config, limiar, bugfix pequeno, habilitar ou desabilitar comando do catálogo (mas frases novas entram em `server/eval/phrases.yaml`).

Fluxo, com as skills de `.claude/skills/` (Claude Code):

1. **`new-spec`**: escreve a spec a partir do template, sem inventar números. O que ninguém mediu fica `inferido`, com `TODO(humano)`. O agente `spec-reviewer` revisa.
2. Um humano aprova a spec. Em experimento, ele congela o critério de decisão antes de qualquer teste.
3. **`implement-spec`**: testes a partir dos critérios de aceite, depois o código, numa branch `feat/<slug>` ou `exp/<nome>`.
4. **`check-contracts`**: mudou rota, campo ou status HTTP? Regenere `specs/contracts/` no mesmo commit. O workflow `contracts-check` falha se o contrato e o código divergirem.
5. **`hardware-checklist`**: monta o roteiro dos critérios `hardware-only` e registra o que a equipe mediu no robô ou na TV Box.
6. **`close-experiment`**: fecha o experimento como adotado (merge) ou rejeitado (o código sai, a spec fica como registro).

`verificacao: testado-hardware` e `verificado-em` só são preenchidos por um humano da equipe, depois de testar no robô. Teste automático com mock não prova comportamento físico.

## CI

Um workflow por serviço em `.github/workflows/`, disparado só quando a pasta dele muda: `api-ci.yml` e `api-build.yml`, `server-ci.yml`, `tvbox-ci.yml`. O `contracts-check.yml` confere `specs/contracts/` contra o OpenAPI de api e server.
