# DDS vs. WebRTC

**Em uma frase:** por dentro, tudo no Go2 é **DDS**: os serviços do robô conversam publicando e lendo mensagens em canais com nome (os **tópicos**). O **WebRTC** é um túnel de fora até esse barramento.

```
 go2-api ──WebRTC──▶ webrtc_bridge ──▶ barramento DDS ──▶ sport, lidar, câmera, vui...
 (SDK oficial/EDU) ─────────cabo──────▶ barramento DDS
```

## O que passa pelo túnel

| | WebRTC |
|---|---|
| Comandos de alto nível (andar, posturas, gestos) | ✅ |
| LiDAR, vídeo, áudio | ✅ |
| Estado em **baixa** frequência (`rt/lf/lowstate`) | ✅ |
| Estado em taxa cheia | ❌ |
| `rt/lowcmd` (torque/posição de cada junta) | ❌ |

## Na prática

Os nomes de tópico são os mesmos do SDK oficial (`rt/api/sport/request`...), porque são os mesmos serviços acessados por outra porta. Nada no escopo do projeto (voz, gestos, movimento, LiDAR, telemetria) precisa de `rt/lowcmd`.

## Pegadinha

"O app do celular controla o robô, então o SDK oficial funciona" é falso. O celular usa WebRTC. O SDK usa DDS direto, que no Pro não está aberto.

## Mais detalhes

[`go2_modelo_mental.md`](../go2_modelo_mental.md) §1–2 · [`dossie_go2.md`](../dossie_go2.md) §6–7

## Termos desta ficha

- **DDS**: *Data Distribution Service*: o sistema de mensagens interno do Go2, em que os serviços publicam e leem dados por tópico.
- **Tópico**: Nome de um canal de mensagens (ex.: `rt/api/sport/request`).
- **WebRTC**: *Web Real-Time Communication*: protocolo de comunicação em tempo real. É o túnel que liga a API ao robô.
- **`webrtc_bridge`**: Serviço dentro do robô que traduz WebRTC para DDS.
- **SDK**: *Software Development Kit*: o kit oficial da Unitree para programar o robô (`unitree_sdk2`). Usa DDS direto, por cabo, no EDU.
- **EDU**: Versão de pesquisa do Go2, com computador extra (Jetson) e DDS aberto. O robô do projeto é um **Pro**, não EDU.
- **LiDAR**: *Light Detection and Ranging*: sensor que mede distâncias com laser.
- **`lf`**: *Low frequency* (baixa frequência): versão do tópico que manda menos mensagens por segundo.
- **`rt/lowcmd`**: Tópico de controle de baixo nível: força/posição de cada junta (motor) individualmente.
- **Junta**: Articulação do robô movida por um motor (o Go2 tem 12, 3 por pata).
