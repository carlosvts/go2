# AGENTS.md — Go2 (monorepo)

Robô Unitree Go2 controlado por voz (NEURON/UFLA). O código é escrito majoritariamente por IA; as decisões e a avaliação são humanas (equipe do lab). Em dúvida de escopo ou de comportamento, pergunte.

Monorepo de três microserviços (`api/`, `server/`, `tvbox/`) mais `specs/`. Cada serviço tem seu `AGENTS.md`; leia o do serviço em que for mexer.

Fluxo: TV Box (wake word + VAD) → server (STT → interpretação → fila) → api → Go2, tudo por HTTP. A parada falada segue o mesmo caminho (passa pelo server); só `python -m sense.stop` vai direto à api.

## Arquitetura

- Nenhum serviço importa código de outro. Só HTTP, conforme `specs/contracts/`. Nada compartilhado fora de `specs/`.
- Mudou um contrato HTTP: atualize `specs/contracts/` no mesmo commit.
- A TV Box tem 1,8 GiB de RAM e disco a ~90%: nada pesado em `tvbox/` sem avisar.

## Spec-driven

Regras do processo em `specs/README.md`. Leia antes de mexer em contrato, feature de comportamento ou experimento.

## Verificação

- Nunca escreva `verificacao: testado-hardware` nem preencha `verificado-em`: só um humano da equipe, depois de testar no robô.
- Valor que ninguém mediu (duração de gesto, payload, latência) é `inferido`. Não invente número; escreva `TODO(humano): medir`.
- Teste com mock não prova comportamento no robô; diga isso ao reportar.
- Ao concluir, diga o que não foi possível rodar.

## Segurança (robô físico)

- `damp` (desliga motores, o robô cai) **só por frase exata**. Nunca por embedding, regex fuzzy ou LLM.
- `move` exige `balance_stand` antes. Só `stand_up` não basta. Hoje quem garante isso é o dispatch do server; a api não bloqueia.
- `stop` interrompe o move e deixa o robô de pé (não desliga motores). A parada **falada** passa pelo server e depende de rede e Whisper; a garantia independente é `python -m sense.stop` (direto na api). Nunca escreva ou sugira que a parada por voz é garantida.
- Gesto despachado **não é cancelável**. Só o `stop` interrompe. Frase nova só afeta o que ainda não foi despachado.
- **Modo bípede: desativado de propósito.** Não exponha na api nem habilite no catálogo sem decisão humana explícita, registrada em `specs/decisions/`.
- Comandos da lib fora da api (truques, flips, Wallow, FrontJump/Pounce etc.) só entram depois de a equipe testar um a um.
- Desvio de obstáculo (`obstacle-avoidance`): no teste da equipe com o robô, ele **para quando vai bater**; não foi visto contornar. Não prometa que contorna.
- Não relaxe `GO2S_MAX_UTTERANCE_AGE_S` para mascarar latência. Rejeição por `stale` é comportamento correto.
- Interpretação nunca gera comando fora do catálogo.

## Fora de escopo por enquanto

Lease/arbitragem entre clientes (só no final) e autenticação. Não proponha nem implemente.

## Convenções

Docs e specs em português; identificadores de código em inglês.
