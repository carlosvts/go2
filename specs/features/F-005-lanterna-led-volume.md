---
id: F-005
titulo: Lanterna, LED e volume do robô (/device/*)
tipo: comportamento
status: proposta
servicos: [api]
verificacao: inferido
verificado-em: null
depende-de: []                 # a confirmação por /status.settings (F-004) é opcional
---

# F-005 — Lanterna, LED e volume do robô (`/device/*`)

## Objetivo
Controlar o que o Go2 mostra e o quão alto ele soa: brilho da lanterna, cor do LED e volume do alto-falante. É a rota de que depende o sinal de "câmera ligada" pedido na F-003, e o volume é o controle do áudio das F-006/F-007.

Termos desta spec, para não confundir com a F-003:
- **lanterna**: a luz cujo **brilho** muda (api_ids 1005/1006);
- **LED**: a luz cuja **cor** muda (api_id 1007).

Qual peça física é cada uma não foi visto (`TODO(humano): observar`, A6/A7). Se for a mesma, a spec é corrigida.

Base: `api/docs/cobertura_lib.md` §4. Os api_ids **não estão nas constantes da lib 2.2.0**; vêm do exemplo `examples/go2/data_channel/vui/vui.py` do repositório do legion e não foram vistos no robô.

## Comportamento

Todas as chamadas vão ao tópico `RTC_TOPIC["VUI"]` (`rt/api/vui/request`) com `publish_request_new`, que espera resposta, com timeout `GO2_REQUEST_TIMEOUT_S` (a lib não tem timeout próprio). O `parameter` vai como **dict**, exatamente como no exemplo:

```python
await conn.datachannel.pub_sub.publish_request_new(
    RTC_TOPIC["VUI"], {"api_id": 1005, "parameter": {"brightness": brightness_level}}
)
await conn.datachannel.pub_sub.publish_request_new(RTC_TOPIC["VUI"], {"api_id": 1006})
```

| Rota | api_id | `parameter` ao robô | Resposta da api |
|---|---|---|---|
| `PUT /device/brightness` `{"level"}` | 1005 | `{"brightness": level}` | `202` `{"level"}` |
| `GET /device/brightness` | 1006 | — | `200` `{"level"}` ← `json.loads(data.data)["brightness"]` |
| `PUT /device/volume` `{"level"}` | 1003 | `{"volume": level}` | `202` `{"level"}` |
| `GET /device/volume` | 1004 | — | `200` `{"level"}` ← `json.loads(data.data)["volume"]` |
| `PUT /device/led` `{"color", "duration_s", "flash_cycle_ms"?}` | 1007 | `{"color", "time": duration_s}` e, se houver, `"flash_cycle": flash_cycle_ms` | `202` `{"color", "duration_s", "flash_cycle_ms"}` |

### Validação (antes de falar com o robô; fora disso `422`, nada publicado)
- Modo estrito: `true` e `5.0` não valem como inteiro.
- `level` do brilho: inteiro, `0 ≤ level ≤ GO2_MAX_BRIGHTNESS`.
- `level` do volume: inteiro, `0 ≤ level ≤ GO2_MAX_VOLUME`.
- A faixa 0–10 vem do exemplo; os tetos não podem passar de 10. A mensagem do `422` diz o teto.
- `color`: `white`, `red`, `yellow`, `blue`, `green`, `cyan`, `purple` (`VUI_COLOR` da lib).
- `duration_s`: inteiro, `1 ≤ duration_s ≤ GO2_LED_MAX_DURATION_S`.
- `flash_cycle_ms` (opcional): inteiro, `499 ≤ flash_cycle_ms ≤ duration_s × 1000`. É o comentário do exemplo, `inferido`. Sem ele, a cor fica fixa.

### Respostas e erros
- **`202`** depois de o robô responder com `data.header.status.code == 0`: o robô **aceitou** o pedido. É a mesma convenção das escritas atuais (`PUT /commands/speed`), que respondem `202` (decisão do humano). Para brilho e volume, o `GET` seguinte confirma o valor.
- **`502`** (convenção nova da api, entra em `api/docs/arquitetura_go2_api.md` §4): o robô respondeu com código ≠ 0, ou com resposta sem `header.status`, ou o `GET` voltou sem o campo esperado ou com `data.data` que não é JSON. O `detail` traz o código ou o motivo.
- **`503`**: sem conexão. **`504`**: sem resposta em `GO2_REQUEST_TIMEOUT_S`. São as convenções atuais.
- Em `502` e `504`, **o estado do robô é desconhecido**: o pedido pode ter sido aplicado. Quem chamou confere com o `GET` (ou com `/status.settings`).
- O LED não tem `GET`: nenhum api_id de leitura de cor é conhecido.
- Dois pedidos VUI simultâneos são independentes: cada resposta volta ao pedido certo (a lib casa a resposta pelo id da request).

### `/capabilities`
Não muda (decisão do humano): as rotas `/device/*` ficam no OpenAPI (`/docs`) e no README da api.

### Configuração (`.env`)

| Variável | Padrão | Origem |
|---|---|---|
| `GO2_MAX_VOLUME` | `10` (sem teto) | humano (2026-11-21): sem teto por padrão; quem distribui baixa no `.env` |
| `GO2_MAX_BRIGHTNESS` | `10` (sem teto) | humano (2026-11-21), idem |
| `GO2_LED_MAX_DURATION_S` | `60` | sugerido pelo Claude (`inferido`); o limite do robô não é conhecido |

Os tetos só limitam o que passa pela api. Volume e brilho já configurados no robô (pelo app oficial ou antes) podem estar acima deles.

### Contrato
`specs/contracts/api.openapi.json` regenerado no commit da implementação; `api/docs/arquitetura_go2_api.md` §4.3 atualizado (rotas, `202`, `502`).

## Critérios de aceite

| ID | Critério (observável) | Como verificar | Tipo | Verificação |
|---|---|---|---|---|
| A1 | Cada rota publica no tópico `VUI`, com `publish_request_new`, o api_id e o `parameter` (dict) da tabela; o LED sem `flash_cycle_ms` não manda `flash_cycle` | teste com fake pub_sub | software | inferido |
| A2 | Valores inválidos levam `422` sem nada publicado, um caso por valor:<br>`level` −1, 11, acima do teto, `true` e `5.0`;<br>cor fora da lista;<br>`duration_s` 0 e acima do teto;<br>`flash_cycle_ms` 498 e `duration_s × 1000 + 1`.<br>Os limites exatos (499 e `duration_s × 1000`) são aceitos | teste | software | inferido |
| A3 | Resposta com `status.code == 0` → `202`; outro código ou sem `header.status` → `502`; sem conexão → `503`; sem resposta em `GO2_REQUEST_TIMEOUT_S` → `504`. Durante a espera de um pedido VUI, `POST /commands/stop` responde e é publicado. Dois pedidos VUI simultâneos recebem cada um a sua resposta | teste | software | inferido |
| A4 | Os `GET` leem o nível de `data.data` (string JSON); campo ausente ou JSON inválido → `502` | teste | software | inferido |
| A5 | As rotas `/device/*` não aparecem no `/capabilities`, e o `version` dele não muda | teste | software | inferido |
| A6 | Com o robô real (deitado, ninguém de frente para ele): `GET /device/brightness` responde; `PUT` com 1, depois 0 a 10, muda a lanterna de apagada a máxima; o `GET` devolve o valor definido. Registrar a peça física que muda e o código de resposta | roteiro | hardware-only | inferido |
| A7 | Com o robô real, `PUT /device/led` com cada uma das 7 cores e `duration_s=5` mostra a cor; cronometrar: a cor dura entre 4 e 6 s. Com `flash_cycle_ms=1000`, ela pisca; registrar a cadência. Registrar o que o LED faz quando o tempo acaba e qual peça física muda | roteiro | hardware-only | inferido |
| A8 | Com o robô real, `GET /device/volume` responde; `PUT` com 2 e depois 8 muda o volume de um som tocado pelo robô (F-006 ou F-007, na mesma sessão), e o `GET` devolve o valor definido | roteiro | hardware-only | inferido |

O A8 depende de a F-006 ou a F-007 tocar som. Por isso as quatro specs da rodada vão juntas para o robô.

## Fora de escopo
- Sinal automático de "câmera ligada" (F-003): só depois de A7 passar, numa mudança da F-003.
- Sequências ou animações de LED, mais de uma cor ao mesmo tempo, leitura da cor.
- Lease: dois clientes mudando o LED ao mesmo tempo, vale o último (AGENTS.md raiz).

## Segurança
- Não é comando de movimento: o tópico VUI é de luz e som, pelo nome e pelo exemplo (`inferido`).
- A lanterna no máximo pode ofuscar quem está de frente para o robô. Volume alto perto de gente assusta. Os tetos existem para quem distribui, mas por padrão não limitam (decisão do humano).
- Os api_ids e payloads vêm de exemplo, não da lib: comando errado pode fazer outra coisa no robô. O roteiro testa com o robô deitado, primeiro as leituras e depois valores baixos.
- **api_id que não fizer o esperado no robô** (código ≠ 0 ou outro efeito): a rota sai da api antes do PR, e a spec registra o motivo. Decidido pelo Claude, a confirmar.

## Impacto HRI

| Pergunta | Resposta |
|---|---|
| Que interação da pessoa com o robô isto muda? | O robô passa a mudar de luz e de volume quando um cliente pede. |
| O que a pessoa percebe em sucesso, rejeição, erro e espera? | Quem está perto vê a lanterna, a cor do LED ou o volume mudar. `422` não muda nada no robô. Em `502`/`504` o estado é desconhecido: a luz ou o volume podem ter mudado. O retorno é só para quem chamou a api. |
| Latência percebida | Do pedido à mudança de luz: `inferido`; `TODO(humano): medir` (A6/A7). |
| O retorno promete algo que o sistema não fez? | `202` significa que o robô **aceitou**, não que a pessoa viu a luz. Para brilho e volume, o `GET` confirma o valor guardado no robô. |
| Pode surpreender ou assustar quem está perto? | Lanterna forte de repente, LED piscando ou volume alto podem assustar, sobretudo criança. |
| Quem usa? | Quem programa contra a api. Quem está perto do robô só percebe o efeito. |
| Como validar com uma pessoa que não conhece o sistema? | Sem critério `usuario`: as cores ainda não têm significado combinado. A spec que der significado a uma cor terá um. |

## Hipóteses não verificadas
- Os api_ids 1003–1007 e os payloads (exemplo `vui.py`). `TODO(humano): conferir` (A6–A8).
- Faixa 0–10 de brilho e volume; unidade de `time` (s) e de `flash_cycle` (ms).
- Formato da resposta (`data.header.status.code`, `data.data` como string JSON).
- O que o LED faz quando o `time` acaba; se o firmware usa o LED para sinais próprios (bateria, erro, conexão) que o comando esconde.
- Duração máxima aceita pelo robô.
- Se brilho e volume continuam depois de a api cair ou de o robô reiniciar. `TODO(humano): observar`.

## Decisões
Tomadas (2026-11-21, humano):
- lanterna, LED e volume entram;
- escritas respondem `202` (aceite do robô), como as atuais;
- `/capabilities` não muda;
- sem teto por padrão (10 e 10);
- api independente do server e da TV Box.

Tomadas pelo Claude (2026-11-22, a confirmar no relatório da rodada):
- `PUT /device/led` (como em `arquitetura_go2_api.md` §4.3);
- `502` como convenção nova;
- `GO2_LED_MAX_DURATION_S` = `60`;
- api_id que falhar no robô sai da api.

## Roteiro hardware-only
No roteiro único da rodada: [`specs/checklists/api-completa.md`](../checklists/api-completa.md).

## Histórico
- 2026-11-21: criada (proposta).
- 2026-11-22: revisada pelo `spec-reviewer` e com as decisões do humano. Mudanças:
  - `202` em vez de `200`;
  - `PUT /device/led`;
  - `/capabilities` fora;
  - `502` definido;
  - estado desconhecido em `502`/`504`;
  - `parameter` como dict;
  - limites inclusivos;
  - tolerância do A7;
  - `stop` durante a espera (A3).
