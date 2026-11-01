# contracts/

Contratos HTTP entre os serviços. Cada arquivo será **commitado** e **conferido contra o código no CI** (workflow `contracts-check`, ainda a criar): quando existir, se o código divergir, o build quebra.

| Arquivo | Dono | Consumidores |
|---|---|---|
| `api.openapi.json` | api | server (`build_catalog.py`, despacho); tvbox (só `POST /commands/stop`, em `sense.stop`) |
| `server.openapi.json` | server | tvbox (`/v1/utterance`, `/v1/cancel`) |
| `catalog.schema.json` (planejado) | server | server (validará o `catalog.yaml` gerado) |

O tvbox não expõe HTTP, então não tem contrato próprio: só consome os dois acima.

## Como atualizar

1. Mudou uma rota, campo ou status? Edite o código **e** regenere o arquivo aqui, no mesmo commit.
2. Use a skill `check-contracts` (exporta o OpenAPI do código e compara com o commitado).
3. Contrato quebrado para um consumidor? Atualize o consumidor no mesmo PR ou abra spec de feature.

## O que o OpenAPI não cobre

O `catalog.yaml` e o `/capabilities` carregam semântica fora do schema HTTP: `max_duration_s`, `enabled`, e a distinção entre valor medido e inferido. O formato do catálogo vai precisar de schema próprio (`catalog.schema.json`), validado dentro de `server/scripts/build_catalog.py`. Ainda não existe: o schema e a validação dependem de aprovação.

## Primeira vez

Os arquivos ainda não existem. Gere-os a partir do código atual (skill `check-contracts`, modo "inicializar") e commite como linha de base. A linha de base descreve o que **o código faz hoje**, não o que foi validado em hardware.
