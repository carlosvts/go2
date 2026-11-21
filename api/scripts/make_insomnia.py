# ruff: noqa: E501 - tabela de exemplos com descrições longas, lidas no Insomnia
"""Gera a coleção do Insomnia com todas as rotas da api.

Uso:
    uv run python scripts/make_insomnia.py              # grava insomnia/go2-api.json
    uv run python scripts/make_insomnia.py --check      # só confere se está em dia

A lista de rotas sai do próprio app (OpenAPI + rotas WebSocket); os exemplos
de corpo, a ordem e as pastas vêm de `EXAMPLES` e `FOLDERS` abaixo. Rota nova
sem exemplo entra mesmo assim, na pasta "Outras", e o `--check` (e o teste
`tests/unit/test_insomnia.py`) acusa a coleção desatualizada.

No Insomnia: Application → Preferences → Data → Import, ou arraste o arquivo.
Ajuste `base_url`/`ws_url` no ambiente "Base Environment" (IP da máquina da api).
"""

import argparse
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parent.parent / "insomnia" / "go2-api.json"
WORKSPACE = "wrk_go2api"
ENVIRONMENT = "env_go2api_base"

# Pasta, nome e ordem de cada rota. Chave: (método, caminho).
FOLDERS: list[tuple[str, str]] = [
    ("fld_01_estado", "1. Estado e sensores"),
    ("fld_02_postura", "2. Posturas"),
    ("fld_03_gestos", "3. Gestos"),
    ("fld_04_movimento", "4. Movimento, velocidade e desvio"),
    ("fld_05_device", "5. Lanterna, LED e volume"),
    ("fld_06_speaker", "6. Alto-falante (tocar na hora)"),
    ("fld_07_audio", "7. Biblioteca de áudio do robô"),
    ("fld_08_streams", "8. Streams (WebSocket)"),
    ("fld_99_outras", "Outras"),
]

JSON = "application/json"
MULTIPART = "multipart/form-data"

POSTURE_NOTES = {
    "balance_stand": "Necessário antes de qualquer move.",
    "damp": "⚠ DESLIGA OS MOTORES: o robô cai se estiver de pé.",
    "recovery_stand": "Levanta depois de uma queda.",
}


def _req(  # noqa: PLR0913 - um exemplo por chamada, tudo por nome
    folder: str,
    name: str,
    method: str,
    path: str,
    *,
    body: Any = None,  # noqa: ANN401
    multipart: list[dict[str, str]] | None = None,
    query: dict[str, str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    return {
        "folder": folder,
        "name": name,
        "method": method,
        "path": path,
        "body": body,
        "multipart": multipart,
        "query": query or {},
        "note": note,
    }


def examples(enums: dict[str, list[str]]) -> Iterator[dict[str, Any]]:
    """Os pedidos da coleção, na ordem em que aparecem no Insomnia."""
    estado = "fld_01_estado"
    yield _req(
        estado,
        "Status",
        "GET",
        "/status",
        note="Conexão, bateria, IMU, motores, configurações e erros (errors: null = desconhecido).",
    )
    yield _req(
        estado, "Status com payloads crus", "GET", "/status", query={"raw": "true"}
    )
    yield _req(
        estado,
        "Capabilities",
        "GET",
        "/capabilities",
        note="Comandos de movimento aceitos; não depende do robô.",
    )

    for cmd in enums["Posture"]:
        prefix = "⚠ " if cmd == "damp" else ""
        yield _req(
            "fld_02_postura",
            f"{prefix}Postura: {cmd}",
            "POST",
            "/commands/posture",
            body={"cmd": cmd},
            note=POSTURE_NOTES.get(cmd, ""),
        )
    for cmd in enums["Gesture"]:
        yield _req(
            "fld_03_gestos",
            f"Gesto: {cmd}",
            "POST",
            "/commands/gesture",
            body={"cmd": cmd},
            note="Robô de pé. Gesto enviado não é cancelável.",
        )

    mov = "fld_04_movimento"
    yield _req(
        mov,
        "STOP (parar)",
        "POST",
        "/commands/stop",
        note="Para o move e deixa o robô de pé. Deixe esta aba à mão.",
    )
    yield _req(
        mov,
        "Move: frente devagar 2 s",
        "POST",
        "/commands/move",
        body={"vx": 0.3, "vy": 0, "vyaw": 0, "duration_s": 2},
        note="Antes: postura balance_stand. Área livre.",
    )
    yield _req(
        mov,
        "Move: girar 2 s",
        "POST",
        "/commands/move",
        body={"vx": 0, "vy": 0, "vyaw": 0.5, "duration_s": 2},
        note="Antes: postura balance_stand.",
    )
    yield _req(mov, "Velocidade: ler", "GET", "/commands/speed")
    yield _req(mov, "Velocidade: definir", "PUT", "/commands/speed", body={"level": 1})
    yield _req(mov, "Desvio de obstáculo: ler", "GET", "/safety/obstacle-avoidance")
    yield _req(
        mov,
        "Desvio de obstáculo: ligar",
        "PUT",
        "/safety/obstacle-avoidance",
        body={"enabled": True},
    )
    yield _req(
        mov,
        "Desvio de obstáculo: desligar",
        "PUT",
        "/safety/obstacle-avoidance",
        body={"enabled": False},
    )

    dev = "fld_05_device"
    yield _req(dev, "Brilho: ler", "GET", "/device/brightness")
    yield _req(
        dev,
        "Brilho: definir (1)",
        "PUT",
        "/device/brightness",
        body={"level": 1},
        note="0 a 10 (GO2_MAX_BRIGHTNESS). Comece baixo.",
    )
    yield _req(
        dev, "Brilho: apagar (0)", "PUT", "/device/brightness", body={"level": 0}
    )
    yield _req(dev, "Volume: ler", "GET", "/device/volume")
    yield _req(
        dev,
        "Volume: definir (2)",
        "PUT",
        "/device/volume",
        body={"level": 2},
        note="0 a 10 (GO2_MAX_VOLUME). Comece baixo.",
    )
    for color in enums["LedColor"]:
        yield _req(
            dev,
            f"LED: {color} 5 s",
            "PUT",
            "/device/led",
            body={"color": color, "duration_s": 5},
        )
    yield _req(
        dev,
        "LED: vermelho piscando",
        "PUT",
        "/device/led",
        body={"color": "red", "duration_s": 5, "flash_cycle_ms": 1000},
        note="flash_cycle_ms de 499 a duration_s × 1000.",
    )

    spk = "fld_06_speaker"
    yield _req(
        spk,
        "Tocar arquivo (escolha o WAV/MP3)",
        "POST",
        "/speaker/play",
        multipart=[{"name": "file", "type": "file"}],
        note="Até GO2_AUDIO_MAX_UPLOAD_MB e GO2_SPEAKER_MAX_DURATION_S (120 s). Clique no campo file e escolha o arquivo.",
    )
    yield _req(spk, "Parar o alto-falante", "POST", "/speaker/stop")
    yield _req(spk, "O que está tocando", "GET", "/speaker")

    aud = "fld_07_audio"
    yield _req(
        aud,
        "Listar áudios do robô",
        "GET",
        "/audio/files",
        note="Copie um id para a variável file_id do ambiente.",
    )
    yield _req(
        aud,
        "Enviar áudio ao robô (escolha o arquivo)",
        "POST",
        "/audio/files",
        multipart=[
            {"name": "file", "type": "file"},
            {"name": "name", "value": "teste-insomnia"},
        ],
        note="Responde 202 com upload_id; copie para a variável upload_id. O envio leva minutos para alguns MB.",
    )
    yield _req(aud, "Andamento do envio", "GET", "/audio/uploads/{{ _.upload_id }}")
    yield _req(aud, "Tocar áudio do robô", "POST", "/audio/files/{{ _.file_id }}/play")
    yield _req(aud, "Pausar", "POST", "/audio/pause")
    yield _req(aud, "Retomar", "POST", "/audio/resume")
    yield _req(aud, "Modo de reprodução: ler", "GET", "/audio/play-mode")
    for mode in enums["PlayMode"]:
        yield _req(
            aud,
            f"Modo de reprodução: {mode}",
            "PUT",
            "/audio/play-mode",
            body={"mode": mode},
        )
    yield _req(
        aud,
        "Renomear áudio",
        "PATCH",
        "/audio/files/{{ _.file_id }}",
        body={"name": "renomeado"},
    )
    yield _req(aud, "Apagar áudio", "DELETE", "/audio/files/{{ _.file_id }}")
    yield _req(aud, "Estado do player do robô", "GET", "/audio/player")
    yield _req(
        aud,
        "SILENCIAR TUDO",
        "POST",
        "/audio/silence",
        note="Pausa o player do robô e para o alto-falante.",
    )


WEBSOCKETS = {
    "/ws/state": "Estado e sensores em tempo real (JSON). Contrato: specs/contracts/ws-state.md.",
    "/ws/lidar": "Nuvem de pontos (binário float32). Prefira scripts/lidar_viewer.html.",
    "/ws/telemetry": "Métricas, pose e estado do LiDAR (JSON).",
    "/ws/video": "Câmera, JPEG por frame binário. Prefira scripts/video_viewer.html. Avise as pessoas antes.",
}


def _openapi_route_keys(openapi: dict[str, Any]) -> set[tuple[str, str]]:
    keys = set()
    for path, methods in openapi["paths"].items():
        for method in methods:
            keys.add((method.upper(), path))
    return keys


def _normalize(path: str) -> str:
    """`/audio/files/{{ _.file_id }}` → `/audio/files/{file_id}` (como no OpenAPI)."""
    return path.replace("{{ _.file_id }}", "{file_id}").replace(
        "{{ _.upload_id }}", "{upload_id}"
    )


def build(openapi: dict[str, Any], websockets: list[str]) -> dict[str, Any]:
    """Monta o export (formato 4) do Insomnia."""
    schemas = openapi["components"]["schemas"]
    enums = {k: v["enum"] for k, v in schemas.items() if "enum" in v}
    items = list(examples(enums))
    covered = {(i["method"], _normalize(i["path"])) for i in items}
    for method, path in sorted(_openapi_route_keys(openapi) - covered):
        items.append(_req("fld_99_outras", f"{method} {path}", method, path))
    resources: list[dict[str, Any]] = [
        {
            "_id": WORKSPACE,
            "_type": "workspace",
            "name": "go2-api",
            "description": "Todas as rotas da go2-api (Unitree Go2). Gerado por api/scripts/make_insomnia.py.",
            "scope": "collection",
        },
        {
            "_id": ENVIRONMENT,
            "_type": "environment",
            "parentId": WORKSPACE,
            "name": "Base Environment",
            "data": {
                "base_url": "http://localhost:8000",
                "ws_url": "ws://localhost:8000",
                "file_id": "COLE_AQUI_O_ID",
                "upload_id": "COLE_AQUI_O_UPLOAD_ID",
            },
        },
    ]
    used = {i["folder"] for i in items} | ({"fld_08_streams"} if websockets else set())
    for order, (folder_id, name) in enumerate(FOLDERS):
        if folder_id in used:
            resources.append(
                {
                    "_id": folder_id,
                    "_type": "request_group",
                    "parentId": WORKSPACE,
                    "name": name,
                    "metaSortKey": order,
                }
            )
    for order, item in enumerate(items):
        resources.append(_request_resource(order, item))
    for order, path in enumerate(websockets):
        resources.append(
            {
                "_id": f"ws_{order:03d}",
                "_type": "websocket_request",
                "parentId": "fld_08_streams",
                "name": path,
                "url": "{{ _.ws_url }}" + path,
                "description": WEBSOCKETS.get(path, ""),
                "metaSortKey": order,
                "headers": [],
                "parameters": [],
                "settingEncodeUrl": True,
                "settingFollowRedirects": "global",
            }
        )
    return {
        "_type": "export",
        "__export_format": 4,
        "__export_source": "go2-api:make_insomnia.py",
        "resources": resources,
    }


def _request_resource(order: int, item: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    headers: list[dict[str, str]] = []
    if item["body"] is not None:
        body = {"mimeType": JSON, "text": json.dumps(item["body"], indent=2)}
        headers.append({"name": "Content-Type", "value": JSON})
    elif item["multipart"] is not None:
        params = []
        for field in item["multipart"]:
            if field.get("type") == "file":
                params.append({"name": field["name"], "type": "file", "fileName": ""})
            else:
                params.append({"name": field["name"], "value": field.get("value", "")})
        body = {"mimeType": MULTIPART, "params": params}
        headers.append({"name": "Content-Type", "value": MULTIPART})
    return {
        "_id": f"req_{order:03d}",
        "_type": "request",
        "parentId": item["folder"],
        "name": item["name"],
        "method": item["method"],
        "url": "{{ _.base_url }}" + item["path"],
        "description": item["note"],
        "body": body,
        "headers": headers,
        "parameters": [{"name": k, "value": v} for k, v in item["query"].items()],
        "metaSortKey": order,
        "settingEncodeUrl": True,
    }


def app_routes() -> tuple[dict[str, Any], list[str]]:
    """OpenAPI e rotas WebSocket do app, sem conectar ao robô."""
    os.environ.setdefault("GO2_CONNECTION_METHOD", "LocalAP")
    os.environ.setdefault("GO2_CONNECT_ON_STARTUP", "false")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from fastapi.routing import APIWebSocketRoute  # noqa: PLC0415

    from app.main import create_app  # noqa: PLC0415

    app = create_app()

    def walk(routes: list[Any]) -> Iterator[str]:
        # FastAPI recente embrulha cada `include_router` (`original_router`).
        for route in routes:
            if isinstance(route, APIWebSocketRoute):
                yield route.path
            inner = getattr(route, "original_router", None)
            if inner is not None:
                yield from walk(inner.routes)

    websockets = sorted(
        set(walk(app.routes)),
        key=lambda p: list(WEBSOCKETS).index(p) if p in WEBSOCKETS else 99,
    )
    return app.openapi(), websockets


def render() -> str:
    """O JSON da coleção, como fica no arquivo."""
    openapi, websockets = app_routes()
    return json.dumps(build(openapi, websockets), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    """Grava a coleção ou confere se está em dia."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != content:
            print(
                f"❌ {OUT} desatualizado: rode scripts/make_insomnia.py",
                file=sys.stderr,
            )
            sys.exit(1)
        print("✅ coleção do Insomnia em dia")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content, encoding="utf-8")
    print(f"{OUT}")


if __name__ == "__main__":
    main()
