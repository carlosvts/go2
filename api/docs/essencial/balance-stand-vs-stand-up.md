# De pé não basta: `balance_stand` vs. `stand_up`

**Em uma frase:** para o robô **andar**, ele precisa estar de pé via `balance_stand`. Só `stand_up` deixa o robô de pé, mas não pronto para se mover.

| Postura | Estado do robô |
|---|---|
| `stand_up` (`StandUp`, 1004) | Levanta e fica parado de pé. |
| `balance_stand` (`BalanceStand`, 1002) | De pé **em modo de equilíbrio ativo**, pronto para receber `Move`. |

## Na prática

Sequência para andar:

```bash
curl -X POST :8000/commands/posture -H 'content-type: application/json' -d '{"cmd":"balance_stand"}'
curl -X POST :8000/commands/move    -H 'content-type: application/json' -d '{"vx":0.3,"vy":0,"vyaw":0,"duration_s":2}'
```

## Pegadinha

Depois de `stand_up`, o `POST /commands/move` responde **202** normalmente, porque a API aceitou e despachou o comando, mas o robô não sai do lugar. O 202 não significa "o robô se mexeu".

> Observado por Carlos no robô do projeto. Se `rise_sit` e `recovery_stand` também deixam o robô pronto para andar: **a confirmar**.

## Mais detalhes

[`como-o-move-funciona.md`](como-o-move-funciona.md) · [`semantica-202-503-504.md`](semantica-202-503-504.md)

## Termos desta ficha

- **`curl`**: Programa de terminal para fazer pedidos HTTP.
- **202 / 422 / 503 / 504**: Códigos de resposta HTTP. Ver [ficha](semantica-202-503-504.md).
- **Endpoint**: Um endereço da API que aceita pedidos (ex.: `POST /commands/move`).
