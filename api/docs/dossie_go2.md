# Dossiê Técnico — Unitree Go2

> Compilado a partir de documentação oficial da Unitree, repositórios da comunidade (TheRoboVerse), pesquisa de segurança pública e revendedores especializados. Specs de mercado variam por região/lote — os números aqui são de múltiplas fontes cruzadas, mas vale confirmar contra o manual do lote específico de vocês quando a precisão importar (ex: relatório técnico).

---

## 1. O que é o Go2

O Go2 é a segunda geração da linha de robôs quadrúpedes da Unitree (sucessor do Go1), lançado com foco em LiDAR 4D integrado de fábrica e IA embarcada. Existe em várias configurações de hardware, indo de um produto de consumo/entretenimento até uma plataforma de pesquisa com compute NVIDIA Jetson embarcado.

---

## 2. Modelos e especificações comparativas

| | **Air** | **Pro** | **X** | **EDU Standard** | **EDU Plus** |
|---|---|---|---|---|---|
| Público-alvo | Consumo/demonstração | Intermediário/pesquisa leve | Sensoriamento avançado | Laboratórios/pesquisa | Pesquisa avançada |
| SDK / desenvolvimento | **Não programável** | SDK aberto (secundário) | SDK aberto | SDK completo + baixo nível | SDK completo + baixo nível |
| Velocidade máx. | ~2,5 m/s | ~3,5 m/s | — | até 3,7 m/s | até 3,7 m/s |
| Payload | ~3–7 kg | ~7–8 kg | — | até 12 kg | até 12 kg |
| Peso (com bateria) | ~15 kg | ~15 kg | — | ~15 kg | ~15 kg |
| Bateria padrão | 8.000 mAh (~1–2h) | 8.000 mAh | — | 15.000 mAh (~2–4h) | 15.000 mAh (~2–4h) |
| Bateria longa (opcional) | 15.000 mAh | 15.000 mAh | — | — | — |
| LiDAR 4D | L1 (360°×90°) | L1 (360°×90°) | — | L1/L2, upgradável (Mid-360, Hesai XT16) | L1/L2, upgradável |
| Câmera frontal | RGB wide-angle 1280×720 | RGB wide-angle 1280×720 | — | + RealSense D435i (profundidade) | + RealSense D435i |
| Sensores de força nas patas | Não | Não | — | **Sim** (instalados de fábrica, não retrofitáveis) | Sim |
| Compute extra (Jetson) | Não disponível | Não disponível | — | Orin Nano, 40 TOPS | Orin NX, 100 TOPS |
| Docking station | Não | Não | — | Sim (I/O extra, ethernet, USB) | Sim |
| Conectividade | WiFi 6, Bluetooth | WiFi 6, Bluetooth | — | + 4G/eSIM opcional | + 4G/eSIM opcional |

**Fonte da distinção mais importante para desenvolvimento**: o Go2 Air normalmente não é vendido como programável — Pro/X/EDU são as versões com acesso a SDK. Dentro dessas, só EDU (Standard/Plus) tem controle de baixo nível (torque por junta) e sensores de força nas patas de fábrica.

---

## 3. Sensores

### 3.1 LiDAR 4D
- Mecanismo giratório visível no focinho — é o LiDAR L1 (ou L2 em configurações mais recentes/upgradadas), campo de visão de 360°×90° (algumas fontes citam 360°×96° para variantes L2).
- Distância mínima detectável: ~0,05 m.
- Gera nuvem de pontos densa, usada tanto pelo comportamento autônomo de desvio de obstáculo do robô quanto disponível para os desenvolvedores via SDK/WebRTC.
- EDU Plus e configurações avançadas permitem upgrade para LiDAR de terceiros (Livox Mid-360, Hesai XT16) para SLAM mais robusto.
- **Importante (achado no código-fonte, não em marketing)**: o dado bruto que chega pelo WebRTC vem comprimido, e a biblioteca de vocês tem **dois decoders diferentes** para ele, com resultados diferentes:
  - **`native`** — Python puro (numpy + lz4), decodifica um grid de ocupação binário comprimido e devolve uma nuvem de pontos real (`x,y,z`, resolução padrão de 0,05m). Auditável, sem dependência de binário de terceiros.
  - **`libvoxel`** (configurado como **padrão** na lib) — roda um binário WebAssembly (`libvoxel.wasm`, minificado, nomes de função de uma letra só) via `wasmtime`, quase certamente extraído do próprio app/web da Unitree. Devolve **malha 3D pronta pra renderização** (`positions`, `uvs`, `indices`, `face_count` — formato tipo WebGL/Three.js), não uma lista de pontos utilizável em cálculo de distância ou SLAM.
  - Ou seja: se nada for trocado explicitamente, o padrão devolve geometria de tela, não dado de distância. Quem quiser usar o LiDAR pra cálculo/processamento precisa trocar para o decoder `native`.

### 3.2 Câmera frontal
- RGB simples, wide-angle, 1280×720 — pensada para teleoperação (ver o que o robô vê), **não tem profundidade própria**.
- Usada também para as funções de "AI vision" citadas no marketing (detecção de objeto, rastreamento de pessoa) — mas essas são capacidades que **dependem de vocês rodarem o modelo**, não vêm como serviço pronto que devolve resultado.

### 3.3 Câmera de profundidade (só EDU)
- Intel RealSense D435i, montada na docking station — sensor estéreo dedicado, close-range.
- Não presente em Air/Pro/X.

### 3.4 Outros
- IMU (orientação/equilíbrio).
- Sensores de força nas 4 patas — **só no EDU**, instalados de fábrica, não é possível adicionar depois em outro modelo.
- Microfone e alto-falante embarcados — existem, mas relatos de campo (inclusive um case da WSO2 rodando agente de voz no robô) descrevem qualidade ruidosa, o que motivou o uso de microfone externo (Anker PowerConf S3) no projeto de vocês.

---

## 4. Compute embarcado

> **Não aplicável ao robô de vocês** — confirmado que não é a versão EDU, não tem docking station nem Jetson. Toda essa seção descreve o que existiria *se* fosse EDU; mantida por completude e caso o grupo NEURON adquira uma unidade EDU no futuro.

Existem **dois domínios de compute completamente separados** no Go2 EDU — isso é importante para arquitetura:

1. **"Cérebro" principal do robô** — roda o firmware oficial da Unitree, controla locomoção, WebRTC, e o assistente de voz nativo (BenBen). É fechado — não dá acesso de shell a esse computador.
2. **Jetson do dock** (só EDU) — módulo NVIDIA Orin Nano (40 TOPS, Standard) ou Orin NX (100 TOPS, Plus), com SO próprio (JetPack, Ubuntu 20.04 + ROS 2 Foxy por padrão, upgradável para JetPack 6.2.1). Esse sim é aberto para os desenvolvedores rodarem código.
   - IP padrão: `192.168.123.18`
   - Usuário/senha padrão: `unitree` / `123` (recomenda-se trocar)
   - Acesso via SSH, VSCode Remote-SSH, ou USB-C→HDMI para desktop direto.
   - Fica na rede interna do robô (faixa `192.168.123.x`) — diferente da rede WiFi externa que o "corpo" do robô usa para se conectar à internet/roteador de vocês.

---

## 5. Conectividade e modos de conexão

O Go2 (via WebRTC, o mesmo protocolo do app oficial) suporta três modos de conexão:

| Modo | Como funciona | Precisa de internet? |
|---|---|---|
| **LocalAP** (Access Point) | O robô cria sua própria rede WiFi; o cliente conecta direto nela. | **Não** — funciona totalmente offline. |
| **LocalSTA** | Robô e cliente na mesma rede local (WiFi do usuário). Pode ser por IP ou descoberta via serial number (multicast). | Não, desde que ambos estejam na mesma LAN. |
| **Remote (STA-T)** | Conexão via servidor TURN da Unitree, controla o robô de qualquer rede. | **Sim** — depende da nuvem da Unitree e de conta cadastrada. |

Isso é relevante para o cenário de campo (zona rural, baixa conectividade): **`LocalAP` não depende de internet nenhuma** — o robô e o celular/dispositivo de controle formam sua própria rede isolada. É o modo que sustentaria a visão do cafeicultor sem depender de sinal de operadora.

Conectividade adicional: WiFi 6 e Bluetooth em todos os modelos; 4G/eSIM opcional nos EDU (para telemetria/imagem remota via rede celular, não para controle direto).

---

## 6. Arquitetura de software oficial

O Go2 roda internamente sobre **CycloneDDS** (uma implementação open-source do padrão DDS — Data Distribution Service), o mesmo tipo de barramento de mensagens usado pelo ROS 2. Alguns tópicos DDS conhecidos e documentados pela comunidade:

- `rt/lowcmd` — comando de baixo nível, controle direto de torque/posição por junta.
- `rt/lowstate` / `rt/lf/lowstate` — leitura de estado de baixo nível (IMU, força nas patas), a versão "lf" é de baixa frequência.
- `rt/sportmodestate` — estado do modo esportivo (posição, velocidade, etc).
- `rt/api/sport/request` e `/response` — comandos de alto nível (os `SPORT_CMD` que o projeto de vocês já usa).
- `rt/api/motion_switcher/request` — troca entre modos de movimento (normal, avançado, IA).
- `rt/api/gpt/request` / `rt/gptflowfeedback` — canal dedicado ao assistente de voz nativo (BenBen), que usa GPT por trás.
- `rt/api/videohub/request`, `rt/api/audiohub/request` — vídeo e áudio.
- `rt/webrtcreq` / `rt/webrtcres` — o próprio canal pelo qual o WebRTC se comunica com o barramento DDS interno.

**CycloneDDS funciona nativamente só no EDU.** Em Air/Pro seria necessário um upgrade de firmware não-oficial para habilitar — não é o caminho recomendado nem o que vocês usam.

**SDK oficial (`unitree_sdk2`)**: biblioteca C++ com wrapper Python (pybind11), acesso total aos tópicos DDS acima, incluindo controle de baixo nível. É o caminho "com todas as portas abertas", mas exige o modo de desenvolvedor do EDU habilitado — que, pelo que vocês relataram, não é o caso do robô de vocês.

### 6.1 Existe uma terceira via (não recomendada)
Segundo o FAQ comunitário do TheRoboVerse, é possível usar o SDK oficial mesmo num Air/Pro **ganhando acesso root ao robô e habilitando manualmente o "desenvolvimento secundário"** — via ferramentas de firmware customizado (o `go2_firmware_tools` da tabela na seção 8). Isso também remove um limite artificial de velocidade/torque que a Unitree aplica por software no Air (usa os mesmos motores do Pro/EDU). Diferente do WebRTC — que funciona sem modificar nada no robô — essa via exige **rootear o firmware do cérebro principal**, com risco real de inutilizar o robô se der errado, e vai além do que a Unitree tolera (é adjacente ao tipo de acesso que a própria empresa está ativamente tentando fechar, ver seção 11). Não recomendado para o escopo atual do projeto — nada do que vocês precisam hoje exige isso.

### 6.2 Como funciona o fluxo de conexão do SDK oficial (e por que ele não tem autenticação)
Diferente do WebRTC (seção 7.3), conectar via SDK oficial não tem handshake de aplicação nenhum:
1. Cabo Ethernet direto no robô, IP manual configurado na mesma sub-rede (ex: `192.168.123.99/24`).
2. Instalar CycloneDDS localmente (compilado do fonte) e configurar variáveis de ambiente apontando pra interface de rede correta.
3. Inicializar com uma linha: `ChannelFactory::Instance()->Init(domain_id, "eth0")` (ou `ChannelFactoryInitialize` no wrapper Python). Isso não abre uma "conexão" com o robô especificamente — só ativa descoberta automática (protocolo DDS SPDP/SEDP, via multicast UDP) na rede local.
4. Publicar/assinar tópicos usa classes tipadas geradas de definições IDL, com um campo `crc()` de checksum — **isso valida integridade do dado, não autentica quem enviou**.

**Consequência de segurança relevante**: não existe verificação de identidade na camada DDS — quem estiver na mesma rede local do robô pode, em princípio, publicar em qualquer tópico, incluindo `rt/lowcmd`. Isso não é especulação: existe uma pesquisa de segurança pública com CVE próprio — **CVE-2026-27509, "Unauthenticated DDS-Based Remote Code Execution"** — documentando exatamente essa falta de autenticação sendo explorada até execução remota de código em robôs Unitree. Contra-intuitivamente, isso torna o canal WebRTC "não-oficial" que vocês usam **mais robusto em termos de modelo de confiança** do que o canal DDS "oficial" seria, caso migrassem — vale considerar isso ao decidir prioridades futuras.

---

## 7. WebRTC — o caminho universal

Como o SDK oficial (DDS) não está disponível para vocês, o WebRTC é o único caminho universal — funciona em Air/Pro/EDU sem exceção, porque é o mesmo protocolo que o app oficial da Unitree usa.

### 7.1 Como funciona por dentro
Existe um serviço interno no robô chamado **`webrtc_bridge`**, que converte as mensagens do canal de dados WebRTC direto para o barramento DDS interno — segundo pesquisa de segurança pública sobre o assunto, esse bridge **não filtra tópicos ou tipos de mensagem**, ou seja, ele é essencialmente uma ponte transparente.

### 7.2 O que passa pelo WebRTC — e o que não passa
Apesar da ponte ser ampla, existe uma limitação documentada pela comunidade: **`rt/lowcmd` (controle de baixo nível, por junta) não é suportado via WebRTC** — só via SDK oficial/DDS direto. Isso significa:
- **Funciona via WebRTC**: gestos e comandos de alto nível (`SPORT_CMD`), modos de movimento, LiDAR, vídeo, áudio (Pro/Edu), leitura de estado (`rt/lf/lowstate`, baixa frequência).
- **Não funciona via WebRTC**: controle direto de torque/posição de cada motor — isso é exclusivo do SDK oficial com DDS habilitado.

Para o escopo do projeto de vocês (controle por voz, gestos, movimento, telemetria, LiDAR), essa limitação não importa — nada do que foi discutido até agora precisa de controle de junta individual.

**O mapa de tópicos é maior do que só `SPORT_MOD`.** Inspecionando o código-fonte da lib de vocês (`constants.py`), o `RTC_TOPIC` documenta dezenas de canais além dos comandos esportivos — desvio de obstáculo tem **tópico próprio e separado** (`rt/api/obstacles_avoid/request`, não faz parte do `SPORT_CMD`), existe um subsistema inteiro de SLAM/mapeamento/navegação (`rt/uslam/...`, incluindo planejamento de trajetória global), posicionamento **UWB** (ultra-wideband, `rt/api/uwbswitch/request` + `rt/uwbstate`), controle de braço robótico e sensor de gás (herdados de outros robôs da linha, o Go2 não tem esse hardware fisicamente), e um tópico de execução de shell (`rt/api/bashrunner/request`) que merece cautela por ser uma superfície de execução de código, não um comando de robô comum. Detalhamento completo na seção 12.

### 7.3 Segurança / autenticação (AES-128)
A partir do firmware 1.1.15 (Go2) / 1.5.1 (G1), o handshake local do WebRTC passou a exigir uma chave AES-128 por dispositivo (em vez da chave estática genérica anterior), amarrada à conta Unitree do dono via API na nuvem deles. É uma medida de autenticação de posse — sem ela, o handshake falha. Firmwares anteriores a essa versão (caso do robô de vocês) não exigem isso.

Confirmado no código-fonte da lib: a chave AES-GCM estática (firmware antigo, sem exigência de chave por dispositivo) está literalmente hardcoded como bytes fixos no módulo de autenticação — bate exatamente com o mecanismo descrito acima. O modo de conexão remota (`Remote`/TURN) funciona **imitando o app oficial** — os headers HTTP enviados fingem ser um Samsung Galaxy S20 rodando o app versão 1.8.0, usando um segredo de assinatura de app extraído do próprio binário da Unitree. Vale registrar, sem alarde: o esquema de criptografia usa AES em modo ECB e hash MD5 no login — ambos considerados fracos pelos padrões atuais, mas isso é do protocolo da Unitree, não algo que o projeto de vocês define ou pode corrigir.

**Atualização — a versão mais recente da lib escalou a personificação.** O módulo mais novo (`unitree_cloud.py`) já não usa `requests` puro — usa `curl_cffi`, uma biblioteca que imita a impressão digital TLS (JA3) exata de um Chrome real, porque a nuvem da Unitree passou a bloquear `requests` comum via proteção estilo Cloudflare. É um sinal concreto de arms race ativo entre a Unitree e a comunidade que mantém essas bibliotecas — outro ponto a favor de mencionar isso ao professor antes de publicar algo em cima disso. Detalhe técnico à parte: a chave AES-128 por dispositivo fica armazenada no robô em `/unitree/etc/key/aes_key.bin` (envolta em RSA) e é espelhada na nuvem da Unitree como `dev.key`.

### 7.4 Os três mecanismos de workaround, em detalhe

**1. Handshake local (`LocalSTA`/`LocalAP`) — troca RSA + AES em duas requisições HTTP:**
- `GET http://{ip}:9991/con_notify` → robô devolve (em base64) a chave pública RSA dele. Em firmware antigo, esse campo vem cifrado com a chave AES-GCM estática hardcoded na lib.
- Cliente gera uma chave AES nova (efêmera), cifra a proposta de conexão WebRTC (SDP) com ela, cifra a própria chave AES com a chave pública RSA do robô, e manda tudo via `POST http://{ip}:9991/con_ing_{sufixo}` — um sufixo de URL calculado por uma lógica sem explicação óbvia (indexação de caracteres numa lista fixa), sinal clássico de lógica copiada de um app decompilado sem entender o "porquê" original.
- É criptografia híbrida clássica (RSA só troca a chave de sessão, AES faz o resto) — a particularidade é que nada disso está documentado pela Unitree, foi reconstruído observando o tráfego real do app.

**2. Handshake remoto (`Remote`/TURN) — personificação, não criptografia:** a API de nuvem da Unitree só aceita requisições que pareçam vir do app oficial. A lib monta headers HTTP inteiros fingindo ser um Android específico rodando a versão exata do app, com uma assinatura calculada usando um segredo extraído do binário do app.

**3. Monkey-patches no `aiortc`/`aioice` — workaround de compatibilidade, não de autenticação:** credenciais ICE fixas (não geradas por sessão, como seria o padrão) e downgrade forçado do algoritmo de hash do certificado DTLS — porque versões novas da biblioteca genérica de WebRTC negociam um formato que o firmware do Go2 (mais antigo) não entende.

**O que essa verificação toda realmente prova**: no firmware de vocês (sem AES-128 por dispositivo), ela prova que o cliente sabe falar o protocolo — não prova *quem* é o cliente. A chave estática é a mesma pra qualquer Go2 nesse firmware e agora está pública neste código. Qualquer pessoa na mesma rede local, com essa biblioteca, consegue parear — é exatamente esse buraco que a chave AES-128 por dispositivo (firmware ≥1.1.15) veio fechar.

---

## 8. Ecossistema de bibliotecas de engenharia reversa

Não existe uma única biblioteca "oficial" para quem não tem o SDK habilitado — o ecossistema é fragmentado, mantido pela comunidade (grande parte gira em torno do fórum/Discord **TheRoboVerse**). Principais projetos identificados:

| Projeto | Autor | Linguagem | O que oferece |
|---|---|---|---|
| `unitree_webrtc_connect` | legion1581 | Python (`aiortc`) | O mais completo — sport commands, vídeo, áudio (Pro/Edu), LiDAR decodificado (2 decoders, ver seção 3.1), gerenciamento de biblioteca de áudio no robô (upload/play/megafone), desvio de obstáculo e controle de LED/volume (VUI) documentados via exemplo oficial. Dá suporte também a **G1 e R1** (não só Go2) — o R1 é quem tem braço robótico, o que explica os tópicos `ARM_COMMAND`/`ARM_FEEDBACK` do `RTC_TOPIC` que o Go2 não usa. **É a base que vocês já usam.** MIT.
| `go2-webrtc` | tfoldi | Python + JS | Interface web simples de controle (dashboard), mais enxuta que a do legion1581. |
| `unitree_ui` / `unitree_go2_ui` | legion1581 | TypeScript | Interface de controle via navegador, já com criptografia AES implementada em JS. |
| `go2_python_sdk` | legion1581 | Python | SDK que tenta unificar CycloneDDS *e* WebRTC sob uma única API — WebRTC ainda não totalmente implementado nessa lib segundo o próprio README. |
| `go2_ros2_sdk` | abizovnuralem | Python/ROS2 | Bridge que expõe o Go2 como tópicos ROS2 padrão (`/cmd_vel`, etc). Depende do stack ROS2 inteiro. |
| `Go2Py` | Rooholla-KhorramBakht | Python | Interface unificada sim/real, focada em pesquisa de locomoção, também usa bridge ROS2 por baixo. |
| `go2_firmware_tools` | legion1581 | Python | Ferramentas para habilitar "desenvolvimento secundário" via firmware customizado (fora do escopo recomendado para vocês). |
| Forks (`VectorRobotics`, `phospho-app`) | comunidade | Python | Forks do driver original com pequenas variações/manutenção paralela. |

> **Correção em relação ao que eu disse antes**: numa resposta anterior, apontei os IDs de `Handstand`, `FreeWalk`, `LeftFlip`, `BackFlip`, `EconomicGait` no `SPORT_CMD` de vocês como "desatualizados/incorretos", comparando com o header oficial `sport_api.hpp` que eu tinha clonado. **Isso estava errado.** Clonando agora o repositório oficial `unitree_webrtc_connect` mais atual, descobri que existe um **segundo dicionário paralelo no próprio código**, `SPORT_CMD_MCF` (Multi-Control Framework, modo introduzido no firmware 1.1.7), com seu **próprio espaço de IDs** pros mesmos nomes de comando — ex: `BackFlip` é `1044` no modo normal, `2043` no modo MCF (que exige o robô já estar nesse modo, sem handshake de `motion_switcher`). O header oficial que eu tinha consultado documentava o espaço MCF, não o normal — os dois são válidos, servem pra modos diferentes do robô. **O dicionário instalado de vocês está correto e é idêntico ao HEAD atual do repositório**, não desatualizado como eu disse antes. Registro esse erro aqui pra não gerar confusão se alguém consultar esse dossiê depois.

### O que **não** encontrei no ecossistema
Depois de vasculhar, não achei nenhum projeto que seja **um serviço de rede leve, standalone, REST + WebSocket, sem exigir o stack completo do ROS2**, feito especificamente para o Go2. O que existe se divide em três categorias — biblioteca Python para importar, dashboard de controle via navegador, ou bridge para dentro do ecossistema ROS2. Uma camada de API HTTP/WS que não carrega ROS2 nem é uma UI de operador parece ser, de fato, uma lacuna real — é exatamente o espaço onde a ideia de vocês (`go2-api`) se encaixaria.

---

## 9. O que já vem pronto de fábrica (comportamentos autônomos)

- **Desvio de obstáculo inteligente** — usa LiDAR + câmera internamente, liga/desliga via app ou (provavelmente) via `SwitchAvoidMode` no espaço de API do SDK oficial.
- **Side-Follow / Pet Mode (ISS 2.0)** — segue uma pessoa/o controle físico a curta distância. O material de marketing menciona "posicionamento vetorial sem fio" — e o código-fonte da lib **corrobora essa hipótese**: existem tópicos dedicados `UWB_REQ`/`UWB_STATE` (`rt/api/uwbswitch/request`, `rt/uwbstate`) — UWB (Ultra-Wideband) é justamente uma tecnologia de posicionamento por rádio de curto alcance, a mesma usada em AirTags e chaves de carro sem fio. Ou seja: **o follow provavelmente rastreia um dispositivo UWB físico** (o controle remoto), não a pessoa por visão computacional — "seguir quem está falando" via voz não teria, hoje, um dispositivo UWB associado pra rastrear. Não achei, em nenhuma fonte, esse comando exposto por nome (`LeadFollow`) no header oficial da Unitree que consultei — reforça que pode nem ser um comando de sport client chamável isoladamente, e sim um modo interno amarrado ao hardware UWB.
- **Assistente de voz nativo (BenBen)** — usa GPT por trás (canal DDS dedicado `rt/api/gpt`), mas roda via serviço em nuvem da própria Unitree, sem gancho para desenvolvedores customizarem.
- **Gestos pré-programados** — os que vocês já usam (`Hello`, `Stretch`, `FingerHeart`, etc) e outros documentados no espaço de API oficial (`sport_api.hpp`, IDs 1001–2058), incluindo modos de marcha mais avançados como `HandStand`, `FreeWalk`, `ClassicWalk`.

---

## 10. Limitações físicas e ambientais

- **Não é à prova d'água nem de poeira** — pensado para "condições secas e terreno moderado", segundo a própria especificação da Unitree.
- Uso recomendado a partir de 14 anos (classificação de produto).
- Autonomia de bateria: ~1–2h nos modelos padrão, ~2–4h com a bateria longa (15.000 mAh, padrão no EDU).
- Peso total (~15 kg com bateria) e payload (3–12 kg dependendo do modelo) — relevante se pensarem em acoplar sensores extras físicos no futuro.

---

## 11. Contexto de segurança do ecossistema (nota informativa)

Pesquisa de segurança pública recente (meados de 2026) documentou falhas na arquitetura de autenticação da Unitree (CVE associado, artigo em arXiv) — incluindo uma vulnerabilidade onde a chave AES-128 por dispositivo podia ser obtida indevidamente via uma falha na API de nuvem ("cloud-oracle"), permitindo acesso não autorizado ao BLE e ao WebRTC de robôs de terceiros. A Unitree corrigiu essa vulnerabilidade específica (checagem de vínculo de propriedade) entre julho e agosto de 2026. Isso reforça um ponto prático para o dossiê institucional: o ecossistema inteiro de bibliotecas de terceiros (incluindo a que vocês usam) nasce de engenharia reversa de um protocolo que a própria fabricante está ativamente tentando proteger — mais um motivo para o alinhamento institucional que vocês já planejam ter com o professor antes de publicar algo com o nome da UFLA.

---

## 12. O que está acessível hoje na `unitree_webrtc_connect` — e o que falta

Levantamento feito lendo o código-fonte real da versão instalada de vocês (`constants.py`, `webrtc_driver.py`, `webrtc_datachannel.py`, `webrtc_audiohub.py`, decoders de LiDAR).

### 12.1 Pronto pra usar — tem classe/método dedicado

| Capacidade | Como acessar |
|---|---|
| Comandos esportivos (mover, gestos) | `SPORT_CMD` + `publish_request_new` no tópico `SPORT_MOD` — já em uso no `robot_control`. |
| Vídeo (recepção) | `WebRTCVideoChannel`, callback via `add_track_callback`. |
| Áudio bidirecional (Pro/Edu) | `WebRTCAudioChannel`, callback via `add_track_callback`, liga/desliga com `switchAudioChannel`. |
| **Biblioteca de áudio no robô** (upload de MP3/WAV, tocar por UUID, modo megafone) | `WebRTCAudioHub` — classe completa, pronta, não usada ainda pelo projeto de vocês. Candidata natural pra substituir o `CMD_PLAY_AUDIO` customizado do modo chat. |
| **Desvio de obstáculo** (liga/desliga/consulta) | `OBSTACLES_AVOID_API`: `SWITCH_SET` (`{"enable": bool}`), `SWITCH_GET` (retorna `{"enable": bool}`). Payload confirmado no exemplo oficial `examples/go2/data_channel/obstacles_avoid/`. |
| **LED e volume (VUI)** | `RTC_TOPIC["VUI"]` com api_ids diretos: `1003` define volume, `1004` lê volume, `1005` define brilho, `1006` lê brilho, `1007` define cor/pisca do LED (`VUI_COLOR` + `time` + `flash_cycle` opcional). Payload confirmado no exemplo oficial `examples/go2/data_channel/vui/`. |
| LiDAR (nuvem de pontos) | Assinar `ULIDAR_ARRAY`, com `set_decoder('native')` explicitamente (padrão é `libvoxel`, que devolve malha, não pontos — seção 3.1) e `disableTrafficSaving(True)` chamado antes. |
| Descoberta do robô na rede | `multicast_scanner.discover_ip_sn()`. |

**Nota importante sobre movimento**: existem **três** mecanismos diferentes de mover o robô, com comportamento distinto quanto a desvio de obstáculo:
1. `SPORT_CMD["Move"]` — comando de velocidade direto no tópico `SPORT_MOD`.
2. `RTC_TOPIC["WIRELESS_CONTROLLER"]` — simula o joystick físico (`lx/ly/rx/ry`). É o que o exemplo oficial de desvio de obstáculo usa pra dirigir — o comentário no próprio exemplo diz que **é esse canal que o serviço de desvio intercepta e filtra** quando o modo está ativo.
3. `OBSTACLES_AVOID_API["MOVE"]` (id `1003`, dentro do tópico de desvio de obstáculo) — um terceiro comando de movimento, com payload `{"x", "y", "yaw", "mode": 0}`, sem resposta.

Não está confirmado se `SPORT_CMD["Move"]` também é filtrado pelo desvio de obstáculo, ou só o canal de joystick simulado — vale testar antes de assumir que ligar o desvio protege todo tipo de comando de movimento.

### 12.2 Tópico existe no `RTC_TOPIC`, mas sem wrapper — exige engenharia reversa do payload

Mapa completo dos tópicos encontrados no `constants.py`, por categoria:

**Estado e telemetria** — `LOW_STATE` (`rt/lf/lowstate`, IMU/força nas patas, baixa frequência), `MULTIPLE_STATE` (provável agregado de vários estados), `SPORT_MOD_STATE`/`LF_SPORT_MOD_STATE` (posição/velocidade, alta e baixa frequência), `SELF_TEST` (autodiagnóstico), `SERVICE_STATE` (saúde dos serviços internos).

**Vídeo** — `FRONT_PHOTO_REQ` (`rt/api/videohub/request`): não é o stream (isso é a track WebRTC separada, já coberta em 12.1) — é a API de controle, tipo "tirar uma foto e salvar no robô".

**LiDAR bruto** — `ULIDAR_SWITCH` (liga/desliga o sensor), `ULIDAR` (dado não comprimido), `ULIDAR_STATE` (saúde do sensor), `ROBOTODOM` (`rt/utlidar/robot_pose`, pose calculada pelo SLAM interno do robô).

**Posicionamento UWB** — `UWB_REQ`/`UWB_STATE`: liga/desliga e lê o módulo de rádio UWB — provável mecanismo do Side-Follow (seção 9).

**Mapeamento manual / pose-graph ("QT")** — `SLAM_QT_COMMAND`, `SLAM_ADD_NODE`, `SLAM_ADD_EDGE`, `SLAM_QT_NOTICE` (`rt/qt_*`): terminologia clássica de pose-graph SLAM (nó = posição/keyframe, aresta = restrição espacial entre duas posições) — provável interface do "modo de mapeamento manual" do app, incluindo fechamento manual de loop. `SLAM_PC_TO_IMAGE_LOCAL` (`rt/pctoimage_local`): conversão de nuvem de pontos pra imagem 2D local, provável geração de miniatura de mapa.

**Pipeline completo de SLAM/navegação autônoma (`uslam`)** — o achado mais significativo: `LIDAR_MAPPING_CMD` (iniciar/parar mapeamento, salvar mapa), `LIDAR_MAPPING_CLOUD_POINT` (nuvem de pontos no referencial do mundo, downsampled), `LIDAR_MAPPING_ODOM` (odometria pré-otimização), `LIDAR_MAPPING_PCD_FILE` (mapa acumulado completo, formato PCD), `LIDAR_MAPPING_SERVER_LOG` (log de debug), `LIDAR_LOCALIZATION_ODOM`/`LIDAR_LOCALIZATION_CLOUD_POINT` (localização dentro de um mapa **já existente**, modo diferente de mapear), `LIDAR_NAVIGATION_GLOBAL_PATH` (caminho planejado — "vá do ponto A ao B sozinho"). Confirma três modos distintos: **mapear → localizar-se num mapa salvo → navegar autonomamente até um destino.** O nome do tópico `SLAM_ODOMETRY` (`rt/lio_sam_ros2/mapping/odometry`) referencia diretamente o **LIO-SAM**, um sistema de SLAM lidar-inercial conhecido da comunidade ROS — confirma que o SLAM interno roda algo compatível com essa convenção, de fábrica, sem o usuário nunca ter instalado ROS2.

**Controle bruto do rádio remoto** — `WIRELESS_CONTROLLER` (`rt/wirelesscontroller`): simula o joystick físico (`lx/ly/rx/ry`) — payload confirmado, ver nota sobre os três mecanismos de movimento na seção 12.1.

**Outros tópicos de API sem wrapper** — `MOTION_SWITCHER` (troca de modo de locomoção), `BASH_REQ` (`rt/api/bashrunner/request` — pelo nome, execução de shell; superfície sensível, cautela), `PROGRAMMING_ACTUATOR_CMD` (provável canal da função de "programação em blocos" do app), `ASSISTANT_RECORDER` (provável controle de gravação pro assistente de voz nativo, o equivalente ao papel do `OpenWakeWord` de vocês), `GRID_MAP` (mapa de ocupação 2D exibido no app).

**Hardware que o Go2 não tem fisicamente** — `ARM_COMMAND`/`ARM_FEEDBACK` (braço robótico), `GAS_SENSOR`/`GAS_SENSOR_REQ` — herdados de outros robôs da linha Unitree, presentes no dicionário mas sem efeito no hardware de vocês.

**O que seria preciso pra usar qualquer um desses**: descobrir o formato exato do `parameter` esperado por cada `api_id`. Três caminhos, em ordem de preferência: (1) achar outro projeto da comunidade que já tenha implementado wrapper pra esse tópico específico; (2) capturar o tráfego do app oficial acionando a função e inspecionar o payload real; (3) tentativa guiada pelos nomes/IDs do header oficial do SDK2 como ponto de partida.

### 12.3 Não mapeado nem no `RTC_TOPIC` de vocês — visto em outras fontes

- `rt/api/sport_lease/request` — parece ser o mecanismo de "lease"/trava de quem detém o controle no momento — possivelmente a peça por trás do `RobotBusyError`.
- `rt/config_change_status`
- O lado de **pedido** do assistente de voz nativo (`rt/api/gpt/request`) não está mapeado — só o `GPT_FEEDBACK` (resposta) está.

### 12.4 Genuinamente impossível via WebRTC — precisa do SDK oficial (DDS)

- **`rt/lowcmd`** (controle de baixo nível por junta) — confirmado pela comunidade como não repassado pela ponte.
- **Leitura de estado em alta frequência** — só a versão "lf" (baixa frequência) está mapeada; a versão de taxa completa não atravessa.

### 12.5 Hardware ausente / incerto

- `ARM_COMMAND`, `GAS_SENSOR` — hardware que o Go2 não tem (seção 12.2).
- Stream de profundidade da câmera RealSense (só em EDU com esse acessório) — não vi indício de canal de vídeo separado pra ela no código atual; provavelmente exigiria acesso direto via USB no Jetson do dock, não pelo canal de vídeo principal do robô.

Pro escopo atual do projeto (voz, gestos, movimento, LiDAR, telemetria), nada das seções 12.3/12.4/12.5 é necessário — a seção 12.2 é onde está o próximo território a explorar, se decidirem ir atrás de desvio de obstáculo ou navegação autônoma.

---

## 13. Decisão de design registrada — controle de concorrência na `go2-api`

Definido ao pensar em múltiplos projetos do NEURON usando o mesmo robô físico ao mesmo tempo (cenário real: dois times, comunicação falha entre eles, comandos conflitantes chegando juntos).

- **Leitura (LiDAR/vídeo/telemetria)**: sem problema — WebSocket é fan-out, todo cliente recebe a mesma cópia.
- **Comandos discretos (gestos)**: só precisa de fila (`asyncio.Queue` + uma única tarefa consumidora), não de trava — executar em sequência já resolve.
- **Controle contínuo (`Move`, joystick simulado)**: precisa de um **lease com dono e prazo de validade**, não uma trava simples:
  - `POST /control/acquire` → token, ou `409` com o dono atual se já estiver em uso.
  - Comandos de movimento contínuo exigem esse token.
  - Token **expira sozinho** sem heartbeat periódico — evita que um cliente travado prenda o controle indefinidamente.
  - `POST /control/release` para devolver explicitamente.
- **Comando de parada (`StopMove`/`Damp`) ignora fila e lease** — sempre passa, de qualquer cliente, sem esperar a vez.
- **Log de origem por comando** (identificador simples de cliente/projeto, não precisa ser autenticação forte) — resolve o sintoma social do problema (saber depois "quem" mandou o quê), não só o técnico.

Como é um único processo Python (`asyncio`) que detém a única conexão WebRTC com o robô, tudo isso cabe em memória do próprio processo — não precisa de lock distribuído nem Redis-lock.

**Nota de investigação futura**: a seção 12.3 já registra um tópico não mapeado, `rt/api/sport_lease/request`, com nome sugestivo de que a própria Unitree pode ter um mecanismo de lease nativo no firmware — possivelmente a peça por trás do `RobotBusyError`. Vale investigar se dá pra reaproveitar esse mecanismo nativo em vez de (ou além de) implementar o lease inteiramente dentro da `go2-api`.

---

## 14. Fontes principais consultadas
- **Repositório oficial `legion1581/unitree_webrtc_connect` clonado diretamente do GitHub** (README, `constants.py`, exemplos oficiais de VUI/desvio de obstáculo/LiDAR/áudio, `unitree_cloud.py`, `_cli.py`) — fonte primária da seção 12 atualizada e da correção sobre `SPORT_CMD_MCF`.
- **Código-fonte da `unitree_webrtc_connect` instalada no projeto de vocês** (fornecido diretamente por você) e do `unitree_sdk2` oficial (clonado do GitHub da Unitree pra verificação cruzada dos IDs de comando) — fonte primária pra toda a seção 12 e para as correções nas seções 3.1, 7.2, 7.3, 8 e 9.
- Documentação e loja oficial da Unitree (unitree.com, shop.unitree.com)
- Repositórios GitHub: `legion1581/unitree_webrtc_connect`, `tfoldi/go2-webrtc`, `abizovnuralem/go2_ros2_sdk`, `legion1581/go2_python_sdk`, `Rooholla-KhorramBakht/Go2Py`, `unitreerobotics/unitree_sdk2`
- Documentação técnica de terceiros (QRE Docs, OpenMind Robotics, TheRoboVerse)
- Revendedores especializados (RobotShop Community, Maverick, Generation Robots, RoboZaps, Robots International) — usados para specs de mercado, cruzados entre si
- Reportagem de pesquisa de segurança (SecurityAffairs, InfosecToday) sobre CVE-2025-35027 / arXiv:2509.14139
- Pesquisa de segurança independente sobre CVE-2026-27509 e CVE-2026-27510 (execução remota de código via DDS não-autenticado e adulteração de banco de dados móvel, respectivamente) — boschko.ca

*Documento compilado a partir de busca na web em agosto de 2026 — specs de produto e estado do ecossistema de software mudam com frequência; revalidar antes de qualquer publicação formal.*
