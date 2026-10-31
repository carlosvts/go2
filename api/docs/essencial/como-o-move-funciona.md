# Como o `move` funciona

**Em uma frase:** o robô só anda enquanto recebe `Move` continuamente, então a API **reenvia** o comando várias vezes por segundo durante `duration_s` e depois manda `StopMove`.

```
POST /commands/move {vx, vy, vyaw, duration_s}
   │
   ├─ envia Move imediatamente
   ├─ reenvia Move a GO2_MOVE_RATE_HZ (20–50 Hz) até o fim da janela
   └─ envia StopMove
```

## Na prática

| Regra | Detalhe |
|---|---|
| Unidades | Relativas ao robô: `vx` = frente/trás (m/s), `vy` = lados (m/s), `vyaw` = girar (rad/s; 1 rad/s ≈ 57°/s). |
| Limites | `GO2_MAX_VX`, `GO2_MAX_VY`, `GO2_MAX_VYAW` e `GO2_MOVE_MAX_DURATION_S`. Acima disso → **422**, e nada é enviado. |
| Um por vez | Um `move` novo **substitui** o anterior (sem lease ainda, #7). |
| Interrupção | `stop`, qualquer postura ou gesto cancela o reenvio. |
| Resposta | **202** na hora, sem esperar o fim do movimento. |

## Pegadinha

- O robô precisa estar em **`balance_stand`** antes ([ficha](balance-stand-vs-stand-up.md)).
- Andar por mais tempo exige vários `move` seguidos, porque o teto de duração é proposital (segurança).

## Mais detalhes

`app/robot.py` (`start_move`, `_move_loop`) · `app/routers/posture.py`

## Termos desta ficha

- **Hz**: Hertz: vezes por segundo. 30 Hz = 30 envios por segundo.
- **m/s, rad/s**: Metros por segundo; radianos por segundo (1 rad ≈ 57°).
- **Yaw**: Rotação em torno do eixo vertical: virar para a esquerda ou para a direita.
- **`StopMove`**: Comando que para o movimento e mantém o robô de pé.
- **202 / 422 / 503 / 504**: Códigos de resposta HTTP. Ver [ficha](semantica-202-503-504.md).
- **Lease**: "Posse" temporária do controle do robô, com prazo de validade (planejado, #7).
