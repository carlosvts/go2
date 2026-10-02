# Firmware e chave AES-128

**Em uma frase:** o firmware do robô do projeto é anterior ao 1.1.15 e por isso **não** exige chave por dispositivo. Se o firmware for atualizado, a conexão passa a exigir a chave.

## Na prática

| Firmware Go2 | Handshake local |
|---|---|
| < 1.1.15 (o do projeto) | Chave estática, embutida na lib. Funciona sem configurar nada. |
| ≥ 1.1.15 | Exige uma **chave AES-128 por robô**, ligada à conta Unitree do dono. |

- O `.env` já tem `GO2_ROBOT_AES_128_KEY`, **mas hoje ela não é repassada à lib**. Se o firmware for atualizado, além de preencher a variável é preciso passar `aes_128_key=` no construtor em `app/robot.py` (o comentário no `connect()` indica onde).
- A chave pode ser obtida com o `examples/fetch_aes_key.py` da lib (repositório upstream).

## Pegadinha

**SN não é firmware.** O serial (`B42D...`) serve para descoberta na rede e para buscar a chave. A versão do firmware aparece em outro campo do app oficial. Evite atualizar o firmware sem combinar com a equipe.

## Mais detalhes

[`dossie_go2.md`](../dossie_go2.md) §7.3–7.4 · `app/config.py` · `app/robot.py` (`connect`)
