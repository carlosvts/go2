---
name: hardware-checklist
description: Gera o roteiro de teste em hardware (robô, TV Box, microfone) a partir dos critérios hardware-only de uma spec, e registra os resultados que o humano trouxer. Use quando uma spec tiver critérios hardware-only pendentes ou quando um humano for testar no laboratório.
---

# hardware-checklist

Você prepara o roteiro e registra o que o humano mede. **Você não executa nada no robô** e não declara hardware verificado por conta própria.

## Gerar o roteiro

1. **Leia** a spec e liste os critérios `hardware-only` com Verificação diferente de `testado-hardware`.
2. **Monte um roteiro por critério**, nesta forma:

```
## H1 — <critério A2>
Pré-requisitos: <robô de pé? balance_stand? api em qual branch? versão atual rodando?>
Segurança: <controle remoto à mão, área livre, risco específico (ex.: damp derruba o robô)>
Passos:
  1. ...
Registrar: <valores, logs, vídeo, hora; nomes de campos/logs a copiar>
Passa se: <número ou observação do critério, copiado da spec>
```

3. **Antes de tudo**, lembrete curto de pré-condições do ambiente: a api e o server rodando na versão que contém a mudança (`git pull` + rebuild), `df -h` e `free -h` na TV Box antes de rodar nela, `GO2S_SAVE_UTTERANCES=1` se o teste envolve fala.
4. **Ordem**: do mais seguro para o mais arriscado. Postura e gesto antes de movimento; comandos com risco (dança longa, `stop` durante gesto) por último e com supervisão total.
5. Escreva o roteiro em `specs/checklists/<id-da-spec>.md` ou na seção "Roteiro hardware-only" da própria spec, conforme o humano preferir. Não crie checklists soltas sem vínculo com spec.

## Registrar resultados

Quando o humano trouxer os resultados:

1. Anote na spec, por critério: valor medido, data, commit, observações. Cole os números que ele deu; não os arredonde nem "limpe".
2. Marque `testado-hardware (AAAA-MM-DD @ commit)` **apenas no critério que o humano disse ter passado**, e só depois de ele relatar. Critério que falhou: marque `falhou` com o que foi observado e abra o ponto para decisão.
3. `verificacao: testado-hardware` e `verificado-em` no frontmatter só quando **todos** os critérios `hardware-only` passaram e o humano confirmou.
4. Resultado que contradiz a spec? Diga isso explicitamente e proponha a correção da spec. Não ajuste o critério para encaixar.
5. Se o teste foi parte de um experimento, encaminhe para `close-experiment`.

## Não faça

- Não invente medidas nem assuma que "deve ter funcionado".
- Não rode comandos que movam o robô.
- Não sugira desligar proteções (desvio de obstáculo, limites de velocidade) para facilitar o teste.
