# Nimly Touch Pro: dagens protokollstøtte

Sist verifisert: 2026-08-09.

Dette dokumentet kartlegger hva som finnes i upstream-koden nå. Det skiller mellom:

1. hva Zigbee Door Lock-clusteret og `zigbee-herdsman` kan representere
2. hva `zigbee-herdsman-converters` gjør tilgjengelig via Zigbee2MQTT
3. hva Nimly-definisjonen faktisk kobler inn og eksponerer
4. hva som fortsatt må bekreftes mot en fysisk Nimly Touch Pro og Connect Module

Konklusjonen er at en nyttig Home Assistant-integrasjon kan bygges nå for lås,
batteri, hendelser, navngitte bruker-slots og PIN-opprettelse/-sletting. RFID- og
schedule-kommandoene finnes allerede i Herdsman, men mangler Z2M-convertere og er
ikke bevist støttet av den aktuelle låsen. Fingeravtrykk kan detekteres ved bruk,
men det finnes ingen enrollment- eller delete-API i den undersøkte stacken.

## Kildestatus og avgrensning

Kartleggingen er basert på følgende upstream-tilstand:

- [`onesti.ts` ved siste endring av filen](https://github.com/Koenkk/zigbee-herdsman-converters/blob/013ebd49b1e63da9ee527f850824ca04a6a26902/src/devices/onesti.ts)
- [`fromZigbee.ts`](https://github.com/Koenkk/zigbee-herdsman-converters/blob/32c9f0aedf53bcb9f52df7dec90fbf010b563356/src/converters/fromZigbee.ts)
- [`toZigbee.ts`](https://github.com/Koenkk/zigbee-herdsman-converters/blob/32c9f0aedf53bcb9f52df7dec90fbf010b563356/src/converters/toZigbee.ts)
- [`exposes.ts`](https://github.com/Koenkk/zigbee-herdsman-converters/blob/32c9f0aedf53bcb9f52df7dec90fbf010b563356/src/lib/exposes.ts)
- [`closuresDoorLock` i Herdsman](https://github.com/Koenkk/zigbee-herdsman/blob/135c2303646401b441f095436875c42ef847b739/src/zspec/zcl/definition/cluster.ts)
- GitHub-søk i `home-assistant/core` og HACS' standardkatalog

Den publiserte «E-life Zigbee Modul User Manual v2.0» er lenket fra
[`zigbee2mqtt#6379`](https://github.com/Koenkk/zigbee2mqtt/issues/6379), men GitHub-
vedlegget kunne ikke åpnes i den integrerte nettleseren. Påstander nedenfor er
derfor ikke basert på uverifisert innhold fra PDF-en.

## 1. Faktisk device definition

Det finnes to Onesti/Nimly-familier i samme fil.

### Legacy EasyAccess/EasyCodeTouch

| Felt | Verdi |
|---|---|
| `zigbeeModel` | `easyCodeTouch_v1`, `EasyCodeTouch`, `EasyFingerTouch` |
| Z2M `model` | `easyCodeTouch_v1` |
| `vendor` | `Onesti Products AS` |
| Beskrivelse | Zigbee-modul for EasyAccess code touch-serien |

### Nimly-familien

| Felt | Verdi |
|---|---|
| `zigbeeModel` | `NimlyPRO`, `NimlyCode`, `NimlyTouch`, `NimlyIn`, `NimlyPRO24`, `NimlyShared`, `NimlyCodePRO` |
| Z2M `model` | `Nimly` |
| `vendor` | `Onesti Products AS` |
| Beskrivelse | Zigbee-modul for Nimly-låsserien |

Definisjonen bruker bare `zigbeeModel`; den har ingen strengere `fingerprint`
med produsent, endpointliste eller `manufacturerID`. Det betyr at den konkrete
Touch Pro-enhetens rapporterte `modelID` må hentes fra
`zigbee2mqtt/bridge/devices`, ikke gjettes fra markedsnavnet.

### Endpoint, clusters og configure

Begge familiene bruker endpoint **11**.

`configure()` gjør følgende:

- binder `closuresDoorLock` og `genPowerCfg` til coordinator-endpointet
- setter rapportering for lock state
- setter rapportering for battery percentage remaining
- leser `lockState` og `soundVolume`
- setter power source til `Battery`

Legacy-familien forsøker i tillegg å lese Door Lock-attributtene:

- `0x0012` — antall støttede PIN-brukere
- `0x0017` — maksimal PIN-lengde
- `0x0018` — minimal PIN-lengde

Nimly-familien gjør ikke dette eksplisitte capability-readet, selv om feltene er
eksponert. Ingen av familiene leser RFID- eller schedule-capabilities under
configure.

Det finnes ingen `manufacturerCode`, ingen registrert private cluster og ingen
manufacturer-specific command i device definition. Logger i
[`zigbee2mqtt#17205`](https://github.com/Koenkk/zigbee2mqtt/issues/17205) viser
standard cluster `0x0101` på endpoint 11 og vanlige, ikke-manufacturer-specific
attribute reports. Dette beviser ikke at enheten ikke har andre/private clusters;
det krever device interview-data.

## 2. Convertere som Nimly bruker

### `fromZigbee`

Nimly-familien kobler inn:

- lokal `nimly_pro_lock_actions`
- generisk `lock`
- generisk `lock_operation_event`
- generisk `battery`
- generisk `lock_programming_event`
- lokal `easycodetouch_action`

Legacy-familien har i tillegg `lock_set_pin_code_response`.

Viktige detaljer:

- Attributt `0x0100` (256) tolkes lokalt som source, lock/unlock og 16-bit user ID.
- Source blir `zigbee`, `keypad`, `fingerprintsensor`, `rfid`, `self` eller
  `unknown`.
- Attributt `0x0101` (257) tolkes som de faktiske ASCII-sifrene som ble skrevet på
  tastaturet.
- Den rå EasyCodeTouch-eventtabellen har egne hendelser for keypad, manual, key,
  fingerprint, RFID og Zigbee.
- `lock_operation_event` dekoder standard operation event notification.
- `lock_programming_event` dekoder master-code change, PIN added/deleted/changed
  og RFID added/deleted.

Den generiske `lock_pin_code_response` og `lock_user_status_response` finnes i
converterbiblioteket, men er **ikke** koblet inn i Nimly-definisjonen. Derfor kan
Herdsman sende `getPinCode`, men dagens Nimly-oppsett publiserer ikke det svaret
som en brukerliste via Z2M.

### `toZigbee`

Begge familiene kobler inn:

- `lock`
- lokal `easycode_auto_relock`
- `lock_sound_volume`
- `pincode_lock`

Nimly kobler ikke inn den eksisterende generiske `lock_userstatus`-converteren.
Det finnes ingen converter for RFID, weekday schedule, year-day schedule,
holiday schedule eller log records i `zigbee-herdsman-converters` per denne
kartleggingen.

## 3. Alle aktuelle exposes

Begge familiene eksponerer:

| Property | Tilgang | Betydning |
|---|---:|---|
| `state` / `lock_state` | state/set/get | Lås og låsestatus |
| `battery` | state | Batteriprosent |
| `sound_volume` | state/set/get | `silent_mode`, `low_volume`, `high_volume` |
| `voltage` | state | Batterispenning dersom rapportert |
| `last_unlock_source` | state | Zigbee, keypad, fingerprint, RFID, self eller unknown |
| `last_unlock_user` | state | Numerisk slot som tekst |
| `last_lock_source` | state | Kilde for siste låsing |
| `last_lock_user` | state | Numerisk slot som tekst |
| `last_used_pin_code` | state | Faktiske tastede PIN-sifre |
| `auto_relock` | state/set | Skriver `autoRelockTime` som 1 eller 0 |
| `auto_relock_time` | state | Rapportert delay i sekunder |
| `max_pin_users` | state | Attributt `0x0012`, dersom lest/rapportert |
| `min_pin_length` | state | Attributt `0x0018`, dersom lest/rapportert |
| `max_pin_length` | state | Attributt `0x0017`, dersom lest/rapportert |
| `pin_code` | composite set/get | PIN-kommando med user, type, enabled og PIN |

Legacy-definisjonen eksponerer i tillegg tidsstempel for siste vellykkede
PIN-lagring og -sletting. Nimly-definisjonen gjør ikke det.

`pin_code.user_type` tillater verdiene `unrestricted`, `year_day_schedule`,
`week_day_schedule`, `master` og `non_access`. Dette setter bare user type i
`setPinCode`; det finnes ingen tidsfelter eller schedule-kommando i expose-et.

## 4. PIN-operasjoner

`pincode_lock` støtter følgende MQTT-shape:

```json
{
  "pin_code": {
    "user": 4,
    "user_type": "unrestricted",
    "user_enabled": true,
    "pin_code": 8472
  }
}
```

Converteren sender da standard `closuresDoorLock.setPinCode` med:

- `userid`
- `userstatus`: 1 for enabled eller 3 for disabled
- `usertype`: 0 unrestricted, 1 year-day, 2 week-day, 3 master, 4 non-access
- `pincodevalue` som tekst

Sletting skjer når `pin_code` er `null`; da sendes `clearPinCode` for valgt
`userid`.

`convertGet` kan sende `getPinCode` for én eller alle slots. Nimly har metadata
`pinCodeCount: 1000`, så et uavgrenset get forsøker 1000 kommandoer. Det bør ikke
brukes av Nimly Manager. I tillegg mangler Nimly den relevante fromZigbee-
converteren for å publisere svaret.

Fysiske brukerrapporter i [`zigbee2mqtt#17205`](https://github.com/Koenkk/zigbee2mqtt/issues/17205)
og testbeskrivelsen i [`zigbee-herdsman-converters#11332`](https://github.com/Koenkk/zigbee-herdsman-converters/pull/11332)
bekrefter at PIN set/delete og user-slot tracking virker på NimlyPRO-varianter.
Det finnes også rapporter om timeout/ustabilitet på enkelte firmware-/mesh-oppsett.

### Sikkerhetskonsekvens

Dagens converter publiserer `last_used_pin_code` i klartekst. Nimly Manager må:

- ignorere feltet ved ordinær state-modellering
- aldri opprette en entity for feltet
- redigere det fra diagnostics og logger
- unngå å abonnere videre eller persistére verdien når det er mulig
- behandle RFID-verdier tilsvarende

En senere upstream-forbedring bør vurdere å gjøre dette feltet opt-in eller fjerne
det, men det er utenfor denne research-leveransen.

## 5. RFID

RFID finnes allerede i Herdsmans standard Door Lock-definisjon:

| Kommando | ID |
|---|---:|
| `setRfidCode` | `0x16` |
| `getRfidCode` | `0x17` |
| `clearRfidCode` | `0x18` |
| `clearAllRfidCodes` | `0x19` |

Herdsman har også attributter for antall RFID-brukere og min/maks RFID-lengde,
samt response-definisjoner for alle fire kommandoene.

Det er likevel ingen RFID-converter i Z2M, og Nimly-definisjonen eksponerer ingen
RFID-management. Generic programming events kjenner eventkodene
`rfid_code_added` og `rfid_code_deleted`, og de Nimly-spesifikke eventene kan
rapportere at låsen ble brukt med RFID.

Dette betyr:

- RFID-bruk kan detekteres nå dersom låsen sender de observerte eventene.
- RFID-opprettelse/sletting krever en Z2M external converter.
- Før skriving må fysisk støtte bekreftes ved å lese capability-attributtene og
  teste en eksplisitt, kjent slot.

## 6. Fingeravtrykk

Det finnes to former for observerbar fingerprint-støtte:

- attributt 256 kan gi source `fingerprintsensor` og user slot
- rå Door Lock-events har `fingerprint_lock` og `fingerprint_unlock`

[`zigbee-herdsman-converters#11332`](https://github.com/Koenkk/zigbee-herdsman-converters/pull/11332)
oppgir fysisk test av fingerprint-unlock på flere NimlyPRO-låser.

Det finnes ingen `enrollFingerprint`, `deleteFingerprint`, `clearFingerprints`
eller tilsvarende kommando i Door Lock-definisjonen, Herdsman-koden eller
converterbiblioteket. Standard Door Lock-clusteret som er implementert her har
heller ingen fingerprint credential commands.

Konklusjon:

- fingerprint-detektering og user mapping kan bygges nå
- enrollment/delete er ukjent
- device interview, ukjente clusters og trafikk ved lokal enrollment må
  undersøkes før API-design
- ingen manufacturer-specific kommando må sendes uten forstått command-ID og
  payload

## 7. Event notifications

Herdsman implementerer server-til-klient-kommandoene:

- `operationEventNotification` (`0x20`)
- `programmingEventNotification` (`0x21`)

Operation events dekodes til blant annet lock/unlock, invalid PIN/ID, invalid
schedule, one-touch, key, auto-lock, scheduled lock/unlock og manual lock/unlock.
Publisert state inkluderer user ID, numerisk source og source name.

Programming events dekodes til master code changed, PIN added/deleted/changed og
RFID added/deleted.

Nimly kobler inn begge converterne. I tillegg brukes de Nimly-spesifikke
attributtene 256/257 og den rå action-tabellen. Integrasjonen må deduplisere
hendelser dersom samme fysiske handling kommer gjennom flere av disse rutene.

Eventpayloadene i Zigbee kan inneholde PIN/RFID-data. Z2M-converterne som er
koblet inn publiserer ikke `pin` fra standard event notification, men Nimlys
attributt 257 publiserer faktisk sist tastede PIN. Redigering er derfor obligatorisk.

## 8. Schedule support

Herdsman støtter wire-format og responses for:

- weekday schedule: set/get/clear (`0x0b`–`0x0d`)
- year-day schedule: set/get/clear (`0x0e`–`0x10`)
- holiday schedule: set/get/clear (`0x11`–`0x13`)
- user type: set/get (`0x14`–`0x15`)

`closuresDoorLock` har også capability-attributter for antall weekday-, year-day-
og holiday schedules.

Z2M mangler convertere og exposes for alle schedule-kommandoene. At `pin_code`
kan sette user type til weekday/year-day er ikke tilstrekkelig; selve tidsvinduet
blir ikke sendt.

Det er heller ikke verifisert at aktuell Nimly-firmware:

- rapporterer schedule-capability større enn null
- har korrekt Zigbee local time
- aksepterer schedule-kommandoene
- håndhever tidsvinduet offline

Native temporary access er derfor **REQUIRES PHYSICAL LOCK TEST** og en Z2M-
utvidelse, ikke `CAN BUILD NOW`.

## 9. Home Assistant og HACS

Det finnes ingen dedikert Nimly-integrasjon i `home-assistant/core` eller Nimly-
oppføring i HACS' standardkatalog ved søk på `Nimly`, `easyCodeTouch` og `Onesti`.

`home-assistant/core` har en eldre deCONZ-testfixture for en Onesti
`easyCodeTouch_v1`, men dette er testdata for den generiske deCONZ lock-
integrasjonen, ikke en Nimly Manager-integrasjon.

Dette støtter prosjektets valgte retning: en separat HACS-integrasjon over Home
Assistants MQTT-API, uten egen Zigbee-stack.

## 10. Relevante issues og PR-er

| Kilde | Betydning |
|---|---|
| [`zigbee2mqtt#6379`](https://github.com/Koenkk/zigbee2mqtt/issues/6379) | Opprinnelig E-Life/easyCodeTouch support request og protokollmanual |
| [`zigbee-herdsman-converters#4892`](https://github.com/Koenkk/zigbee-herdsman-converters/pull/4892) | La til `NimlyPRO` i Onesti-definisjonen |
| [`zigbee2mqtt#17205`](https://github.com/Koenkk/zigbee2mqtt/issues/17205) | Fysiske logger for fingerprint/RFID, PIN-eksempler og schedule-diskusjon |
| [`zigbee-herdsman-converters#6010`](https://github.com/Koenkk/zigbee-herdsman-converters/pull/6010) | La til parsing av Nimly-attributtene 256/257 og last source/user |
| [`zigbee-herdsman-converters#6043`](https://github.com/Koenkk/zigbee-herdsman-converters/issues/6043) | Dokumenterer `NimlyIn` model ID |
| [`zigbee-herdsman-converters#7237`](https://github.com/Koenkk/zigbee-herdsman-converters/pull/7237) | Opprettet egen Nimly-family definition |
| [`zigbee-herdsman-converters#9018`](https://github.com/Koenkk/zigbee-herdsman-converters/pull/9018) | La til PIN set/clear success-markører for legacy-modellen |
| [`zigbee-herdsman-converters#11332`](https://github.com/Koenkk/zigbee-herdsman-converters/pull/11332) | Rettet ASCII-PIN og user tracking; fysisk test på NimlyPRO |
| [`zigbee2mqtt#30704`](https://github.com/Koenkk/zigbee2mqtt/issues/30704) | Nyere batteriprosentproblem og firmware-/variantforskjeller |
| [`zha-device-handlers#2354`](https://github.com/zigpy/zha-device-handlers/issues/2354) | Relatert ZHA-device request; nyttig sammenligningsgrunnlag, ikke valgt transport |

## 11. Konkrete gaps

1. Ingen verifisert device interview for den konkrete Touch Pro/Connect Module.
2. Ingen capability-read for RFID og schedules i Nimly `configure()`.
3. Ingen Z2M RFID to/from-converter eller expose.
4. Ingen Z2M schedule to/from-converter eller expose.
5. `getPinCode` er tilgjengelig i Herdsman, men Nimly kobler ikke inn response-
   converteren.
6. `lock_userstatus` finnes generisk, men er ikke koblet inn i Nimly-definisjonen.
7. Ingen fingerprint enrollment/delete-kommando er funnet.
8. Klartekst-PIN publiseres som vanlig state.
9. Eventer kan dupliseres mellom standard notifications, rå events og attributt
   256.
10. `pinCodeCount: 1000` gjør «get all PINs» uegnet og potensielt belastende.
11. Capability-modellen må være runtime-basert; modellnavn alene er utilstrekkelig.

## 12. Anbefalt første eksperiment

Første eksperiment skal være **read-only capability discovery**, ikke RFID-write.

Lag i milestone 3 et MQTT-verktøy som:

1. leser `zigbee2mqtt/bridge/devices`
2. finner den konkrete Nimly-enheten og endpoint 11
3. skriver ut alle input/output clusters og eventuelt ukjente clusters
4. leser følgende `closuresDoorLock`-attributter med en lokal external converter:
   - `0x0010` lock records
   - `0x0011` total users
   - `0x0012` PIN users
   - `0x0013` RFID users
   - `0x0014` weekday schedules per user
   - `0x0015` year-day schedules per user
   - `0x0016` holiday schedules
   - `0x0017`/`0x0018` PIN max/min
   - `0x0019`/`0x001a` RFID max/min
5. aldri logger credential-verdier

Hvis RFID-count er større enn null, er neste trygge steg `getRfidCode` mot én
eksplisitt kjent eller ledig slot, med full redigering av response. Først etter
det bør `setRfidCode` testes mot en fysisk lås og en bevisst valgt test-slot.

## Beslutningsmatrise

| Feature | Status | Begrunnelse |
|---|---|---|
| Lock/unlock | **CAN BUILD NOW** | Z2M `lock` er koblet inn og eksponert |
| Battery/voltage | **CAN BUILD NOW** | State og reporting finnes; variantforskjeller må tåles |
| User-slot til navn | **CAN BUILD NOW** | `last_*_user` finnes som numerisk slot |
| PIN create | **CAN BUILD NOW** | `setPinCode` er koblet inn og fysisk bekreftet |
| PIN delete | **CAN BUILD NOW** | `clearPinCode` er koblet inn og fysisk bekreftet, men timeout må håndteres |
| PIN read/list | **REQUIRES Z2M EXTENSION** | Herdsman og generic fz støtter det, Nimly kobler ikke inn response-converteren |
| Enable/disable eksisterende bruker | **REQUIRES Z2M EXTENSION** | Generic converter finnes, men er ikke koblet inn; PIN-set kan ikke brukes blindt |
| Lock/RFID/fingerprint event detection | **CAN BUILD NOW** | Standard og Nimly-spesifikke eventkilder finnes |
| RFID add/delete event | **CAN BUILD NOW**, fysisk verifikasjon anbefalt | Generic programming event kjenner eventkodene |
| RFID create/read/delete | **REQUIRES Z2M EXTENSION** + **PHYSICAL LOCK TEST** | Herdsman har kommandoene; Z2M/Nimly expose mangler |
| Native weekday schedule | **REQUIRES Z2M EXTENSION** + **PHYSICAL LOCK TEST** | Herdsman har wire-format; capability og tidsføring er ukjent |
| Native year-day schedule | **REQUIRES Z2M EXTENSION** + **PHYSICAL LOCK TEST** | Samme gap som weekday |
| HA-basert temporary access fallback | **CAN BUILD NOW**, men ikke offline-sikkert | Kan set/clear PIN via automasjon |
| Fingerprint detection/user mapping | **CAN BUILD NOW** | Fysisk testet event/source og slot |
| Fingerprint enrollment/delete | **REQUIRES PHYSICAL LOCK TEST** | Ingen API funnet; må undersøke descriptors/private trafikk |
| Historical lock log | **REQUIRES Z2M EXTENSION** + **PHYSICAL LOCK TEST** | `getLogRecord` finnes i Herdsman, men ingen converter/expose |
