# AGENTS.md — tvbox (go2-tvbox, "Sense")

Cliente de voz na TV Box (Amlogic S9xx, Debian 11 aarch64, 1,8 GiB de RAM, disco ~90%): wake word, grava o comando e envia ao server. Regras gerais: `AGENTS.md` da raiz. Comportamento e contrato: `specs/`.

## Comandos

```bash
uv sync --no-dev --extra capture --extra recognition   # capture = pyaudio; recognition = openwakeword (sem ele não roda)
cp .env.example .env             # SERVER_URL (:9000); GO2_API_URL (:8000) só para a parada manual
uv run python -m sense           # cliente
uv run python -m sense.stop      # parada manual (direto na api)
uv run pytest
```

Antes de instalar ou rodar na TV Box: `df -h` e `free -h`. Não clone o monorepo inteiro lá; use sparse checkout (`tvbox` e `specs/contracts`, ver `tvbox/README.md`).

## Regras

- Python fixado em 3.10 e `tflite-runtime==2.13.0` (glibc 2.31 da TV Box). Não mexa sem testar na TV Box.
- Só o modo **thin** existe. Referência a edge nos docs ou no código: avise, não reviva.
- A TV Box não tem fila e não executa o que o server responde.
- **A parada falada passa pelo server** e depende de rede e Whisper. A garantia independente é `python -m sense.stop`. Nunca escreva ou sugira que a parada por voz é garantida.
- Não adicionar dependência pesada sem medir RAM e CPU antes e depois.
- `chunks_dropped_late` subindo no diagnóstico = a wake word não acompanha o áudio. Investigar antes de adicionar processamento.
- `PRE_ROLL_S` pode vazar o fim da wake word ("-vis") e quebrar a interpretação. É ajuste de config.
- Não versionar `.env`, modelos nem áudios gravados.
- O tvbox só consome contratos (server e, no `sense.stop`, a api). Mudou o que ele envia? Atualize `specs/contracts/` no mesmo commit.

Validação com microfone real (wake word à distância, falsos disparos): `docs/checklist-laboratorio.md` e specs `hardware-only`.
