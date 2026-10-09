# Rodar com Docker

**Em uma frase:** a API roda num container no PC Linux, usando a rede do próprio PC, e reconecta sozinha ao robô.

## Na prática

```bash
cp .env.example .env                    # preencha GO2_ROBOT_SERIAL_NUMBER (ou GO2_ROBOT_IP)
docker compose --profile api build      # monta a imagem (demora na primeira vez)
docker compose --profile api up -d      # sobe em segundo plano
docker compose --profile api logs -f    # acompanha a conexão com o robô
docker compose --profile api down       # para e remove o container
```

- **Configuração:** tudo vem do `.env`. Mudou o `.env`? Rode `up -d` de novo (não precisa de `build`).
- **Porta:** `UVICORN_PORT` no `.env` (padrão `8000`). De outra máquina: `http://<IP do PC>:8000/status`.
- **Rede do host** (`network_mode: host`): o container usa a rede do PC direto. Sem isso a descoberta do robô por serial (multicast) e o WebRTC não funcionam. Só vale em Linux.

## "No ar" não é "conectado"

| Pergunta | Como ver | Resposta boa |
|---|---|---|
| A API está no ar? | `docker ps` → coluna STATUS | `(healthy)` |
| O robô está conectado? | `curl :8000/status` | `"connected": true` |

Com o robô desligado o container continua `healthy`: a API está viva e respondendo `connected: false`. O campo `state` diz o que ela está fazendo: `connected`, `disconnected` ou `reconnecting` (caiu e está tentando de novo).

## Reconexão

- Na subida a API tenta conectar uma vez **antes** de começar a responder (pode levar uns 15 s com o robô desligado).
- Depois, a cada `GO2_RECONNECT_INTERVAL_S` (padrão 5 s), ela confere a conexão. Se caiu, tenta de novo, para sempre.
- **Com serial**, cada tentativa procura o robô na rede de novo: se o IP mudou, ela acha o novo. **Com IP fixo** no `.env`, uma troca de IP exige corrigir o `.env`.
- Enquanto não há conexão, os comandos respondem `503`. Nada é guardado nem reenviado: o robô volta parado.
- **A confirmar no robô:** quanto tempo a API leva para perceber que o robô sumiu (desligado ou fora do Wi-Fi).

## Pegadinha

- **Firewall do PC.** Com rede do host, quem bloqueia é o firewall do PC. Se a TV Box não alcança a API, libere a porta TCP da API; se a descoberta por serial não acha o robô, libere a UDP `10134`. No Fedora: `sudo firewall-cmd --add-port=8000/tcp --add-port=10134/udp` (vale até reiniciar; com `--permanent` fica).
- Enquanto o robô está fora do ar, cada tentativa de reconexão trava a API por 2–3 s. Um `curl` pode demorar esse tanto.
- O app oficial aberto no celular disputa a conexão com a API ([ficha](uma-conexao-por-vez.md)).

## Checklist de teste com o robô

Antes: [checklist de campo](checklist-de-campo.md) (app do celular fechado, área livre, quem dispara o `stop`).

1. **Conectar.** `docker compose --profile api up -d` e `logs -f`. Esperado: `Peer Connection State: 🟢 connected` e `Data Channel Verification: ✅ OK`.
2. **Health.** `docker ps` mostra `(healthy)`; `curl :8000/status` mostra `"connected": true`, `"state": "connected"` e `low_state_age_s` pequeno. `curl :8000/capabilities` lista os comandos.
3. **Comando inválido.** `curl -i -X POST :8000/commands/posture -H 'content-type: application/json' -d '{"cmd":"voar"}'` → `422`, robô não se mexe.
4. **Um comando seguro.** Com o robô deitado: `curl -X POST :8000/commands/posture -H 'content-type: application/json' -d '{"cmd":"stand_up"}'` → `202` e o robô levanta. Depois `{"cmd":"stand_down"}`.
5. **Reiniciar o container.** `docker compose --profile api restart` com o robô deitado. Esperado: `🔴 disconnected` no log, e em alguns segundos `connected: true` de novo, sem o robô se mexer.
6. **Derrubar o container.** `docker kill go2-api` (queda sem aviso). O Docker sobe de novo sozinho. Anote se a nova conexão entra de primeira ou se o robô recusa por um tempo (`RobotBusyError` no log).
7. **Derrubar o robô.** Com o robô deitado, desligue-o (ou tire-o do Wi-Fi). Anote em quanto tempo `/status` vira `connected: false` com `state: reconnecting`. Religue: deve voltar a `true` sozinho.
8. **Comando durante a queda.** Enquanto `connected: false`, um comando responde `503` e **não** é executado quando a conexão volta.

## Mais detalhes

`Dockerfile` e `docker-compose.yml` (comentados) · [Modos de rede](modos-de-rede.md) · [Rodar sem o robô](rodar-sem-robo.md)

## Termos desta ficha

- **Docker / container**: Docker é o programa que roda containers. Um container é um processo isolado, com tudo de que a API precisa já dentro.
- **Imagem**: O "molde" de um container: sistema, Python, bibliotecas e o código da API. É montada pelo `build`.
- **`Dockerfile`**: A receita de como montar a imagem.
- **Docker Compose / profile**: Compose descreve em um arquivo (`docker-compose.yml`) como subir o container. *Profile* é uma etiqueta: o serviço só sobe quando ela é pedida (`--profile api`).
- **`.env`**: Arquivo de configuração da API, com as variáveis `GO2_*` e `UVICORN_*` (modelo em `.env.example`).
- **uvicorn**: O servidor que recebe os pedidos HTTP e os entrega à API.
- **`network_mode: host`**: O container usa a rede do PC diretamente, sem a rede isolada que o Docker cria por padrão (*bridge*).
- **Multicast**: Mensagem enviada a todos os aparelhos da rede de uma vez. É como a lib acha o robô pelo serial.
- **WebRTC**: *Web Real-Time Communication*: protocolo de comunicação em tempo real. É o túnel que liga a API ao robô.
- **TCP / UDP**: Os dois jeitos básicos de mandar dados pela rede. TCP confirma a entrega (HTTP usa); UDP não confirma (descoberta e WebRTC usam).
- **Firewall**: Programa do sistema que bloqueia conexões de rede não autorizadas.
- **Healthcheck / `healthy`**: Teste que o Docker repete para saber se o container está respondendo. Aqui ele chama `GET /status`.
- **`curl`**: Programa de linha de comando para fazer pedidos HTTP.
- **202 / 422 / 503**: Códigos de resposta: aceito (não quer dizer executado), corpo inválido, sem conexão com o robô.
- **`RobotBusyError`**: Erro da lib quando o robô recusa uma conexão porque já está ocupado com outra.
- **Serial**: Número de série do robô (`B42D...`).
