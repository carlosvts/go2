# LiDAR: malha vs. pontos

**Em uma frase:** por padrão, a lib decodifica o LiDAR como **malha 3D para desenhar na tela**, e não como **pontos para calcular distância**. É preciso trocar o decoder.

| Decoder | Como roda | Devolve | Serve para |
|---|---|---|---|
| `libvoxel` (**padrão**) | Binário WebAssembly extraído do app da Unitree | `positions`, `uvs`, `indices` (malha tipo WebGL) | Renderizar |
| `native` | Python (lz4 + numpy) | `{"points": array (N, 3)}` em metros | Calcular distância, SLAM, desvio |

## Na prática

A cada conexão (o decoder some quando a conexão é refeita):

```python
conn.datachannel.set_decoder("native")
await asyncio.wait_for(conn.datachannel.disableTrafficSaving(True), timeout)
conn.datachannel.pub_sub.subscribe(RTC_TOPIC["ULIDAR_ARRAY"], on_lidar)
# on_lidar: message["data"]["data"]["points"] → np.ndarray (N, 3)
```

Nenhuma alteração na lib é necessária.

## Pegadinhas

- `numpy.ndarray` não vira JSON direto: é preciso converter antes de mandar por WebSocket.
- A decodificação pesa no processador e roda no mesmo fluxo que atende todo o resto da API ([event loop](glossario.md)). Só assine o tópico se alguém estiver ouvindo (#13).
- Se é preciso ligar o sensor via `rt/utlidar/switch`: **a confirmar**.

## Mais detalhes

[`lib_unitree_webrtc_connect.md`](../lib_unitree_webrtc_connect.md) §6 · issue #6

## Termos desta ficha

- **Decoder**: O código que transforma o dado comprimido que chega do robô em algo utilizável.
- **Malha**: Superfície 3D feita de triângulos, usada para desenhar na tela.
- **WebGL / WebAssembly**: WebGL: tecnologia de gráficos 3D do navegador. WebAssembly (WASM): formato de programa compilado que roda em navegadores e, aqui, dentro do Python.
- **lz4 / numpy / `ndarray`**: lz4: algoritmo de compressão. numpy: biblioteca de cálculo numérico; `ndarray` é a matriz dela.
- **SLAM**: *Simultaneous Localization and Mapping*: o robô mapeia o ambiente e se localiza nele ao mesmo tempo.
- **JSON**: *JavaScript Object Notation*: formato de texto para dados, como `{"chave": "valor"}`.
- **Event loop**: O "motor" do `asyncio`: executa as tarefas da API uma de cada vez. Se uma demora, todas esperam.
- **Subscribe / unsubscribe**: Assinar / cancelar a assinatura de um tópico (passar a receber / parar de receber as mensagens).
