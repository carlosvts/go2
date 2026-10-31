# Glossário

| Termo | Significado |
|---|---|
| **AES-128** | *Advanced Encryption Standard*, chave de 128 bits: tipo de criptografia. No firmware ≥ 1.1.15, cada robô tem uma chave própria. |
| **API** | *Application Programming Interface*: o "balcão de atendimento" de um programa. Aqui, a `go2-api`, que recebe pedidos HTTP e fala com o robô. |
| **`api_id`** | Número que identifica um comando dentro de um tópico de request (ex.: `Move` = 1008). |
| **Cache** | Cópia guardada em memória do último dado recebido, para responder rápido sem perguntar de novo ao robô. |
| **Callback** | Função que você entrega para alguém chamar depois, quando algo acontecer (ex.: "quando chegar estado do robô, chame esta função"). |
| **Damp** | Postura que desliga a força dos motores. De pé, o robô cai. |
| **Data channel** | Canal de mensagens dentro da conexão WebRTC. Por ele passam comandos, estado e LiDAR. |
| **DDS** | *Data Distribution Service*, o barramento de mensagens interno do Go2 (CycloneDDS, o mesmo tipo do ROS 2). |
| **Decoder** | O código que transforma o dado comprimido que chega do robô em algo utilizável. |
| **DHCP** | Sistema em que o roteador distribui endereços IP aos aparelhos. O endereço pode mudar. |
| **EDU / Pro / Air** | Versões do Go2. O projeto usa um **Pro** (sem Jetson, sem DDS aberto). |
| **Endpoint** | Um endereço da API que aceita pedidos (ex.: `POST /commands/move`). |
| **Envelope** | Formato das mensagens dos WebSockets da API: `{"topic", "ts", "data"}`. |
| **Event loop** | O "motor" do `asyncio`: uma única fila que executa as tarefas da API uma de cada vez. Se uma tarefa demora, todas as outras esperam. |
| **Firmware** | O software de fábrica que roda dentro do robô. A versão dele muda o que o robô aceita. |
| **Handshake** | "Aperto de mão": a troca inicial de mensagens que abre a conexão. |
| **HTTP** | Protocolo de pedido e resposta da web (é o que o navegador e o `curl` usam). |
| **Hub (TopicHub)** | Distribuidor interno (planejado, #9) que leva os dados do robô a vários clientes WebSocket. |
| **Hz** | Hertz: vezes por segundo. 30 Hz = 30 envios por segundo. |
| **ICE** | Mecanismo do WebRTC que descobre um caminho de rede entre os dois lados. |
| **IMU** | *Inertial Measurement Unit*: sensor de orientação e aceleração (inclinação, giro). |
| **IP** | Endereço de um aparelho na rede (ex.: `192.168.12.1`). |
| **Jetson** | Computador da NVIDIA para IA, que vem acoplado só no Go2 EDU. |
| **JSON** | *JavaScript Object Notation*: formato de texto para dados, como `{"chave": "valor"}`. |
| **Junta** | Articulação do robô movida por um motor (o Go2 tem 12, 3 por pata). |
| **LAN** | *Local Area Network*: a rede local (do laboratório), sem passar pela internet. |
| **Lease** | "Posse" temporária do controle do robô, com token e expiração (planejado, #7). |
| **`lf`** | *Low frequency*. Ex.: `rt/lf/lowstate` é a versão de baixa frequência do estado. |
| **Lib** | Biblioteca de código. Aqui, a `unitree_webrtc_connect`, que faz a conexão WebRTC com o robô. |
| **LiDAR** | Sensor de distância a laser. Ver [ficha](o-que-e-lidar.md). |
| **LocalAP / LocalSTA / Remote** | Modos de rede. Ver [ficha](modos-de-rede.md). |
| **MCF** | *Multi-Control Framework*, modo de locomoção com ids próprios. Ver [ficha](ids-normal-vs-mcf.md). |
| **Multicast** | Mensagem enviada para todos os aparelhos da rede ao mesmo tempo. A lib usa para achar o robô pelo serial. |
| **MVP** | *Minimum Viable Product*: a primeira versão, só com o essencial. |
| **Nuvem de pontos** | Conjunto de pontos `(x, y, z)` medidos pelo LiDAR. |
| **Payload** | O conteúdo útil de uma mensagem (os dados), sem o cabeçalho. |
| **SDK** | *Software Development Kit*: o kit oficial da Unitree para programar o robô (`unitree_sdk2`). Usa DDS direto, por cabo, no EDU. |
| **SDP** | Texto que descreve a conexão WebRTC, trocado no início ("oferta" e "resposta"). |
| **SLAM** | *Simultaneous Localization and Mapping*: o robô mapeia o ambiente e se localiza nele ao mesmo tempo. |
| **SN** | Número de série do robô (`B42D...`). Usado para achar o robô na rede e buscar a chave AES. |
| **`SPORT_CMD`** | Dicionário da lib com os comandos de alto nível e seus `api_id`s. |
| **STA-T / TURN** | Modo remoto: a conexão passa por um servidor intermediário (TURN) da Unitree na internet. |
| **Timeout** | Limite de tempo de espera. Passou do limite, desiste com erro. |
| **Track** | Fluxo de mídia (vídeo ou áudio) dentro da conexão WebRTC, separado do data channel. |
| **Tópico** | Nome de um canal de mensagens (ex.: `rt/api/sport/request`). |
| **Voxel** | "Pixel 3D": um cubinho do espaço marcado como ocupado ou livre. |
| **VUI** | Nome que a Unitree dá ao serviço de volume, brilho e LED do Go2 (o significado da sigla não está documentado na lib). |
| **WebRTC** | Protocolo de comunicação em tempo real. É o túnel até o DDS do robô. |
| **`webrtc_bridge`** | Serviço dentro do robô que traduz WebRTC ↔ DDS. |
| **WebSocket** | Conexão que fica aberta entre cliente e servidor, por onde o servidor pode mandar dados continuamente (streams). |
| **Yaw** | Rotação em torno do eixo vertical: virar para a esquerda ou para a direita. |
