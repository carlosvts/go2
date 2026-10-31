
# Go2 — modelo mental

> Nota de entendimento, não de referência. Pra consultar `api_id`, tópico ou spec, use o `dossie_go2.md`.
> Robô do projeto: **Go2 PRO**, firmware antigo (< 1.1.15 — não pede chave AES por dispositivo).

---

## 1. A ideia central, em um parágrafo

Por dentro, **tudo no Go2 é DDS**. Locomoção, LiDAR, câmera, LED, voz — todos os serviços internos conversam por um barramento de mensagens (CycloneDDS, o mesmo tipo que o ROS 2 usa), publicando e assinando tópicos com nome tipo `rt/api/sport/request`. Esse barramento é o "sistema nervoso" do robô.

O problema: **esse barramento não é exposto pra fora** num Air/Pro. Só o EDU vem com ele acessível de fábrica.

Então a Unitree colocou uma porta lateral: um serviço interno chamado `webrtc_bridge`, que aceita conexões WebRTC de fora e traduz as mensagens direto pro barramento DDS. **É por essa porta que o app do celular entra.** E é por essa mesma porta que vocês entram, com a lib do legion1581.

```
        [ app celular ]          [ código ]
                 \                      /
                  \                    /
                   ▼   WebRTC (a porta lateral)
              ┌──────────────┐
              │ webrtc_bridge│
              └──────┬───────┘
                     ▼
         ══════ barramento DDS ══════   ← EDU fala aqui direto
          │        │        │      │
       sport    lidar    camera   vui ...
```

**Consequência que explica quase tudo:** o WebRTC não é um "protocolo alternativo de controle". É um *túnel* até o mesmo DDS. Por isso os nomes de tópico são idênticos aos do SDK oficial — vocês estão falando com os mesmos serviços, só que por outra porta.

---

## 2. O que a porta lateral não deixa passar

A ponte é quase transparente, mas não totalmente:

| | Passa pelo WebRTC? |
|---|---|
| Comandos de alto nível (andar, gestos, modos) | sim |
| LiDAR, vídeo, áudio | sim |
| Leitura de estado em **baixa** frequência (`rt/lf/lowstate`) | sim |
| Leitura de estado em taxa cheia | não |
| **`rt/lowcmd`** — torque/posição de cada junta | **não** |

`rt/lowcmd` é a única coisa que o EDU realmente compra. Nada no escopo de vocês (voz, gestos, movimento, LiDAR) precisa disso.

---

## 3. Redes — três coisas diferentes que todo mundo confunde

O Go2 tem **duas redes**, e uma delas tem três modos. Essa é a maior fonte de confusão.

### Rede interna: `192.168.123.x` — **fixa, sem DHCP**
É a rede *dentro* do robô, entre os componentes. IPs estáticos e sempre os mesmos:
- `.161` — cérebro principal (controle de movimento)
- `.18` — Jetson do dock *(só EDU — vocês não têm)*
- `.20` — LiDAR

Você só alcança essa rede por **cabo Ethernet**, e num Pro não há porta exposta pra isso — o conector é do dock do EDU. É por isso que o caminho "SDK oficial" não está só bloqueado por software: falta a porta física também.

### Rede externa: como você chega no robô
Três modos, e **só aqui existe DHCP**:

| Modo | Quem dá o IP | Endereço | Internet? |
|---|---|---|---|
| **LocalAP** | o próprio robô (ele vira o roteador) | robô fixo em `192.168.12.1` | não precisa |
| **LocalSTA** | **o roteador de vocês, via DHCP** | muda sozinho | não precisa (só LAN) |
| **Remote (STA-T)** | — (túnel pela nuvem Unitree) | — | sim |

**É aqui que mora aquele bug do IP que mudou sozinho.** Em LocalSTA o robô é um cliente DHCP comum: o roteador pode dar outro IP a qualquer momento. Duas saídas:
1. Usar o **SN** em vez de IP — a lib acha o robô por descoberta multicast (`serialNumber=`), imune a troca de IP. É o que o SN serve pra vocês.
2. Usar **LocalAP** em campo — endereço fixo, sem roteador, sem internet, sem surpresa.

---

## 4. O que a lib do legion1581 faz, de verdade

`unitree_webrtc_connect` faz **três coisas**, e vale separar porque elas têm naturezas diferentes:

**(a) Fingir ser o app oficial.** O robô só abre a porta WebRTC pra quem sabe fazer um handshake criptográfico específico, que a Unitree nunca documentou. A lib reimplementou byte a byte: troca RSA, sessão AES, e — no modo remoto — headers HTTP fingindo ser um Galaxy S20 rodando o app. *Isso não é design da lib; é o pedágio de usar uma porta que não era pra terceiros.*

**(b) Remendar o `aiortc`.** As libs modernas de WebRTC negociam formatos que o firmware antigo do Go2 não entende. A lib aplica monkey-patches pra forçar compatibilidade.

**(c) Dar nomes às coisas.** Depois que o túnel abre, ela expõe o barramento DDS de forma usável: o dicionário `RTC_TOPIC` (dezenas de tópicos), `SPORT_CMD` (os gestos por ID), decoders de LiDAR, classes pra vídeo/áudio/VUI.

Resumindo em uma frase: **ela transforma "não consigo nem conectar" em "posso publicar em qualquer tópico DDS que a ponte deixe passar".**

E o que ela **não** faz: não é um serviço, não tem endereço de rede, não resolve concorrência. É uma biblioteca que roda dentro de um processo — e como o WebRTC é ponto-a-ponto, **só um processo pode estar conectado por vez**. Abriu o app no celular? Seu código cai.

---

## 5. Onde a `go2-api` entra

Esse último parágrafo *é* a justificativa da API, e não depende de opinião:

- A conexão com o robô é **única e exclusiva** → alguém tem que ser o dono dela.
- A TV Box é cliente fino e vai continuar sendo → ela precisa alcançar esse dono **por rede**.
- O pipeline é poliglota (Python, aarch64 magro, talvez C++ depois) → o limite tem que ser HTTP, não `import`.

Logo: existe um processo que segura a conexão e fala HTTP/WS com o resto. Isso é a API. A escolha não é "ter ou não" — é "desenhada ou improvisada".

```
[ TV Box ]  [ inferência ]  [ dashboard ]
      \           |            /
       ─────── HTTP / WS ─────
                  ▼
            ┌───────────┐
            │  go2-api  │  ← dona da única conexão (lease e fila: planejados, #7)
            └─────┬─────┘
                  ▼  RobotConnection (hoje) → Transport (interface, ideia)
         WebRTCTransport   (DDSTransport, se um dia)
                  ▼
              [  Go2  ]
```

Hoje a conexão é a classe concreta `RobotConnection` (`app/robot.py`). Extrair uma interface `Transport` é a ideia que manteria a discussão do DDS irrelevante pro resto do sistema: se um dia destravar, escreve-se outra implementação e nenhum consumidor percebe. Ainda não foi feito, e só vale a pena quando existir uma segunda implementação.

---

## 6. Cinco coisas que é fácil errar

1. **"O celular controla, então o SDK funciona."** Não — o celular usa WebRTC, a porta lateral. O SDK usa DDS, a porta principal. São portas diferentes.
2. **`192.168.123.x` não tem DHCP e não é onde vocês conectam.** É rede interna, por cabo.
3. **O LiDAR vem errado por padrão.** O decoder default (`libvoxel`) devolve malha 3D pra renderizar, não pontos `x,y,z`. Pra cálculo, trocar pra `native` — e chamar `disableTrafficSaving(True)` antes de assinar.
4. **Existem três jeitos de mandar o robô andar** (`SPORT_CMD["Move"]`, joystick simulado, e o `MOVE` de dentro da API de desvio de obstáculo), e eles interagem diferente com o desvio de obstáculo. Testar antes de assumir.
5. **SN ≠ firmware.** SN é serial (`B42D...`), serve pra descoberta e pra chave AES. Firmware é outro campo do app, e é ele que decide se jailbreak é sequer possível.

---

## Glossário deste documento

| Termo | Significado |
|---|---|
| **AES / AES-128** | *Advanced Encryption Standard*: criptografia simétrica (mesma chave cifra e decifra). "128" é o tamanho da chave em bits. |
| **aiortc / aioice** | Bibliotecas Python que implementam WebRTC e ICE. A lib do projeto é construída em cima delas. |
| **API** | *Application Programming Interface*: a interface que um programa oferece a outros. Aqui, a `go2-api`. |
| **CycloneDDS** | Uma implementação open source do DDS, a usada dentro do Go2. |
| **DDS** | *Data Distribution Service*: o sistema de mensagens interno do Go2. Os serviços publicam e leem dados por tópico. |
| **DHCP** | *Dynamic Host Configuration Protocol*: o roteador distribui IPs automaticamente e pode trocá-los. |
| **EDU / Pro / Air / X** | Versões do Go2. O projeto usa um **Pro**. Só o EDU tem Jetson e DDS aberto. |
| **Firmware** | O software de fábrica que roda dentro do robô. |
| **Handshake** | "Aperto de mão": a troca inicial de mensagens que abre uma conexão. |
| **HTTP / REST** | HTTP: protocolo de pedido e resposta da web. REST: estilo de API em que cada endereço representa um recurso. |
| **IP** | Endereço de um aparelho na rede. |
| **LAN** | *Local Area Network*: a rede local, sem passar pela internet. |
| **Lease** | "Posse" temporária do controle do robô, com token e prazo de validade (planejado, #7). |
| **LiDAR / L1 / L2** | LiDAR (*Light Detection and Ranging*): sensor de distância a laser. L1 e L2 são os modelos da Unitree. Mid-360 (Livox) e XT16 (Hesai) são LiDARs de terceiros. |
| **Monkey-patch** | Alterar, em tempo de execução, o código de outra biblioteca sem mexer no arquivo dela. |
| **Multicast** | Mensagem enviada a todos os aparelhos da rede de uma vez. |
| **RSA** | Criptografia assimétrica (chave pública e privada), aqui usada só para trocar a chave AES. |
| **SDK** | *Software Development Kit*: o kit oficial da Unitree (`unitree_sdk2`), que usa DDS direto. |
| **SN** | *Serial Number*: número de série do robô. |
| **STA / AP / STA-T** | Modos de rede: STA (o robô entra no Wi-Fi do roteador), AP (o robô cria o próprio Wi-Fi), STA-T (remoto, pela nuvem da Unitree). |
| **Tópico** | Nome de um canal de mensagens (ex.: `rt/api/sport/request`). |
| **VUI** | Nome que a Unitree dá ao serviço de volume, brilho e LED do Go2 (o significado da sigla não está documentado na lib). |
| **WebRTC** | *Web Real-Time Communication*: protocolo de comunicação em tempo real. É o túnel até o DDS do robô. |
| **WebSocket (WS)** | Conexão que fica aberta, por onde o servidor manda dados continuamente. |
| **Nomes próprios** | **NEURON**: grupo de pesquisa do projeto, na UFLA (Universidade Federal de Lavras). **TV Box**: aparelho de baixo custo usado como cliente no pipeline de voz. **G1 / R1**: robôs humanoides da Unitree. **BenBen**: assistente de voz de fábrica do Go2. **GPT**: modelo de linguagem da OpenAI. **WSO2**: empresa de software (citada como relato de campo). **Galaxy S20**: celular Samsung, imitado pela lib no modo remoto. **Anker PowerConf S3**: microfone externo usado no projeto. **MIT**: licença open source permissiva. **TheRoboVerse / QRE Docs**: comunidade e documentação de terceiros sobre o Go2. **ISS 2.0**: nome comercial da Unitree para o modo de seguir; o significado da sigla não está documentado. **`rt/qt_*`**: prefixo de tópicos de mapeamento; o significado de "qt" não está documentado. |
