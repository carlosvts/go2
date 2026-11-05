# Glossário

Termo, definição curta e o que **não** significa.

| Termo | Definição | Não confundir com |
|---|---|---|
| **Desvio de obstáculo** (`obstacle-avoidance`) | Serviço nativo do Go2, ligado/desligado por `PUT /safety/obstacle-avoidance`. No teste da equipe com o robô, ele para quando vai bater em algo. | Contorno: não foi visto contornar obstáculos; não prometa que contorna. |
| **`balance_stand`** | Modo de equilíbrio. O `move` exige este modo; só `stand_up` não basta. A "mexida" e o atraso extra no primeiro movimento depois de levantar são a entrada nele. | `stand_up` |
| **`stop`** | Interrompe o move em andamento e mantém o robô de pé. Não desliga motores. A parada falada passa pelo server; `python -m sense.stop` vai direto à api. | `damp` |
| **`damp`** | Desliga os motores; o robô cai. Só por frase exata. | `stop` |
| **Gesto despachado** | Gesto/postura já enviado à api. Não é cancelável; só `stop` interrompe. | Comando ainda na fila (esse pode ser substituído). |
| **Catálogo** (`catalog.yaml`) | Lista de comandos que o server pode despachar, com frases, `max_duration_s` e `enabled`. Gerado por `build_catalog.py`. | `/capabilities` (o que a api aceita). |
| **`max_duration_s`** | Quanto a fila espera depois de despachar um comando, porque a api não avisa o fim do gesto. Muitos valores são **inferidos**. | Duração medida. |
| **Thin** | Único modo atual da TV Box: só wake word + gravação do comando; toda interpretação no server. | Edge (removido). |
| **Wake word** | "hey jarvis" (openWakeWord) na TV Box. | Comando. |
| **Utterance** | Uma fala completa enviada ao server (`POST /v1/utterance`), com `utterance_id`. | Frase interpretada. |
| **`edge_id`** | Identificador do cliente que enviou a fala (padrão: nome da máquina; `EDGE_ID` no `.env`). | Modo edge. |
| **Pré-roll** (`PRE_ROLL_S`) | Segundos de áudio antes da wake word incluídos no envio. Pode vazar o fim da wake word ("-vis"). | VAD. |
| **VAD** | Detector de fim de fala (por volume; Silero opcional na wake word). | Wake word. |
| **Lease** | Arbitragem de qual cliente controla o robô. Fora de escopo até o final, junto com autenticação. | Fila do server. |
| **Hardware-only** | Critério que só se valida com robô ou TV Box reais. | Teste automático com mock. |
| **Retorno ao usuário** | O que a pessoa percebe depois de falar: som da TV Box (`beep`, `processing`, `confirmed`, `rejected`, `unconfirmed`, `blocked`), fala ou movimento do robô. | Resposta HTTP (`status`). O `status` só vira retorno quando a TV Box o traduz em som. |
| **Latência percebida** | Tempo da última palavra da pessoa até o primeiro retorno que ela percebe. | Latência de componente (`stt_ms`, `total_ms`): a soma delas não inclui o silêncio do VAD nem o atraso do som. |
| **Critério `usuario`** | Critério de aceite que só uma pessoa que não conhece o sistema valida (entendeu o retorno, se assustou, achou natural). Conta como `hardware-only`; só humano marca `testado-usuario`. | Teste com o próprio time, que já sabe como o sistema responde. |
