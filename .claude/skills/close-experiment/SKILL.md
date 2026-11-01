---
name: close-experiment
description: Fecha um experimento depois que um humano testou em hardware, registrando o resultado e adotando (merge) ou rejeitando (remove o código, mantém a spec). Use quando um humano relatar o resultado de um experimento E-NNN.
---

# close-experiment

Experimento termina em **adotada** ou **rejeitada**. Nunca em "deixa a branch por aí".

## Pré-condições

- O humano trouxe os **resultados medidos** (números, logs, vídeo). Sem medidas, não feche: use `hardware-checklist` para montar o roteiro e peça os dados.
- `criterio-congelado-em` está preenchido na spec. Se estiver `null`, o experimento é inválido: avise e proponha refazer com o critério definido antes.

## Passos

1. **Leia** a spec do experimento e os resultados que o humano forneceu.
2. **Compare com o critério congelado**, ponto a ponto, usando os números da seção "Critério de decisão". Não reinterprete o critério. Se o resultado for inconclusivo conforme o critério, siga o que a spec disse para esse caso.
3. **Preencha "Resultado"**: valores medidos, data, commit, comparação com a linha de base. Registre também o que não foi medido.
4. **Proponha a decisão** ao humano (adota, rejeita ou inconclusivo) com a justificativa baseada no critério. **A decisão é dele.** Só execute o passo 5 depois da confirmação.
5. **Execute a decisão**:
   - **Adotada**: merge da branch em `main`. `status: adotada`, `verificacao: testado-hardware` e `verificado-em: AAAA-MM-DD @ commit` **somente se o humano confirmou que testou em hardware** (registre isso no Resultado). Atualize ou crie a spec de comportamento/contrato correspondente. Se o experimento substituía outro (`alternativa-a`), marque o outro como `rejeitada` ou `obsoleta`.
   - **Rejeitada**: apague o código da branch (não faça merge). Mantenha a spec com `status: rejeitada` e a seção Resultado explicando por que falhou. Atualize "Decisão" e "Histórico". Se o próximo candidato já foi pensado (ex.: LLM depois de regex), proponha a nova spec com `new-spec`.
6. **Commite** só a spec (e, se adotada, o merge). Mensagem no estilo `docs(specs): fecha E-00N (adotada|rejeitada)`.
7. **Entregue** resumo em poucas linhas: decisão, números principais, o que ficou pendente.

## Não faça

- Não apague a spec de experimento rejeitado.
- Não mude critério, dados de teste ou linha de base depois de ver o resultado.
- Não marque `testado-hardware` por conta própria.
- Não adote por "quase passou". O critério é o critério.
