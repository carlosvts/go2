# AGENTS.md — server (go2-server)

Servidor de inferência e despacho de voz (FastAPI): áudio → transcrição → interpretação → fila → api. Regras gerais: `AGENTS.md` da raiz. Comportamento e contrato: `specs/`.

## Comandos

```bash
cp .env.example .env
uv sync
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 9000
uv run pytest                    # rápidos (api e transcrição falsas)
uv run pytest -m model           # frases reais com embeddings (pula se o modelo não estiver em cache; não baixa)
uv run python scripts/send_wav.py --say "hey jarvis senta" --reason wake_word
```

Requer a api no ar (`127.0.0.1:8000` por padrão). Sem robô: api em `LocalAP` com `GO2_CONNECT_ON_STARTUP=false`.

## Regras

- **`catalog.yaml` é gerado** por `scripts/build_catalog.py` a partir de `discovery/`. Não edite à mão.
- **A interpretação nunca gera comando fora do catálogo.**
- Mudou a interpretação? Rode `eval/phrases.yaml`. Meta: **0 falsos positivos**, principalmente em movimento e `damp`. Subir revocação = mais exemplos em `discovery/inferred.yaml`, não baixar limiar.
- `max_duration_s` marcado como inferido continua inferido até haver medida da equipe.
- Mudou `/v1/utterance`, `/v1/cancel` ou `/health`? Atualize `specs/contracts/` no mesmo commit.
- O tvbox espera resposta em até `FALLBACK_TIMEOUT_S` (5 s).
- Ordem do pipeline, fila e demais comportamentos vivem em `specs/features/`, não aqui (a ordem pode mudar com experimentos de interpretação).

## Dados

`GO2S_SAVE_UTTERANCES=1` grava WAV e JSON de falas reais em `captures/`. Não versionar `captures/`, `.env` nem modelos.
