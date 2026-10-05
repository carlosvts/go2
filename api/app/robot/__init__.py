"""Camada do robô: tudo que fala com o Go2, isolado do HTTP.

Organização (cada módulo tem uma única responsabilidade):

- `ports`: contratos (`Protocol`) exigidos da conexão WebRTC.
- `unitree`: única fronteira com a lib `unitree_webrtc_connect`.
- `link`: ciclo de vida da conexão.
- `connection`: estado publicado da conexão e suas transições.
- `envelope` e `channel`: formato e envio dos comandos esportivos.
- `commands`: vocabulário de comandos e objetos de valor.
- `movement`: reenvio periódico do comando `Move`.
- `state` e `payload`: cache de estado e leitura tolerante de payloads.
- `speed`: interpretação da resposta de `GetSpeedLevel`.
- `service`: fachada :class:`~app.robot.service.Go2Robot`, usada pela API.

Este `__init__` não importa nada de propósito, para evitar ciclos de import.
"""
