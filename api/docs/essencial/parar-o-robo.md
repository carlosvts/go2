# Parar o robô: `stop` vs. `damp`

**Em uma frase:** `stop` faz o robô parar de andar e continuar de pé. `damp` **desliga os motores, e o robô cai**.

| Comando | O que acontece | Quando usar |
|---|---|---|
| `POST /commands/stop` | Cancela o `move` em curso e manda `StopMove`. Fica de pé onde está. | Parada normal. Funciona sempre, de qualquer cliente. |
| `POST /commands/posture {"cmd":"damp"}` | Tira a força das juntas. Se estiver de pé, **desaba**. | Emergência real (robô descontrolado) ou já deitado, para desligar. |
| `POST /commands/posture {"cmd":"stand_down"}` | Deita de forma controlada. | Encerrar o uso. |

## Na prática

Em qualquer teste físico, combine antes **quem** dispara o `damp` e por qual meio (curl pronto no terminal, controle físico).

## Truques (flips, handstand)

Têm risco real de queda e dano. Ainda não foram implementados (#1). Quando forem, vão exigir `"confirm": true` e só devem ser testados em área livre e com piso macio.

## Pegadinha

`damp` não é um "stop mais forte". Num robô de pé, ele é uma queda de ~15 kg.

## Mais detalhes

`README.md` (Endpoints) · [`como-o-move-funciona.md`](como-o-move-funciona.md)

## Termos desta ficha

- **`StopMove`**: Comando que para o movimento e mantém o robô de pé.
- **Damp**: Postura que tira a força dos motores. De pé, o robô cai.
- **Junta**: Articulação do robô movida por um motor (o Go2 tem 12, 3 por pata).
- **`curl`**: Programa de terminal para fazer pedidos HTTP.
- **Endpoint**: Um endereço da API que aceita pedidos (ex.: `POST /commands/move`).
