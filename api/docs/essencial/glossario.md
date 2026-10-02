# Glossário

| Termo | Significado |
|---|---|
| **`api_id`** | Número que identifica um comando dentro de um tópico de request (ex.: `Move` = 1008). |
| **Callback** | Função que você entrega para alguém chamar depois, quando algo acontecer (ex.: "quando chegar estado do robô, chame esta função"). |
| **Damp** | Postura que desliga a força dos motores. De pé, o robô cai. |
| **Data channel** | Canal de mensagens dentro da conexão WebRTC. Por ele passam comandos, estado e LiDAR. |
| **DDS** | *Data Distribution Service*, o barramento de mensagens interno do Go2 (CycloneDDS, o mesmo tipo do ROS 2). |
| **DHCP** | Sistema em que o roteador distribui endereços IP aos aparelhos. O endereço pode mudar. |
| **EDU / Pro / Air** | Versões do Go2. O projeto usa um **Pro** (sem Jetson, sem DDS aberto). |
| **Envelope** | Formato das mensagens dos WebSockets da API: `{"topic", "ts", "data"}`. |
| **Event loop** | O "motor" do `asyncio`: uma única fila que executa as tarefas da API uma de cada vez. Se uma tarefa demora, todas as outras esperam. |
| **Hub (TopicHub)** | Distribuidor interno (planejado, #9) que leva os dados do robô a vários clientes WebSocket. |
| **ICE** | Mecanismo do WebRTC que descobre um caminho de rede entre os dois lados. |
| **Lease** | "Posse" temporária do controle do robô, com token e expiração (planejado, #7). |
| **`lf`** | *Low frequency*. Ex.: `rt/lf/lowstate` é a versão de baixa frequência do estado. |
| **LiDAR** | Sensor de distância a laser. Ver [ficha](o-que-e-lidar.md). |
| **LocalAP / LocalSTA / Remote** | Modos de rede. Ver [ficha](modos-de-rede.md). |
| **MCF** | *Multi-Control Framework*, modo de locomoção com ids próprios. Ver [ficha](ids-normal-vs-mcf.md). |
| **Multicast** | Mensagem enviada para todos os aparelhos da rede ao mesmo tempo. A lib usa para achar o robô pelo serial. |
| **Nuvem de pontos** | Conjunto de pontos `(x, y, z)` medidos pelo LiDAR. |
| **Payload** | O conteúdo útil de uma mensagem (os dados), sem o cabeçalho. |
| **SDP** | Texto que descreve a conexão WebRTC, trocado no início ("oferta" e "resposta"). |
| **SN** | Número de série do robô (`B42D...`). Usado para achar o robô na rede e buscar a chave AES. |
| **`SPORT_CMD`** | Dicionário da lib com os comandos de alto nível e seus `api_id`s. |
| **Timeout** | Limite de tempo de espera. Passou do limite, desiste com erro. |
| **Track** | Fluxo de mídia (vídeo ou áudio) dentro da conexão WebRTC, separado do data channel. |
| **Tópico** | Nome de um canal de mensagens (ex.: `rt/api/sport/request`). |
| **Voxel** | "Pixel 3D": um cubinho do espaço marcado como ocupado ou livre. |
| **VUI** | Interface de voz e luz do robô: volume, brilho e LED. |
| **WebRTC** | Protocolo de comunicação em tempo real. É o túnel até o DDS do robô. |
| **`webrtc_bridge`** | Serviço dentro do robô que traduz WebRTC ↔ DDS. |
