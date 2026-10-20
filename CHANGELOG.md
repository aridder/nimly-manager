# Endringslogg

## 0.3.0

- Fingeravtrykkskann over Bluetooth fra sidepanelet: Home Assistant sender
  `FingerprintScan` til valgt BLE-slot (150–199) via HAs Bluetooth-integrasjon,
  så en ESPHome-proxy ved døra kan brukes. Panelet sier «legg fingeren på NÅ»
  idet kommandoen sendes, siden låsen svarer først når skanningen er ferdig.
- Nye actions `nimly_manager.start_fingerprint_scan` og
  `nimly_manager.cancel_fingerprint_scan` med hard tidsavbrudd, lokal
  avbrytelse og avvisning av ukjent modell og for gammel firmware. Krever at
  brukeren bekrefter å stå ved låsen.
- Første fingeravtrykk-opplåsing (`LOCKED → UNLOCKED`) etter et vellykket skann
  verifiserer gjennom dagens Zigbee-flyt, uendret. BLE-slot lagres som datapunkt
  på slot-posten; ingen automatisk BLE→Zigbee-mapping.
- Eiernøkkelen bor i Home Assistants private lager etter en engangsimport av
  `owner-*.json` under Konfigurer. Den logges aldri og er ikke med i diagnostikk.
- `nimly_ble` ligger nå inne i integrasjonen så HACS leverer det; CLI-en
  `nimly-ble-owner` er uendret. Wheelen inneholder ikke lenger
  `custom_components`.
- `manifest.json` avhenger nå av `bluetooth` og `bluetooth_adapters`.

## 0.2.1

- Unngå dobbelt Zigbee2MQTT-prefiks når device name allerede er et komplett topic.

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
