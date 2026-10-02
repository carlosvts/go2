# O que é um LiDAR

**Em uma frase:** um LiDAR mede distâncias disparando pulsos de laser e cronometrando quanto tempo a luz leva para voltar. Com milhares de medidas por segundo em várias direções, ele monta uma "nuvem de pontos" 3D do ambiente.

```
 laser ──────────────▶ parede
       ◀──────────────
 tempo de ida e volta × velocidade da luz ÷ 2 = distância
```

## O que ele entrega

- **Nuvem de pontos:** uma lista de pontos `(x, y, z)` em metros, cada um sendo um lugar onde o laser bateu em algo.
- Ele **não** vê cor nem textura (isso é a câmera). Vê **forma e distância**, e funciona no escuro.

## O LiDAR do Go2

| | |
|---|---|
| Modelo | Unitree L1, no focinho (a parte que gira) |
| Campo de visão | 360° × 90° |
| Distância mínima | ~0,05 m |
| Uso interno do robô | Desvio de obstáculo e mapeamento |

## Como o dado chega pelo WebRTC

Os pontos crus não chegam. O robô envia um **mapa de voxels** comprimido: o espaço é dividido em cubinhos (o tamanho vem na própria mensagem, no campo `resolution`; o padrão do decoder é 5 cm), e cada um é marcado como ocupado ou livre. O decoder transforma os cubinhos ocupados de volta em pontos `(x, y, z)`. Por isso a "resolução" da nuvem é a do grid, não a do laser. Ver [`lidar-malha-vs-pontos.md`](lidar-malha-vs-pontos.md).

## Para que serve no projeto

Medir distância até obstáculos, detectar o que está à frente e, no futuro, mapear o ambiente.

## Mais detalhes

[`dossie_go2.md`](../dossie_go2.md) §3.1
