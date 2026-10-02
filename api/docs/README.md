# Documentação da `go2-api`

| Documento | Para quê | Quando ler |
|---|---|---|
| [`essencial/`](essencial/README.md) | **Fichas curtas e didáticas** (uma ideia por arquivo): redes, conexão, comandos, segurança física, LiDAR, glossário. | **Comece por aqui.** |
| [`go2_modelo_mental.md`](go2_modelo_mental.md) | Visão geral: DDS vs. WebRTC, redes do robô, o papel da lib e da API. Texto de entendimento, não de consulta. | Primeiro contato com o projeto. |
| [`arquitetura_go2_api.md`](arquitetura_go2_api.md) | Onde a API entra, endpoints **implementados e planejados** (com status e issue), desenho dos WebSockets e ordem de implementação. | Antes de abrir ou pegar uma issue. |
| [`lib_unitree_webrtc_connect.md`](lib_unitree_webrtc_connect.md) | Como a `unitree_webrtc_connect` 2.2.0 se comporta de verdade: pub/sub, threads, timeouts, vídeo, lidar, áudio, constantes. | Antes de mexer em `app/robot.py`. |
| [`dossie_go2.md`](dossie_go2.md) | Referência técnica do Go2: modelos e specs, sensores, protocolo, segurança, ecossistema, mapa de tópicos (§12) e decisão de concorrência (§13). | Para consultar tópico, `api_id`, spec ou fonte. |

Convenções:
- **"A confirmar"** marca o que não foi validado no robô ou no fonte. Não trate como fato.
- Referências a linhas da lib valem para a versão travada no `uv.lock` (hoje 2.2.0).
- Status e escopo de cada item vivem nas issues do GitHub; a arquitetura (§4) só aponta para elas.
