---
name: check-contracts
description: Exporta o OpenAPI de api e server e o schema do catálogo, compara com specs/contracts e reporta divergências (ou inicializa os arquivos de contrato). Use ao mudar rota, campo ou status HTTP, antes de abrir PR que toque contrato, ou na primeira vez para criar a linha de base.
---

# check-contracts

Garante que `specs/contracts/` e o código dizem a mesma coisa.

## Comandos

Exportar o OpenAPI direto do app, sem subir o servidor:

```bash
# api (modo sem robô: LocalSTA exige IP ou serial só para criar o app)
cd api && GO2_CONNECTION_METHOD=LocalAP GO2_CONNECT_ON_STARTUP=false uv run python -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False))" > /tmp/api.openapi.json

# server
cd server && uv run python -c "import json; from app.main import create_app; print(json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False))" > /tmp/server.openapi.json
```

Os dois comandos são os mesmos do workflow `.github/workflows/contracts-check.yml`. O da api precisa do PortAudio instalado para o `uv sync` compilar o `pyaudio` (sem ele: "you need to install a library that provides portaudio.h"); no CI, a composite action `.github/actions/api-setup` instala. Localmente, instale o pacote de desenvolvimento do PortAudio (`portaudio19-dev` no Debian/Ubuntu, `portaudio-devel` no Fedora) ou rode num container com ele. Se algum import falhar, diga qual e não improvise outro caminho.

## Modos

**Verificar** (padrão): compare `/tmp/*.openapi.json` com `specs/contracts/api.openapi.json` e `server.openapi.json`.
- Sem diferença: reporte "contratos em dia".
- Com diferença: mostre o diff **resumido** (rotas adicionadas/removidas, campos, status, tipos) e pergunte se a mudança é intencional. Se for, atualize o arquivo em `specs/contracts/` e lembre de commitar junto com o código. Se não for, o código quebrou o contrato: aponte o ponto.
- Consumidores afetados: indique quem consome a rota alterada (tabela em `specs/contracts/README.md`) e se precisa mudar junto.

**Inicializar** (primeira vez, arquivos ausentes): grave os dois OpenAPI em `specs/contracts/` e avise que são a linha de base do **código atual**, não do que foi validado em hardware.

**Catálogo**: se `server/catalog.schema.json` ainda não existir em `specs/contracts/`, proponha um schema (campos de comando: nome, frases, `max_duration_s`, `enabled`, indicador medido/inferido) e peça aprovação antes de adicionar a validação em `build_catalog.py`.

## CI

Se o repositório ainda não tem o check, proponha um workflow que gera o OpenAPI de cada serviço e falha se `git diff --exit-code specs/contracts/` acusar mudança. Mostre o YAML e peça aprovação antes de criar.

## Não faça

- Não edite o OpenAPI à mão para "consertar" divergência: a divergência é informação.
- Não atualize o contrato sem avisar que muda comportamento para os consumidores.
