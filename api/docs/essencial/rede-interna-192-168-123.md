# `192.168.123.x` é a rede interna do robô, não use

**Em uma frase:** `192.168.123.x` é a rede *de dentro* do Go2, entre os componentes dele, e não é por ela que a API conecta.

| IP | O que é |
|---|---|
| `192.168.123.161` | Cérebro principal (controle de movimento) |
| `192.168.123.20` | LiDAR |
| `192.168.123.18` | Jetson do dock (**só EDU**; o robô do projeto é Pro) |

## Na prática

- Essa rede é fixa, não tem DHCP e só é alcançável **por cabo**. O Go2 Pro não tem porta exposta para ela.
- Em `GO2_ROBOT_IP`, use o IP que o **roteador** deu ao robô (LocalSTA). Em LocalAP, não use nenhum IP.

## Pegadinha

Muito tutorial na internet usa `192.168.123.161`. Esses tutoriais são do SDK oficial (DDS) num **EDU com cabo**, um caminho diferente do usado aqui.

## Mais detalhes

[`go2_modelo_mental.md`](../go2_modelo_mental.md) §3 · [`modos-de-rede.md`](modos-de-rede.md)
