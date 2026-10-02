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
