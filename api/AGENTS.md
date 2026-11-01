# AGENTS.md — api (go2-api)

FastAPI (Python, uv) que mantém a **única conexão WebRTC** com o Go2. Outros serviços mandam comandos por HTTP. Regras gerais: `AGENTS.md` da raiz. Comportamento e contrato: `specs/`.

## Comandos

```bash
cp .env.example .env     # GO2_ROBOT_SERIAL_NUMBER (preferido) ou GO2_ROBOT_IP
uv sync
uv run uvicorn app.main:create_app --factory --reload     # docs em /docs
uv run pytest --cov      # sem robô
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Sem robô: `GO2_CONNECTION_METHOD=LocalAP` + `GO2_CONNECT_ON_STARTUP=false`. `LocalSTA` exige IP ou serial mesmo sem conectar.

## Regras

- `app/robot/unitree.py` é a **única fronteira** com a lib unitree. Nada fora dele importa a lib.
- Comando novo da lib só entra com spec e com teste da equipe no robô (49 na lib, 21 expostos). Truques (flips, handstand) exigiriam `"confirm": true`.
- `/capabilities` é consumido pelo `server/` (`build_catalog.py`). Mudou o formato? Atualize `specs/contracts/` no mesmo commit.
- `FreeWalk` e `LeadFollow` têm o mesmo número (1045) na lib. Cuidado com mapeamentos por número.
- Comportamento (códigos de resposta, limites do `move`, reconexão, o que cancela o quê) está em `specs/` e nos docs de `docs/`. Não replique aqui.

## Testes

Testes não exigem robô e não provam comportamento físico (payloads de `Move`/`SpeedLevel`, formato de bateria/modo, duração de gesto).
