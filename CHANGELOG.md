# Endringslogg

## 0.2.0

- Egen, mobilvennlig Nimly Manager-side i Home Assistant-sidepanelet.
- Admin-beskyttet, veiledet fingeravtrykksregistrering uten Developer Tools.
- Slotoversikt som skiller mellom verifisert, observert og ukjent status.
- Lokal lagring av trygg slot-metadata; ingen biometri, masterfinger eller PIN lagres.
- Automatisk verifisering når Zigbee2MQTT rapporterer riktig fingeravtrykk-slot.

## 0.1.0

- Første Home Assistant custom integration for Nimly Manager.
- Config flow for ett Zigbee2MQTT device-topic per lås.
- Lokal, tidsbegrenset fingeravtrykksregistrering for slots `003–199`.
- MQTT-verifisering ved `LOCKED → UNLOCKED` med riktig kilde og slot.
- Credential-sikre events og diagnostics.
- Read-only BLE-probe for protokollresearch.
