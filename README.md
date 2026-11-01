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

## Levar a TV Box do go2-tvbox antigo para este monorepo

A TV Box do laboratório ainda roda o clone do repositório antigo [`go2-tvbox`](https://github.com/carlosvts/go2-tvbox) (em `/home/minipc/go2-tvbox`; ajuste o caminho se for outro). O código de `tvbox/` é o mesmo, com o modo edge removido. Um `.env` antigo continua servindo: as chaves que saíram são ignoradas. A TV Box nova conversa com o server antigo e vice-versa (ela só deixou de mandar `local_hypothesis` e `local_confidence`, que o server sempre tratou como opcionais), então não é preciso trocar os dois ao mesmo tempo.

O disco raiz da TV Box está perto de 90%, então nunca clone o monorepo inteiro lá: use o clone parcial abaixo, que traz só `tvbox/` e `specs/contracts/`.

1. **Confira espaço e memória**, e anote os valores:

   ```bash
   df -h / && free -h
   ```

2. **Pare o Sense antigo.** Se ele roda num terminal, Ctrl+C. Se a unit systemd antiga chegou a ser instalada, desligue e remova (o monorepo não usa mais systemd na TV Box):

   ```bash
   systemctl status go2-sense                  # "could not be found" = não estava instalada; pule o resto
   sudo systemctl disable --now go2-sense
   sudo rm /etc/systemd/system/go2-sense.service /etc/systemd/journald@go2-sense.conf
   sudo systemctl daemon-reload
   ```

3. **Veja o que só existe no clone antigo** (não está no git e não vem no clone novo):

   ```bash
   cd ~/go2-tvbox
   git status --short --ignored
   ```

   Guarde o que aparecer e for seu: o `.env` (obrigatório), WAVs novos em `media/` (por exemplo `blocked*.wav`) e, se quiser, as falas gravadas em `utterances/`. `.venv/` e `__pycache__/` não precisam: são recriados.

4. **Clone parcial do monorepo** (o repositório é público, então HTTPS dispensa chave SSH na TV Box):

   ```bash
   cd ~
   git clone --filter=blob:none --sparse https://github.com/carlosvts/go2.git
   cd go2
   git sparse-checkout set tvbox specs/contracts
   ```

5. **Traga o `.env` e os arquivos do passo 3:**

   ```bash
   cp ~/go2-tvbox/.env ~/go2/tvbox/.env
   cp ~/go2-tvbox/media/blocked*.wav ~/go2/tvbox/media/    # só se existirem
   ```

6. **Instale e baixe o modelo da wake word.** O modelo `hey_jarvis` fica dentro do `.venv`, então o ambiente novo precisa baixá-lo de novo (precisa de internet). As dependências de sistema (`portaudio19-dev gcc python3-dev`) já estão instaladas da versão antiga.

   ```bash
   cd ~/go2/tvbox
   uv sync --no-dev --extra capture --extra recognition
   uv run python scripts/download_models.py
   ```

   Se faltar disco, apague antes o `.venv` antigo, que dá para recriar: `rm -rf ~/go2-tvbox/.venv`.

7. **Teste:**

   ```bash
   curl http://<IP_DO_SERVIDOR>:9000/health    # o server tem de responder 200
   uv run python -m sense.say --all            # beep e falas de retorno no Anker
   uv run python -m sense                      # "Wake word pronta", "Servidor de inferência no ar", "Microfone aberto"
   ```

   O log de partida mostra `código=main@<commit>` do monorepo. Tenha a parada manual (`uv run python -m sense.stop`) pronta num terminal.

8. **Depois que estiver funcionando**, apague o clone antigo (confira antes que nada do passo 3 ficou para trás) e anote de novo o `df -h /`:

   ```bash
   rm -rf ~/go2-tvbox
   ```

Para atualizar depois: `cd ~/go2 && git pull`, e rode `uv sync --no-dev --extra capture --extra recognition` de novo se `tvbox/pyproject.toml` ou `tvbox/uv.lock` mudarem. Mais detalhes em [`tvbox/README.md`](tvbox/README.md) e no roteiro de laboratório em [`tvbox/docs/checklist-laboratorio.md`](tvbox/docs/checklist-laboratorio.md).

## CI

Um workflow por serviço em `.github/workflows/`, disparado só quando a pasta dele muda: `api-ci.yml` e `api-build.yml`, `server-ci.yml`, `tvbox-ci.yml`. O `contracts-check.yml` confere `specs/contracts/` contra o OpenAPI de api e server.
