# Roteiro hardware-only rápido — rodada "api completa" (F-004 a F-007)

Uma sessão, organizada pela **postura do robô**, não por spec: tudo o que dá para testar com o robô deitado vem primeiro (estado, luz, som), e o bloco curto com o robô andando fica no fim.

Specs: [F-004](../features/F-004-estado-e-sensores.md) estado e sensores · [F-005](../features/F-005-lanterna-led-volume.md) lanterna, LED e volume · [F-006](../features/F-006-audio-biblioteca.md) biblioteca de áudio · [F-007](../features/F-007-alto-falante.md) alto-falante.
A [F-003](F-003.md) (vídeo) tem roteiro próprio. O bloco B dela e o bloco B daqui podem usar **a mesma linha de base**.

Duração estimada: bloco A ~40 min; bloco B ~30 min. Os tempos são estimativa, sem medida.

Este roteiro **não** declara nada verificado. Traga as tabelas preenchidas; eu registro nas specs sem arredondar e marco `testado-hardware` só no que você disser que passou.

## Antes de tudo (5 min)

- [ ] Branch: `git fetch && git checkout feat/api-completa && git pull && cd api && uv sync`. Commit (`git rev-parse --short HEAD`): ________
- [ ] Testes: `uv run pytest -q`. Resultado: ________
- [ ] Arquivos de teste: `uv run python scripts/make_test_audio.py ../audio-teste`. Gera `tom-3s.wav`, `tom-3s.mp3`, `tom-30s.mp3` e `tom-1mb.wav`.
- [ ] `api/.env` com o robô configurado, LiDAR e vídeo desligados:
      ```
      GO2_LIDAR_MAX_CLIENTS=0
      GO2_TELEMETRY_MAX_CLIENTS=0
      GO2_VIDEO_MAX_CLIENTS=0
      ```
- [ ] Subir a api com log em arquivo:
      ```
      uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 \
        --log-config logging-debug.json 2>&1 | tee ../api-rodada.log
      ```
- [ ] App oficial da Unitree aberto no celular, para comparar bateria, volume, brilho e erros.
- [ ] Parada de emergência num terminal à parte: `curl -X POST localhost:8000/commands/stop`. Controle remoto à mão.
- [ ] Ninguém de frente para a lanterna. Avise as pessoas por perto que o robô vai fazer sons.

Atalho para os comandos abaixo: `A=localhost:8000`.

## Bloco A — robô deitado (`stand_down`)

`curl -X POST $A/commands/posture -H 'content-type: application/json' -d '{"cmd":"stand_down"}'`

### A1. Estado (F-004 A10, A11, A12) — 5 min
1. Logo depois de a api conectar, contar até 5 e rodar `curl -s $A/status | python -m json.tool > ../status.json`.
2. Conferir no `status.json` se `battery`, `imu`, `motion`, `motors` e `settings` estão não nulos. Comparar com o app: `battery.percent`, `settings.volume` e `settings.brightness`.
3. Anotar o que `errors` mostra (`null`, `[]` ou erros) e o que o app mostra.
4. Rodar `uv run python scripts/ws_state_client.py --seconds 60 | tee ../ws-state.txt`. Ele imprime, por segundo, quantos frames de cada tópico chegaram. No log da api, copiar 3 linhas `state_metrics`.

| Item | Valor |
|---|---|
| Seções não nulas em 5 s (quais faltaram?) | |
| `battery.percent` api × app | |
| `settings.volume` api × app | |
| `settings.brightness` api × app | |
| `errors` na api × app | |
| Mensagens/s por tópico (`state_metrics`) | |
| Algum frame acima de `GO2_STATE_MAX_HZ`? | |

Sessão de 2026-11-23 (Insomnia, registrado pelo Claude do `api-teste-video-inicial.log`): `GET /status` → 200 às 11:04:53 e `GET /status?raw=true` → 200 às 11:05:06. O corpo das respostas e a comparação com o app não ficaram registrados; `ws_state_client.py` não rodou. A tabela acima continua em aberto (`TODO(humano)`).

Passa se: **A10** as cinco seções não nulas em 5 s e os três valores batem com o app (bateria ±1). **A11** nenhum tópico acima do limite. **A12** é só registro.

### A2. Lanterna e LED (F-005 A6, A7) — 10 min
Leitura primeiro, depois valores baixos.
1. `curl -s $A/device/brightness`. Anotar a resposta.
2. `curl -X PUT $A/device/brightness -H 'content-type: application/json' -d '{"level":1}'`. Anotar o status HTTP e a peça física que acendeu.
3. Repetir com `0`, `5` e `10`; depois o `GET` deve devolver `10`. Voltar a `0`.
4. LED: para cada cor (`white`, `red`, `yellow`, `blue`, `green`, `cyan`, `purple`), rodar `curl -X PUT $A/device/led -H 'content-type: application/json' -d '{"color":"<cor>","duration_s":5}'`. Cronometrar quanto tempo a cor fica.
5. `curl -X PUT $A/device/led -H 'content-type: application/json' -d '{"color":"red","duration_s":5,"flash_cycle_ms":1000}'`. Anotar se pisca e a cadência.

| Item | Valor |
|---|---|
| `GET` brilho (resposta) | |
| `PUT` brilho: status HTTP; peça física que muda | |
| Brilho 0 / 5 / 10 visível? `GET` depois | |
| Cor: aparece? duração cronometrada (s) | white __ red __ yellow __ blue __ green __ cyan __ purple __ |
| Pisca com `flash_cycle_ms=1000`? cadência | |
| O que o LED faz quando o tempo acaba | |
| É a mesma peça da lanterna? | |

Sessão de 2026-11-23 (Insomnia, registrado pelo Claude do `api-teste-video-inicial.log`): 15× `PUT /device/led` → 202, de 11:05:29 a 11:08:29, com a câmera desligada (0 quadros lidos nesse intervalo). O log não guarda o corpo da requisição (cor, `duration_s`, `flash_cycle_ms`) nem o efeito físico; o humano relatou que funcionou, sem detalhe por cor. Brilho (`/device/brightness`) não aparece no log. A tabela acima continua em aberto (`TODO(humano)`). 202 é aceite, não confirmação de que o LED acendeu.

Passa se: **A6** o brilho muda de apagado a máximo e o `GET` devolve o valor. **A7** as 7 cores aparecem, cada uma dura entre 4 e 6 s, e o pisca funciona.

### A3. Alto-falante, volume e biblioteca (F-005 A8; F-006 A9, A10, A12; F-007 A10, A11, A13) — 25 min
Volume baixo primeiro: `curl -X PUT $A/device/volume -H 'content-type: application/json' -d '{"level":2}'`. Anotar o `GET /device/volume`.

**Alto-falante (F-007)**
1. `curl -X POST $A/speaker/play -F file=@../audio-teste/tom-3s.wav`. Anotar se o robô tocou e o atraso estimado (cronômetro, do Enter ao som).
2. O mesmo com `tom-3s.mp3`.
3. `curl -X POST $A/speaker/play -F file=@../audio-teste/tom-30s.mp3` e, uns 5 s depois, `curl -X POST $A/speaker/stop`. O som corta?
4. Com o de 30 s tocando, mandar o `tom-3s.wav`. O som troca?
5. **Volume (F-005 A8, F-007 A11):** tocar o `tom-30s.mp3`, mudar para `8`, depois de volta a `2`. O volume muda durante a reprodução? E no próximo `play`?

**Biblioteca (F-006)**
6. `curl -s $A/audio/files | python -m json.tool`. Anotar quantos itens há e os campos de `extra`.
7. Enviar: `curl -X POST $A/audio/files -F file=@../audio-teste/tom-3s.wav -F name=teste-wav`. Acompanhar com `curl -s $A/audio/uploads/<upload_id>` até `done`. Cronometrar.
8. O mesmo com `tom-3s.mp3` e `name=teste-mp3`.
9. Listar de novo: os dois aparecem? Tocar `teste-wav` com `curl -X POST $A/audio/files/<id>/play`; com ele tocando, `POST $A/audio/pause`, depois `POST $A/audio/resume`.
10. `curl -s $A/audio/player` parado, tocando e pausado: anotar o que vem.
11. Modos: `curl -X PUT $A/audio/play-mode -H 'content-type: application/json' -d '{"mode":"list_loop"}'`, `GET`, tocar e observar. Repetir com `single_cycle` e `no_cycle`.
12. Com algo tocando em `list_loop`: `curl -X POST $A/audio/silence`. O robô cala?
13. **Ao mesmo tempo (F-007 A13):** tocar `teste-wav` pela biblioteca e o `tom-30s.mp3` pelo `/speaker/play`. O que se ouve?
14. Renomear: `curl -X PATCH $A/audio/files/<id> -H 'content-type: application/json' -d '{"name":"renomeado"}'`; apagar: `curl -X DELETE $A/audio/files/<id>`. Listar e conferir.
15. **Envio cortado (F-006 A12):** começar o envio do `tom-1mb.wav` e, no meio, desligar o Wi-Fi da máquina da api por 10 s. Religar, esperar a api reconectar e listar. Ficou arquivo parcial? Anotar o `state`/`error` do upload.

| Item | Valor |
|---|---|
| `speaker` WAV toca? atraso (s) | |
| `speaker` MP3 toca? | |
| `stop` corta? `play` durante outro troca? | |
| Volume 2 → 8 muda o `speaker`? (durante / próximo `play`) | |
| Volume muda o áudio da biblioteca? | |
| Lista inicial (nº de itens, campos de `extra`) | |
| Envio WAV 3 s: tempo, `done`? | |
| Envio MP3 3 s: tempo, `done`? | |
| `play`/`pause`/`resume` funcionam? | |
| `/audio/player` parado / tocando / pausado | |
| O que cada modo faz | `list_loop`: __ `single_cycle`: __ `no_cycle`: __ |
| `/audio/silence` cala? | |
| Biblioteca + `speaker` ao mesmo tempo: o que se ouve | |
| Renomear / apagar funcionam? | |
| Envio cortado: arquivo parcial? `state`/`error` | |

Passa se:
- **F-005 A8:** o volume muda o som e o `GET` devolve o valor.
- **F-006 A9:** os dois envios aparecem, tocam, pausam e retomam; renomear e apagar funcionam; `silence` cala.
- **F-006 A10:** o `GET` do modo devolve o que foi definido.
- **F-007 A10:** WAV e MP3 tocam, `stop` corta e o `play` troca.
- São só registro: F-006 A12, F-007 A11 e A13.

Ao terminar: volume de volta ao valor do começo e brilho a `0`.

## Bloco B — robô andando: `stop` sob carga de áudio (F-006 A11, F-007 A12) — 30 min

Pré-requisitos: área livre (~2 m à frente, ~1 m dos lados), ninguém dentro dela. Parada de emergência digitada, controle à mão. Celular filmando de lado, com o robô **e** o terminal do `curl` no quadro; anote o fps: ____.

Robô em equilíbrio, nesta ordem:
1. `curl -X POST $A/commands/posture -H 'content-type: application/json' -d '{"cmd":"stand_up"}'`
2. `curl -X POST $A/commands/posture -H 'content-type: application/json' -d '{"cmd":"balance_stand"}'`

`stand_up` sozinho não basta para o `move`.

Cada repetição:
1. `curl -X POST $A/commands/move -H 'content-type: application/json' -d '{"vx":0.3,"vy":0,"vyaw":0,"duration_s":2}'`
2. ~1 s depois, `curl -X POST $A/commands/stop`.
3. Medir no vídeo o tempo entre a resposta do `stop` aparecer no terminal e as patas pararem.

Volte o robô ao ponto de partida entre as repetições.

1. **Linha de base:** reiniciar a api (log `api-base.log`) sem enviar nem tocar áudio desde o boot. 10 repetições. Se for fazer o bloco B da F-003 no mesmo dia, esta linha de base serve para os dois.
2. **Durante envio:** começar `curl -X POST $A/audio/files -F file=@../audio-teste/tom-1mb.wav -F name=carga` e, enquanto `GET /audio/uploads/<id>` mostrar `uploading`, fazer 10 repetições. Se o envio acabar antes, mandar outro com outro `name`.
3. **Durante reprodução:** tocar `tom-30s.mp3` pelo `/speaker/play` e fazer as repetições enquanto toca. Mandar de novo a cada 30 s, até completar 10.
4. Repetição com queda de conexão (`reconnecting` no log): descartar e anotar.
5. Apagar os arquivos `carga*` da biblioteca no fim.

| Rep. | Base (s) | Durante envio (s) | Durante reprodução (s) |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8 | | | |
| 9 | | | |
| 10 | | | |
| **mediana** | | | |

Passa se: para cada coluna com carga, mediana(carga) ≤ mediana(base) + 0,2 s e nenhuma repetição acima de mediana(base) + 0,4 s. **F-006 A11** é a coluna do envio; **F-007 A12**, a da reprodução.

## Depois da sessão

Traga para cá:
- as tabelas preenchidas, o `status.json`, o `api-rodada.log` e o `api-base.log`;
- os vídeos do bloco B;
- o commit testado.

Item que não fizer o esperado no robô (código ≠ 0, outro efeito): anote o que aconteceu. A rota sai da api antes do PR, e a spec registra o motivo (F-005, Segurança).
