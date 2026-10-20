# Fingeravtrykk-enrollment: beslutning og sikker testplan

Sist verifisert: 2026-10-20.

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

Siden august har [onesti-lock](https://github.com/fredrik-lindseth/onesti-lock)
(oppdatert 2026-10-18) dekodet hele BLE-eier-flyten statisk fra den offisielle
appen, og lagt ved et Python-BLE-bibliotek under
`custom_components/onesti_lock/ble/` — **ikke koblet inn og aldri kjørt mot en
lås**. Det betyr at en HCI-capture ikke lenger er nødvendig for å *oppdage*
protokollen; den er nå bare *validering* av en allerede dokumentert flyt. Vi
gjengir ikke protokollen her — se onesti-lock sine notater for mekanikken:

- nøkkelutveksling, pakkeformat og AES-128-CBC-laget:
  [`ble-protocol.md`](https://github.com/fredrik-lindseth/onesti-lock/blob/main/docs/nimly-ble-app/ble-protocol.md)
- lokal eier-enrollment uten sky (ECDH-avledet eiernøkkel, standardnøkkel på
  fabrikkresatt lås):
  [`ble-auth-provisioning.md`](https://github.com/fredrik-lindseth/onesti-lock/blob/main/docs/nimly-ble-app/ble-auth-provisioning.md)

Følgende må bevises mot *vår* lås før `0x57` eventuelt kan implementeres som en
separat, eksperimentell funksjon:

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

## Fysisk observasjon 2026-10-20: ny Connect Module

En nyere Connect Module er montert, og BLE-tilstanden er nå lest fra HAs egen
Bluetooth-diagnostikk.

- **Firmware 4.8.03.** Over den dokumenterte 4.7.90-grensen for `DeviceModelGet`
  og admin-kommandoene, inkludert `FingerprintScan` (`0x57`). `firmware.py`
  rapporterer nå `fingerprint_scan_command_documented: true` for denne
  versjonen, men holder `fingerprint_enrollment: "unverified"` — at kommandoen
  er dokumentert er ikke det samme som at enrollment er bevist mot maskinvare.
- **Vindu-bare annonsering, ikke kontinuerlig.** I steady state så *ingen* av
  HAs to adaptere (ASUS USB-BT500 og den Pi-interne) `0xFD00` — 95–101 enheter
  i historikken, ingen Nimly. Først etter et batteriuttak dukket låsen opp på
  **begge** adapterne innen sekunder, på ~−98 dBm. Det motbeviser antakelsen om
  at modulen annonserer hele tiden, og mønsteret (bare i ~4-minutters
  pairing-vinduet etter power-cycle) er nettopp onesti-lock sitt tegn på en
  **u-enrollet** modul. (Modulen annonserer som «Nimly»; augustmodulen som
  «Dør», et `DeviceNameSet`-navn. Fabrikknavnet er `GlennI`, så navnet avgjør
  ingenting — seeden gjør det.)
- **Seed `00 00` → factory.** Service-dataen var 10 byte med strukturen
  `00 00` | `<6-byte id>` | `00 00`: seed, identifikator, og to etterfølgende
  null-byte. Identifikatoren viste seg å være låsens egen BLE-adresse reversert
  (verifisert mot annonse-adressen), akkurat slik onesti beskriver en u-enrollet
  lås. Vendor-appens egen parser leser seed som de to første bytene, og bare
  `[seed][id][trailer]`-layouten lar appen kjenne igjen sine egne enrollede
  låser — så seeden står trygt på offset 0. `advertisement.py` klassifiserer nå
  dette som `factory` og rapporterer `identifier_matches_address`.
  (De rå id-bytene er låsens BLE-adresse og holdes utenfor repoet.)

**Konsekvens:** vi er på `factory`-veien. Lokal eier-enrollment er mulig **uten**
factory reset, og Zigbee-paringen forblir urørt. Men så lenge modulen er
u-enrollet annonserer den bare i pairing-vinduet, så **hver BLE-operasjon må
innledes med et batteriuttak** til enrollment er gjort. Etter enrollment
annonserer modulen formodentlig kontinuerlig (onesti sitt «presumably» — ikke
bevist).

To ting gjenstår før HA kan sende kommandoer:

1. **Signalstyrke.** ~−98 dBm på begge adaptere, fortsatt helt i grensen. Å
   sende kommandoer trygt krever en Bluetooth-proxy nær døra (ESP32 med ESPHome,
   `bluetooth_proxy` med `active: true`).
2. **Eierinnlogging.** Ingen har kjørt onesti-lock sin eier-auth mot en fysisk
   lås ennå. Vår første test vil være den aller første maskinvaretesten av den
   flyten. Ingen proprietær write sendes i denne omgang; klassifiseringen er
   avklart, men selve hardware-testen er en egen, bevisst økt med proxyen på
   plass.

### Beslutningstre: trenger vi factory reset?

Dette erstatter den gamle «HCI-capture først»-planen. Den avgjørende lesningen
er de to første bytene (seed) i `0xFD00`-service-dataen, slik onesti-lock leser
den (`[seed: 2B][identifier: 6B]`). `advertisement.py` rapporterer nå
`enrollment_state` fra denne seeden, og nekter å gjette når den observerte
10-byte-varianten gir tvetydig seed-offset (`ambiguous`).

| `enrollment_state` | Betydning | Vei videre |
|---|---|---|
| `factory` (seed `00 00`) | Aldri enrolled over BLE; standard eiernøkkel forventes å åpne | Lokal eier-enrollment uten reset. Zigbee urørt. Laveste risiko. At standardnøkkelen godtas på gjeldende firmware er dokumentert, men utestet mot lås. |
| `enrolled` (seed ≠ `00 00`) **og** låsen finnes i brukerens egen Nimly BLE-app | Enrolled gjennom app + sky | HA kan autentisere som med-eier **uten** reset: eiernøkkel og device-id hentes fra brukerens egen sky-konto ved reconnect (`LockCredentialDto` / `Credentials`-endepunktet i onesti-notatene). Engangs-bootstrap utenfor ordinær flyt, se under. |
| `enrolled` men **ikke** i noen app | Enrolled, men nøkkelen er utilgjengelig | Modul-reset (knapp, ~15 s — dropper Zigbee-paringen) → ny Zigbee-paring → deretter som `factory`. |
| `ambiguous` / `unknown` | 10-byte-layout ikke avklart, eller ingen service-data lest | Ikke beslutt. Skaff en rå advertisement-capture (se under) og avklar byteordenen før noe sendes. |

Faren ved reset: modul-reset dropper Zigbee-paringen, og hele dagens
nimly-manager-integrasjon går over Zigbee2MQTT. `factory`- og med-eier-veiene
unngår dette helt.

Forholdet til produktbeslutningen over: den sier at Nimly Manager *i den
ordinære flyten* ikke skal kreve Nimly-konto-/appnøkler. Med-eier-veien bryter
ikke dette — den er en **engangs-bootstrap utenfor ordinær flyt**. Brukeren
logger inn mot et udokumentert reverse-engineert API (`POST /User/Login`,
password grant) én gang, HA lagrer eiernøkkelen lokalt, og skyen røres aldri
igjen i daglig drift. Hvis brukeren heller velger `factory`-veien, trengs ingen
sky i det hele tatt.

### Arkitekturnotat: proben er ikke produksjonstransporten

`nimly-ble-probe` er macOS/CoreBluetooth-forskningsverktøy for å lese seed og
firmware fra en maskin nær døra. Produksjons-BLE i integrasjonen må gå gjennom
Home Assistants egen `bluetooth`-integrasjon, slik at ESPHome-proxyen faktisk
kan brukes som transport. Proben og integrasjonen deler protokollforståelse,
men ikke BLE-stack.

### To ting bare brukeren kan gjøre

1. **Les seeden.** Enten:
   - gi appen som kjører terminalen Bluetooth-tilgang (System Settings →
     Personvern og sikkerhet → Bluetooth), og kjør
     `uv run --extra ble nimly-ble-probe scan --reveal-identifiers` fra et sted
     nær døra; macOS-proben avbryter (exit 134) uten denne tilgangen, eller
   - hent rå advertisement-bytes fra HAs Bluetooth-integrasjon sin diagnostikk
     (ingen proxy nødvendig for seed-sjekken).
2. **Bekreft app-status.** Ble den nye modulen noen gang lagt til i den
   offisielle Nimly BLE-appen? Det avgjør `enrolled`-raden over.
