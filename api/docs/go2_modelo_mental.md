
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
