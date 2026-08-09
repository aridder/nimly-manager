# Fingeravtrykk-enrollment: beslutning og sikker testplan

Sist verifisert: 2026-08-09.

## Produktbeslutning

Status er **GUIDED LOCAL ENROLLMENT / EVENT-VERIFIED**.

Nimly Manager skal ikke gjøre BLE-capture eller kreve Nimly-konto-/appnøkler i
den ordinære produktflyten. Enrollment gjøres med låsens dokumenterte lokale
programmering. Home Assistant velger person og slot, viser trinnene og
verifiserer resultatet når Zigbee rapporterer første opplåsing fra samme
fingerprint-slot.

Den reverserte Nimly BLE-protokollen beskriver kommandoene
`FingerprintScan` (`0x57`) og `FingerprintClear` (`0x58`). Dagens kjente Zigbee-
og Zigbee2MQTT-kontrakt har ingen tilsvarende kommando. Fingerprint-bruk kan
observeres over Zigbee, men enrollment kan ikke bygges som et ordinært Z2M-
expose før en faktisk Zigbee-kommando eventuelt blir dokumentert.

Kilder:

- [Nimly BLE Protocol Reference](https://github.com/fredrik-lindseth/onesti-lock/blob/da1246aa75266e9da37ff631da32973ebbb6921f/docs/nimly-ble-app/ble-protocol.md)
- [Dokumenterte begrensninger i Onesti Lock-integrasjonen](https://github.com/fredrik-lindseth/onesti-lock#limitations)
- [Fysisk observerte endpoint-clusters](https://github.com/fredrik-lindseth/onesti-lock/blob/main/docs/zigbee-protocol/zigbee-captures.md#endpoint-11-clusters)

## Hva som er implementert nå

`nimly-ble-probe` gjør bare:

1. BLE-skanning etter Nimlys dokumenterte service UUID og `0xFD00`
2. personvernvennlig visning av funn med hash-basert `probe_id`
3. eksplisitt GATT-read av standardfeltet Software Revision

Den gjør ingen proprietary writes og inneholder med hensikt ikke kommandoene
`0x57` eller `0x58`.

Domeneobjektet `FingerprintEnrollment` implementerer nå:

- slots `003–199`, reservert for brukerfinger i Nimlys offisielle video
- lokal veiviser med masterfinger og tre avlesninger
- 15 minutters session-timeout
- eksplisitt bekreftelse før event-verifisering
- verifisering bare ved fingerprint-kilde og eksakt forventet user slot
- cancel/expired som terminale tilstander
- kun UI-metadata; ingen master- eller biometridata

Home Assistant-integrasjonen implementerer i tillegg:

- config flow for ett eksakt Zigbee2MQTT device-topic per config entry
- actions for start, lokal bekreftelse og cancel
- MQTT-abonnement gjennom Home Assistants MQTT-API
- verifisering bare ved en faktisk `LOCKED → UNLOCKED`-overgang
- HA-eventet `nimly_fingerprint_enrollment_verified` med person, slot og kilde
- redigerte diagnostics uten rå MQTT-payload eller `last_used_pin_code`

Enrollment-sessionen lever foreløpig i minnet og utløper etter 15 minutter.
Omstart av Home Assistant avbryter derfor flyten; brukeren starter da en ny
session. Dette er bevisst tryggere enn å gjenoppta en uklar fysisk tilstand.

Offisiell visuell kilde:
[Programmering: Lägg till användarfinger](https://www.youtube.com/watch?v=-RwIQjeYIMs).

## Valgfri fremtidsresearch: fjernstart over BLE

Følgende må bevises før `0x57` eventuelt kan implementeres som en separat,
eksperimentell funksjon:

1. Låsen annonserer den dokumenterte BLE-tjenesten og standard firmwarefelt kan
   leses.
2. En ECDH-link kan etableres med P-256 og AES-128-CBC uten tilstandsendring.
3. `DeviceModelGet` (`0x62`) svarer med en fingerprint-kompatibel modell.
4. Owner authentication kan fullføres uten å logge eller lagre
   `deviceEncryptionKey`.
5. En capture fra offisiell app dokumenterer response/state-machine, slotvalg,
   antall fingerberøringer, timeout og cancel.

Bare deretter implementeres én eksplisitt `enroll`-kommando. Den skal:

- kreve at brukeren bekrefter at vedkommende står ved låsen
- ha hard timeout og lokal cancel
- aldri hente, transportere eller lagre en fingerprint-template
- aldri logge nøkler, challenges eller rå kryptert credential-data
- avvise ukjent modell og firmware

`FingerprintClear` er en destruktiv operasjon og skal ikke implementeres før
slot-semantikken er bevist separat.

## Neste fysiske kommando

```bash
uv run --extra ble nimly-ble-probe scan --timeout 15
uv run --extra ble nimly-ble-probe inspect <probe-id>
```

Hvis skanningen ikke finner låsen, vekk panelet fysisk og kontroller at
Bluetooth er aktivert for terminal-/Codex-prosessen. Ingen videre kommando skal
sendes tilfeldig eller ved fuzzing.

## Fysisk observasjon 2026-08-09

Proben ble kjørt mens Touch Pro-låsen ble låst opp og låst fysisk:

- macOS CoreBluetooth observerte 59 andre BLE-enheter, men ingen Nimly-service,
  `0xFD00` service-data eller Nimly/Onesti-navn
- to påfølgende 15-sekunders skanninger under fysisk betjening ga samme resultat
- Home Assistant rapporterte to aktive Bluetooth-adaptere og 75 observerte
  annonser, men ingen gjenkjennbar Nimly-node i visualiseringen
- Terminal-tillegget kunne liste BlueZ-cachede adresser, men hadde ikke tilgang
  til management-socket og kunne derfor ikke verifisere UUID-ene deres

Dette viser at proben og Bluetooth-tilgangen fungerer, men at Connect Module
ikke annonserer den reverserte BLE-tjenesten kontinuerlig i normal drift. Google Play-
beskrivelsen for den offisielle
[nimly BLE-appen](https://play.google.com/store/apps/details?id=easyaccess.ekey.app&hl=en)
oppgir støtte for både «Zigbee BLE Module» og «Connect Module». Neste test er
derfor å åpne **Add device / Legg til enhet** i den offisielle appen uten å
fullføre noen ny paring, og skanne samtidig. Dette kan avklare om annonseringen
aktiveres av appens discovery-flyt.

### Discovery fra offisiell app

Da **Add device / Legg til enhet** ble åpnet i den offisielle appen, fant proben
umiddelbart følgende anonymiserte enhet:

```json
{
  "probe_id": "nimly-0b992e98e01c",
  "name": "Dør",
  "rssi": -92,
  "matched_by": ["service_data"],
  "service_data_length": 10,
  "software_revision": "4.7.79"
}
```

Firmware ble lest fra standard Device Information Service. Ingen proprietary
write eller autentisering ble utført. Den observerte service-dataen er 10 bytes,
mens reverse-engineering-dokumentet beskriver en 8-byte identifikator. Proben
holder derfor verdien opak og redigert inntil packet capture forklarer de to
ekstra bytene.

Den dokumenterte minimumsversjonen for BLE-tilkobling er 4.6.0, men
`DeviceModelGet` og nyere credential-funksjoner er dokumentert fra 4.7.90.
Låsen kjører 4.7.79. Den offisielle appen viste ingen mulighet for oppgradering,
og samme versjon er rapportert som Connect Module-build `20240625` i
[`zigbee2mqtt#17205`](https://github.com/Koenkk/zigbee2mqtt/issues/17205).
Firmwaregrensen brukes derfor bare for de funksjonene den faktisk dokumenterer;
den blokkerer ikke videre fingerprint-research alene.

Neste port er en BLE HCI-capture fra den offisielle appens tilkoblingsflyt.
`ExchangeKeyPubM` har 64-byte payload, mens appen ber om MTU 23. Den publiserte
protokollreferansen beskriver `BlobStart`, `BlobStream` og `BlobComplete`, men
ikke fragmentenes wire-format. Vi skal ikke gjette dette eller sende tilfeldige
fragmenter til låsen. Capturen må vise fragmentering, command reference og
responseflyt før proben implementerer ECDH-linktesten.
