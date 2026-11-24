# Áudio no robô: biblioteca vs. alto-falante

**Em uma frase:** dá para tocar um som **na hora** (`/speaker/*`) ou **guardar** áudios no robô e tocá-los depois (`/audio/*`). São caminhos diferentes, com limites diferentes.

## Na prática

| | Alto-falante (`/speaker/*`, F-007) | Biblioteca do robô (`/audio/*`, F-006) |
|---|---|---|
| Para quê | Avisos e testes, na hora | Áudios que ficam no robô |
| Como chega ao robô | Track de áudio WebRTC (ao vivo) | Data channel, em blocos de 4 KB |
| Guarda no robô? | Não | Sim |
| Tempo até tocar | Depois de decodificar o arquivo | Minutos de envio para alguns MB; depois, `play` |
| Limites | `GO2_AUDIO_MAX_UPLOAD_MB` (5) e `GO2_SPEAKER_MAX_DURATION_S` (120 s) | `GO2_AUDIO_MAX_UPLOAD_MB` no arquivo **e** no WAV convertido |
| Formatos | WAV e MP3 (sem `ffmpeg`) | WAV e MP3 (MP3 vira WAV 44,1 kHz) |
| Parar | `POST /speaker/stop` | `POST /audio/pause` |

**Calar tudo:** `POST /audio/silence` para o alto-falante e pausa a biblioteca. O `POST /commands/stop` é só do movimento: não mexe no som.

O volume é o do robô (`PUT /device/volume`, 0–10). Que ele valha para os dois caminhos ainda é **a confirmar** no robô.

## Pegadinha

- `202` quer dizer que o robô **aceitou** (ou que a api começou a enviar), não que alguém ouviu.
- O envio para a biblioteca ocupa o mesmo canal do `move` e do `stop` por minutos. É um envio por vez (`409` no segundo).
- Som alto e inesperado assusta, sobretudo criança. Comece com volume baixo.

## Mais detalhes

[`arquitetura_go2_api.md`](../arquitetura_go2_api.md) §4.3 · `specs/features/F-006-audio-biblioteca.md` · `specs/features/F-007-alto-falante.md`

## Termos desta ficha

- **Track**: Fluxo de mídia (áudio ou vídeo) dentro da conexão WebRTC.
- **Data channel**: Canal de mensagens dentro da conexão WebRTC (comandos, estado, LiDAR, envio de arquivos).
- **WAV / MP3**: Arquivo de áudio cru / comprimido.
- **`ffmpeg`**: Programa de conversão de áudio e vídeo. A api não precisa dele: usa o PyAV.
