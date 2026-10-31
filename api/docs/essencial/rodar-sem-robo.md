# Rodar e testar sem o robô

**Em uma frase:** a API sobe sem tentar conectar, e os testes nunca abrem WebRTC.

## Instalar

```bash
sudo dnf install portaudio-devel      # Fedora (Debian/Ubuntu: portaudio19-dev)
uv sync
```

O `uv sync` compila o `pyaudio` (dependência da lib) e falha sem os headers do PortAudio.

## Subir a API sem robô

```bash
GO2_CONNECTION_METHOD=LocalAP GO2_CONNECT_ON_STARTUP=false uv run uvicorn app.main:app --reload
```

- `GET /status` → 200 com `connected: false`. Comandos → **503**. Corpo inválido → **422**.
- Use `LocalAP` aqui: com `LocalSTA`, a configuração exige IP ou serial mesmo sem conectar.
- Documentação interativa em `http://127.0.0.1:8000/docs`.

## Testes

```bash
uv run pytest
```

Os testes usam `FakeConnection`/`FakePubSub` (`tests/conftest.py`), que registram o que **teria** sido enviado ao robô.

## Em breve

O `FakeHub` (#10) vai gerar dados falsos para os WebSockets, e o `scripts/ws_client.py` (#11) vai permitir olhá-los.

## Pegadinha

Teste passando ≠ funciona no robô. Os payloads marcados «pendente de validação física» no código só se confirmam com o robô ligado.

## Termos desta ficha

- **`uv`**: Gerenciador de pacotes e ambientes Python usado no projeto (`uv sync`, `uv run`).
- **PortAudio / headers**: Biblioteca de áudio do sistema. Os *headers* são os arquivos que o compilador precisa para compilar o `pyaudio`.
- **pytest**: Ferramenta que roda os testes automatizados.
- **Fake**: Objeto de teste que imita o real (ex.: `FakeConnection` finge ser o robô).
- **WebSocket**: Conexão que fica aberta entre cliente e servidor, por onde o servidor pode mandar dados continuamente (streams).
