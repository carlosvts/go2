# Checklist de campo

**Em uma frase:** o que conferir antes de ligar a API com o robô de verdade.

## Antes de subir a API

- [ ] Modo de rede definido: LocalSTA (laboratório) ou LocalAP (campo). Ver [ficha](modos-de-rede.md).
- [ ] `.env` com `GO2_ROBOT_SERIAL_NUMBER` (LocalSTA) ou conectado à Wi-Fi do robô (LocalAP).
- [ ] **App oficial fechado no celular** de todo mundo por perto ([ficha](uma-conexao-por-vez.md)).
- [ ] Nenhum outro script usando a lib.

## Com a API no ar

- [ ] `GET /status` → `connected: true`.
- [ ] `battery_percent` aceitável (`null` = campo ainda não reconhecido; olhe `?raw=true`).
- [ ] `low_state_age_s` pequeno (estado chegando).

## Antes de mexer o robô

- [ ] Área livre ao redor, sem pessoas no caminho.
- [ ] Combinado **quem** dispara `stop` e `damp`, e por qual meio ([ficha](parar-o-robo.md)).
- [ ] Robô em `balance_stand` antes de qualquer `move` ([ficha](balance-stand-vs-stand-up.md)).
- [ ] Começar com velocidades baixas e `duration_s` curto.

## Ao terminar

- [ ] `stand_down`, e só então `damp`, se for desligar.
- [ ] Registrar o que foi validado fisicamente (payloads "pendentes de validação" no código e nas issues).
