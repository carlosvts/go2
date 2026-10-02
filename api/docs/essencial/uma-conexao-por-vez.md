# Uma conexão por vez

**Em uma frase:** o robô aceita **uma** conexão WebRTC por vez, e é por isso que a `go2-api` existe.

## Na prática

- A `go2-api` segura essa conexão única. Todos os outros (pipeline de voz, modo chat, outros projetos) falam com a API por HTTP/WebSocket e nunca com o robô direto.
- Um segundo cliente WebRTC (outro script, o app oficial no celular) entra em disputa com a API. Quando o robô **recusa** o novo cliente, a lib levanta o erro `RobotBusyError`. Relatos da equipe dizem que abrir o app no celular derruba quem estava conectado. Qual dos dois acontece em cada caso fica **a confirmar** no robô.
- Se a conexão da API cair, hoje é preciso **reiniciar a API**: não há reconexão automática no MVP.

## Pegadinha

Com a API rodando, "só vou testar rapidinho um script com a lib" derruba a API ou é recusado. Teste pela API, ou pare a API antes.

## Mais detalhes

[`arquitetura_go2_api.md`](../arquitetura_go2_api.md) §3 · [`go2_modelo_mental.md`](../go2_modelo_mental.md) §4–5

## Termos desta ficha

- **WebRTC**: *Web Real-Time Communication*: protocolo de comunicação em tempo real. É o túnel que liga a API ao robô.
- **API**: *Application Programming Interface*: o "balcão de atendimento" de um programa. Aqui, a `go2-api`, que recebe pedidos HTTP e fala com o robô.
- **HTTP**: Protocolo de pedido e resposta da web (é o que o navegador e o `curl` usam).
- **WebSocket**: Conexão que fica aberta entre cliente e servidor, por onde o servidor pode mandar dados continuamente (streams).
- **Lib**: Biblioteca de código. Aqui, a `unitree_webrtc_connect`, que faz a conexão WebRTC com o robô.
- **`RobotBusyError`**: Erro da lib quando o robô recusa uma conexão porque já está ocupado com outra.
- **MVP**: *Minimum Viable Product*: a primeira versão, só com o essencial.
- **Pipeline de voz**: A cadeia do projeto que transforma fala em comando (microfone → reconhecimento → API).
