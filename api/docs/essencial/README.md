# Essencial: o que todo mundo no projeto precisa saber

Fichas curtas, uma ideia cada, no máximo uma tela. Para o detalhe, cada ficha aponta para o dossiê, a arquitetura ou o documento da lib.

## Rede e conexão
- [Modos de rede: LocalSTA, LocalAP e Remote](modos-de-rede.md): por que o IP muda e quando usar cada modo.
- [`192.168.123.x` é a rede interna](rede-interna-192-168-123.md): não use esse IP.
- [Uma conexão por vez](uma-conexao-por-vez.md): por que a `go2-api` existe.
- [Firmware e chave AES-128](firmware-e-chave-aes.md): o que muda se o firmware for atualizado.

## Robô e protocolo
- [DDS vs. WebRTC](dds-vs-webrtc.md): o que passa pelo túnel e o que não passa.
- [Anatomia de um comando](anatomia-de-um-comando.md): como um comando chega ao robô.
- [Tópicos que importam](topicos-que-importam.md): os poucos que o projeto usa.
- [Ids: modo normal vs. MCF](ids-normal-vs-mcf.md): mesmo comando, ids diferentes.

## Operação e segurança física
- [Checklist de campo](checklist-de-campo.md): antes de ligar o robô.
- [Parar o robô: `stop` vs. `damp`](parar-o-robo.md): um para, o outro derruba.
- [De pé não basta: `balance_stand` vs. `stand_up`](balance-stand-vs-stand-up.md): requisito para andar.
- [Como o `move` funciona](como-o-move-funciona.md): reenvio contínuo, limites e substituição.
- [O que significam 202, 503 e 504](semantica-202-503-504.md): "aceito" não é "executado".

## Desenvolvimento
- [Rodar e testar sem o robô](rodar-sem-robo.md)
- [O que é um LiDAR](o-que-e-lidar.md)
- [LiDAR: malha vs. pontos](lidar-malha-vs-pontos.md): trocar o decoder.
- [Pegadinhas da lib em uma tela](pegadinhas-da-lib.md)
- [Glossário](glossario.md)

---

Para escrever uma ficha nova, siga o formato: **Em uma frase** → **Na prática** → **Pegadinha** → **Mais detalhes**. Marque como **"a confirmar"** o que não foi validado no robô.
