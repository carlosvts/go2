# Relatório da rodada "api completa" (madrugada de 2026-11-22)

O que foi feito enquanto você dormia, as decisões que tomei sozinho (com a alternativa descartada) e o que falta. Nada foi testado no robô; nada foi para a `main`; nenhum PR aberto.

<!-- RESUMO -->

## Decisões que tomei sozinho

Cada linha: **decisão** — alternativa descartada — por quê. Marque as que quer mudar; eu ajusto.

### Gerais da rodada
1. **Branch única `feat/api-completa` criada a partir da `feat/ws-video`**. Alternativa: partir da `main`. Motivo: o `/ws/state` reaproveita a fila, o cliente e o laço de stream da F-003; partir da `main` duplicaria esse código. Consequência: a F-003 (vídeo) entra junto quando esta branch for mergeada.
2. **Subagentes em worktrees isolados, um por spec**, integrados por mim. Alternativa: um agente só, em sequência. Motivo: tempo.
3. **Ferramentas de lab novas**: `scripts/make_test_audio.py` (gera os áudios do roteiro) e `scripts/ws_state_client.py` (taxa por tópico do `/ws/state`). Não estavam nas specs; servem só ao roteiro.

4. **README da api reescrito para quem usa só a api**: clone parcial (`git sparse-checkout set api specs/contracts`), Docker, primeiros comandos, rotas por grupo, segurança e a tabela "o que já foi testado no robô". Alternativa: publicar imagem num registro (GHCR) ou espelhar a api num repo próprio. Motivo: as duas pedem configuração de conta e CI; a imagem continua sendo construída localmente com `docker compose --profile api up --build`.
5. **Os worktrees `.claude/worktrees/` foram para o `.gitignore`**, para não sujarem o repo.

### Specs (pendências que eu fechei)
6. **F-004: `GO2_STATE_MAX_CLIENTS=4` e `GO2_STATE_MAX_HZ=10`**. Alternativa: 1 cliente / 5 Hz. Motivo: o stream é leve (só texto); os números são sugestão, sem medida.
7. **F-005: `PUT /device/led`**, como já estava na arquitetura. Alternativa: `POST`.
8. **F-005: `502` como convenção nova da api** (robô recusou ou respondeu algo ilegível), já documentada na arquitetura e no README. Alternativa: reaproveitar `504` ou `500`.
9. **F-005: `GO2_LED_MAX_DURATION_S=60`**. O limite real do robô é desconhecido.
10. **F-005: api_id que falhar no teste do robô sai da api antes do PR.** Alternativa: deixar a rota respondendo `501`.
11. **F-006: envio assíncrono** (`202` + `GET /audio/uploads/{id}`). Alternativa: segurar o HTTP até o fim, o que levaria minutos.
12. **F-006: megafone fora.** A F-007 cobre tocar sem guardar, e o protocolo do megafone (quando chamar o `exit`) não é conhecido.
13. **F-006: `GO2_AUDIO_MAX_UPLOAD_MB=5`**, que dá ~30 s de WAV estéreo e ≥ 3 min de envio.
14. **F-006/F-007: MP3 decodificado com PyAV**, sem `ffmpeg` instalado. Alternativa: o pydub da lib, que exige `ffmpeg` no sistema e no Docker.
15. **F-006: sem consulta prévia do `id`** antes de tocar, renomear ou apagar; o robô responde e código ≠ 0 vira `502`. Alternativa: `404` consultando a lista antes, que tem corrida e dobra a latência.
16. **F-006: concorrência permitida.** Tocar, renomear e apagar durante um envio, e tocar F-006 e F-007 ao mesmo tempo. Alternativa: `409`. O que acontece de fato vai para o roteiro.
17. **F-006: nome de 1 a 64 caracteres**, sem `/`, `\` nem caracteres de controle.
18. **F-006/F-007: régua do `stop` do F-001** (mediana +0,2 s, pior +0,4 s) para o envio e para a reprodução. Você aceitou a mesma régua para o vídeo.
19. **F-007: rotas em `/speaker/*`**, separadas de `/audio/*`, e **sem URL**: só arquivo, para a api não buscar endereços arbitrários na rede.
20. **F-007: uma track própria e persistente que manda silêncio quando ociosa.** Alternativa: trocar a track a cada arquivo. Motivo: verifiquei no aiortc 1.15.0 que o envio RTP termina de vez quando a track de um arquivo acaba; o segundo `play` ficaria mudo.
21. **F-007: arquivo decodificado inteiro antes de tocar** e ordem por número entre `play` e `stop`, para não haver corrida.

### Implementação (decisões dos subagentes, revisadas por mim)
**F-004 (estado e sensores)**
22. `bool` deixou de valer como número também nos campos antigos `battery_percent` e `mode`. Antes, `True` passava como `1`. Alternativa: manter a diferença entre campos antigos e novos.
23. Campos `float` aceitam inteiro e devolvem `float`. Itens ruins: em `motors` cada subcampo ruim vira `null` sozinho; em `range_obstacle` e `foot_force` o campo inteiro vira `null`.
24. `bms_state.bq_ntc`/`mcu_ntc` seguem a spec como inteiro. Se no robô forem listas, viram `null`, e o A10 do roteiro vai mostrar.
25. Erros: a fotografia mantém o `seen_at` de quem já estava na lista. Item malformado é ignorado com log. As mensagens são filtradas pela conexão atual, e uma tentativa de conexão que falha zera a lista.
26. Ordem no aceite do `/ws/state`: `connection`, as seções, `speaker`, `errors`. Eventos e seções dividem uma fila em ordem de chegada. Alternativa: prioridade para eventos, que quebraria a ordem combinada.
27. Formato do `state_metrics` (log): `window_s`, `received` e `rate_hz` por origem, mais `clients: [{sent, dropped}]`.

**F-005 (lanterna, LED, volume)**
28. Os `GET` também exigem `code == 0` antes de ler o nível. Nível que não é inteiro vira `502` (não converte `"3"`).
29. Os tetos do `.env` são conferidos na rota, com mensagem clara. A faixa fixa 0–10 fica no Pydantic.
30. Os api_ids do VUI ficaram em `channel.py` (`VUI_API`), não em `unitree.py`, porque não vêm da lib.

**F-007 (alto-falante)**
31. Uma track nova por conexão: o aiortc para a track antiga quando a conexão acaba.
32. A track entra por `replaceTrack` no transceiver de áudio existente. Alternativa: `addTrack`, que pode criar transceiver novo e exigir renegociação.
33. Um `play` vencido por outro durante a decodificação responde `202` e não toca. Conexão que muda durante a decodificação responde `503`.
34. Upload lido com `python-multipart` direto, em streaming. Alternativa: o `UploadFile` do Starlette, que lê tudo e grava em disco acima de 1 MiB.
35. `GO2_AUDIO_MAX_UPLOAD_MB` é em MiB (×1024²) e aceita fração.

<!-- DECISOES-F006 -->
