# contracts/

Contratos HTTP entre os serviços. Cada arquivo é **commitado** e **conferido contra o código no CI** (workflow `.github/workflows/contracts-check.yml`): o CI exporta o OpenAPI do código e falha se `git diff --exit-code` acusar diferença. Ele roda em pull request e push na `main` que toquem `api/`, `server/` ou `specs/contracts/`.

| Arquivo | Dono | Consumidores |
|---|---|---|
| `api.openapi.json` | api | server (`build_catalog.py`, despacho); tvbox (só `POST /commands/stop`, em `sense.stop`) |
| `server.openapi.json` | server | tvbox (`/v1/utterance`, `/v1/cancel`; `GET /v1/reply/{utterance_id}` e o campo `reply_pending` na E-002) |
| `catalog.schema.json` (planejado) | server | server (validará o `catalog.yaml` gerado) |
| `ws-lidar.md` | api | `api/scripts/ws_lidar_client.py` e `api/scripts/record_lidar.py` (visualização, gravação); o server ainda não |
| `ws-telemetry.md` | api | `api/scripts/record_lidar.py` e o visualizador; o server ainda não |

`ws-lidar.md` e `ws-telemetry.md` descrevem frames de WebSocket, que o OpenAPI não cobre: **o CI não os confere**. A conferência é a revisão humana e os testes de `api/tests/unit/test_lidar_frame.py`, `api/tests/unit/test_lidar_telemetry.py`, `api/tests/api/test_ws_lidar.py` e `api/tests/api/test_ws_telemetry.py` (F-001, F-002).

O tvbox não expõe HTTP, então não tem contrato próprio: só consome os dois acima.

## Como atualizar

1. Mudou uma rota, campo ou status? Edite o código **e** regenere o arquivo aqui, no mesmo commit.
2. Use a skill `check-contracts` (exporta o OpenAPI do código e compara com o commitado).
3. Contrato quebrado para um consumidor? Atualize o consumidor no mesmo PR ou abra spec de feature.

## O que o OpenAPI não cobre

O `catalog.yaml` e o `/capabilities` carregam semântica fora do schema HTTP: `max_duration_s`, `enabled`, e a distinção entre valor medido e inferido. O formato do catálogo vai precisar de schema próprio (`catalog.schema.json`), validado dentro de `server/scripts/build_catalog.py`. Ainda não existe: o schema e a validação dependem de aprovação.

## Linha de base

`api.openapi.json` e `server.openapi.json` foram gerados do código (skill `check-contracts`, modo "inicializar"). Descrevem o que **o código faz hoje**, não o que foi validado em hardware. `catalog.schema.json` ainda não existe.
