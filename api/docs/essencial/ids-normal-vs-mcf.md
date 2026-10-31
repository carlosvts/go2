# Ids de comando: modo normal vs. MCF

**Em uma frase:** o mesmo comando pode ter **dois `api_id`s diferentes**, conforme o modo de locomoção em que o robô está.

| Comando | `SPORT_CMD` (normal) | `SPORT_CMD_MCF` |
|---|---|---|
| `FrontFlip` | 1030 | 1030 |
| `BackFlip` | 1044 | **2043** |
| `Handstand` / `HandStand` | 1301 | **2044** |
| `StandUp`, `Move`, `Hello`... | iguais nos dois | |

- **MCF** (Multi-Control Framework) é um modo de locomoção que existe desde o firmware 1.1.7. O robô precisa **já estar** nele, e a troca de modo (`motion_switcher`) não foi mapeada.
- A `go2-api` usa `SPORT_CMD` (normal). Posturas, movimento e gestos têm o mesmo id nos dois espaços.

## Pegadinha

Os ids só divergem justamente nos **truques** (flips, handstand), os comandos de maior risco. Antes de implementar `/commands/trick` (#1), confirmar em qual modo o robô está, senão o robô pode executar o movimento errado.

## Mais detalhes

[`dossie_go2.md`](../dossie_go2.md) §8 (nota) · [`lib_unitree_webrtc_connect.md`](../lib_unitree_webrtc_connect.md) §8

## Termos desta ficha

- **`api_id`**: Número que identifica qual comando executar (ex.: `Move` = 1008).
- **MCF**: *Multi-Control Framework*: um modo de locomoção do Go2 com ids de comando próprios.
- **Firmware**: O software de fábrica que roda dentro do robô. A versão dele muda o que o robô aceita.
- **`motion_switcher`**: Serviço do robô que troca o modo de locomoção (normal ↔ MCF). Ainda não mapeado.
- **`SPORT_CMD`**: Dicionário da lib com o `api_id` de cada comando de alto nível.
