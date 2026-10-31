# Modos de rede: LocalSTA, LocalAP e Remote

**Em uma frase:** o Go2 é alcançado de três jeitos, e só em um deles (LocalSTA) o endereço do robô pode mudar sozinho.

| Modo | Quem cria a rede | Endereço do robô | Internet? | Na `go2-api` |
|---|---|---|---|---|
| **LocalSTA** | O roteador do laboratório | Dado pelo roteador (**DHCP**), pode mudar a qualquer momento | Não (só LAN) | `GO2_CONNECTION_METHOD=LocalSTA` |
| **LocalAP** | O próprio robô (vira o ponto de acesso) | Sempre **`192.168.12.1`** | Não | `GO2_CONNECTION_METHOD=LocalAP` |
| **Remote** (STA-T) | Servidor da Unitree na internet | — | **Sim**, e conta Unitree | Não suportado, de propósito |

## Na prática

- **No laboratório (LocalSTA):** prefira `GO2_ROBOT_SERIAL_NUMBER` a `GO2_ROBOT_IP`. Com o serial, a lib pergunta à rede inteira "quem tem este serial?" (**multicast**) e acha o robô mesmo que o IP tenha mudado.
- **Em campo (LocalAP):** conecte o computador da API na rede Wi-Fi do robô. Não é preciso configurar IP: a lib usa `192.168.12.1` sozinha.

## Pegadinha

"Ontem funcionava e hoje não conecta" em LocalSTA quase sempre é o IP que mudou. Troque o IP pelo serial no `.env`.

## Mais detalhes

[`go2_modelo_mental.md`](../go2_modelo_mental.md) §3 · [`dossie_go2.md`](../dossie_go2.md) §5 · `.env.example`

## Termos desta ficha

- **IP**: Endereço de um aparelho na rede (ex.: `192.168.12.1`).
- **DHCP**: *Dynamic Host Configuration Protocol*: o roteador distribui os IPs automaticamente e pode trocar o IP de um aparelho.
- **LAN**: *Local Area Network*: a rede local (do laboratório), sem passar pela internet.
- **Multicast**: Mensagem enviada a todos os aparelhos da rede de uma vez.
- **STA / AP**: *Station* (o robô se conecta a um roteador, como um celular) / *Access Point* (o robô vira o roteador e cria a própria rede Wi-Fi).
- **STA-T / TURN**: Modo remoto: a conexão passa por um servidor intermediário (TURN) da Unitree na internet.
- **SN**: *Serial Number*: número de série do robô (`B42D...`).
- **`.env`**: Arquivo de configuração da API, com as variáveis `GO2_*` (modelo em `.env.example`).
