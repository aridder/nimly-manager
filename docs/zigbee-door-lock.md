# Zigbee Door Lock (`closuresDoorLock`) for Nimly

Sist verifisert: 2026-08-09.

Dette dokumentet er den tekniske matrisen for milestone 2. Hovedkonklusjoner og
Nimly-spesifikke beslutninger står i
[`protocol-current-state.md`](./protocol-current-state.md).

Kilde for wire-formatet er Herdsmans runtime-definisjon av cluster
[`0x0101`](https://github.com/Koenkk/zigbee-herdsman/blob/135c2303646401b441f095436875c42ef847b739/src/zspec/zcl/definition/cluster.ts).

## Capability-attributter

| ID | Herdsman-navn | Type | Relevans |
|---:|---|---|---|
| `0x0000` | `lockState` | enum8 | Låst/ulåst/not fully locked |
| `0x0001` | `lockType` | enum8 | Låstype |
| `0x0002` | `actuatorEnabled` | boolean | Om aktuatoren er aktiv |
| `0x0003` | `doorState` | enum8 | Dørstatus dersom støttet |
| `0x0010` | `numOfLockRecordsSupported` | uint16 | Historisk loggkapasitet |
| `0x0011` | `numOfTotalUsersSupported` | uint16 | Totalt antall users |
| `0x0012` | `numOfPinUsersSupported` | uint16 | PIN-slots |
| `0x0013` | `numOfRfidUsersSupported` | uint16 | RFID-slots |
| `0x0014` | `numOfWeekDaySchedulesSupportedPerUser` | uint8 | Weekday schedules per user |
| `0x0015` | `numOfYearDaySchedulesSupportedPerUser` | uint8 | Year-day schedules per user |
| `0x0016` | `numOfHolidayScheduledsSupported` | uint8 | Holiday schedules |
| `0x0017` | `maxPinLen` | uint8 | Maks PIN-lengde |
| `0x0018` | `minPinLen` | uint8 | Min PIN-lengde |
| `0x0019` | `maxRfidLen` | uint8 | Maks RFID credential-lengde |
| `0x001a` | `minRfidLen` | uint8 | Min RFID credential-lengde |
| `0x0020` | `enableLogging` | boolean | Aktiver logg, dersom støttet |
| `0x0023` | `autoRelockTime` | uint32 | Auto-relock; 0 betyr disabled |
| `0x0024` | `soundVolume` | uint8 | Lydnivå |
| `0x0025` | `operatingMode` | enum8 | Aktiv driftsmodus |
| `0x0026` | `supportedOperatingModes` | bitmap16 | Støttede driftsmodi |
| `0x0028` | `enableLocalProgramming` | boolean | Lokal programmering |
| `0x0030` | `wrongCodeEntryLimit` | uint8 | Grense for feil kode |
| `0x0031` | `userCodeTemporaryDisableTime` | uint8 | Midlertidig sperretid |
| `0x0032` | `sendPinOta` | boolean | Om PIN kan sendes OTA |
| `0x0033` | `requirePinForRfOperation` | boolean | PIN-krav ved RF-operasjon |
| `0x0041`–`0x0044` | operation event masks | bitmap16 | Keypad/RF/manual/RFID events |
| `0x0045`–`0x0047` | programming event masks | bitmap16 | Keypad/RF/RFID programming events |

Nimly leser i dag bare `lockState`, `soundVolume` og, for legacy-modellen,
`0x0012`, `0x0017` og `0x0018`. Resten må capability-detekteres.

## Klient-til-server-kommandoer

«Herdsman» betyr at command og response wire-format finnes. «Generisk Z2M» betyr
at en converter finnes et sted i converterbiblioteket. «Nimly» betyr at den er
koblet inn i dagens Onesti/Nimly device definition.

| ID | Kommando | Herdsman | Generisk Z2M | Nimly koblet inn | Nimly expose |
|---:|---|:---:|:---:|:---:|:---:|
| `0x00` | `lockDoor` | ja | ja, `lock` | ja | ja |
| `0x01` | `unlockDoor` | ja | ja, `lock` | ja | ja |
| `0x02` | `toggleDoor` | ja | nei | nei | nei |
| `0x03` | `unlockWithTimeout` | ja | nei | nei | nei |
| `0x04` | `getLogRecord` | ja | nei | nei | nei |
| `0x05` | `setPinCode` | ja | ja, `pincode_lock` | ja | ja |
| `0x06` | `getPinCode` | ja | ja, `pincode_lock` | delvis | composite har get, men response fz mangler |
| `0x07` | `clearPinCode` | ja | ja, `pincode_lock` | ja | ja, `pin_code: null` |
| `0x08` | `clearAllPinCodes` | ja | nei | nei | nei |
| `0x09` | `setUserStatus` | ja | ja, `lock_userstatus` | nei | nei |
| `0x0a` | `getUserStatus` | ja | ja, `lock_userstatus` | nei | nei |
| `0x0b` | `setWeekDaySchedule` | ja | nei | nei | nei |
| `0x0c` | `getWeekDaySchedule` | ja | nei | nei | nei |
| `0x0d` | `clearWeekDaySchedule` | ja | nei | nei | nei |
| `0x0e` | `setYearDaySchedule` | ja | nei | nei | nei |
| `0x0f` | `getYearDaySchedule` | ja | nei | nei | nei |
| `0x10` | `clearYearDaySchedule` | ja | nei | nei | nei |
| `0x11` | `setHolidaySchedule` | ja | nei | nei | nei |
| `0x12` | `getHolidaySchedule` | ja | nei | nei | nei |
| `0x13` | `clearHolidaySchedule` | ja | nei | nei | nei |
| `0x14` | `setUserType` | ja | nei | nei | nei |
| `0x15` | `getUserType` | ja | nei | nei | nei |
| `0x16` | `setRfidCode` | ja | nei | nei | nei |
| `0x17` | `getRfidCode` | ja | nei | nei | nei |
| `0x18` | `clearRfidCode` | ja | nei | nei | nei |
| `0x19` | `clearAllRfidCodes` | ja | nei | nei | nei |

## Viktige payloads

### PIN og RFID

PIN og RFID har samme felttyper i Herdsman:

- `userid`: uint16
- `userstatus`: uint8
- `usertype`: enum8
- credential value: Zigbee octet string

Herdsman kaller RFID-feltet `pincodevalue` av hensyn til ZCL-definisjonen. En
eventuell Nimly external converter bør eksponere det som `rfid_code`, men ikke
endre wire-feltnavnet.

### Weekday schedule

- `scheduleid`: uint8
- `userid`: uint16
- `daysmask`: bitmap8
- start hour/minute
- end hour/minute

### Year-day schedule

- `scheduleid`: uint8
- `userid`: uint16
- `zigbeelocalstarttime`: uint32
- `zigbeelocalendtime`: uint32

Dette forutsetter at låsens Zigbee local time er korrekt. Ingen slik tidsflyt er
verifisert for Nimly.

## Server-til-klient-events

| ID | Kommando | Payload | Z2M converter | Nimly koblet inn |
|---:|---|---|:---:|:---:|
| `0x20` | `operationEventNotification` | source, event code, user ID, PIN, local time, data | ja | ja |
| `0x21` | `programmingEventNotification` | source, event code, user ID, PIN, user type/status, local time, data | ja | ja |

Z2M publiserer ikke credential-feltet fra disse to converterne. Nimlys separate
attributt 257 publiserer likevel den sist tastede PIN-en i klartekst.

### Operation event codes som Z2M dekoder

- unknown
- lock / unlock
- lock/unlock failure: invalid PIN or ID
- lock/unlock failure: invalid schedule
- one-touch lock
- key lock/unlock
- auto lock
- scheduled lock/unlock
- manual lock/unlock
- non-access user operational event

### Programming event codes som Z2M dekoder

- unknown
- master code changed
- PIN added/deleted/changed
- RFID added/deleted

## User status og user type

Z2M mapper user status slik:

| Verdi | Status |
|---:|---|
| 0 | `available` |
| 1 | `enabled` |
| 3 | `disabled` |

`pincode_lock` mapper user type slik:

| Verdi | Type |
|---:|---|
| 0 | `unrestricted` |
| 1 | `year_day_schedule` |
| 2 | `week_day_schedule` |
| 3 | `master` |
| 4 | `non_access` |

Å sette type 1 eller 2 oppretter ikke et tidsvindu. Det markerer bare hvilken
schedule-modell brukeren skal følge; schedule-kommandoene må sendes separat.

## Funksjonsmatrise

| Funksjon | Zigbee Door Lock/Herdsman | Z2M converter | Nimly expose | Beslutning |
|---|:---:|:---:|:---:|---|
| Lock | ja | ja | ja | CAN BUILD NOW |
| Unlock | ja | ja | ja | CAN BUILD NOW |
| User slot i events | ja | ja | ja | CAN BUILD NOW |
| User status set/get | ja | ja | nei | REQUIRES Z2M EXTENSION |
| PIN create | ja | ja | ja | CAN BUILD NOW |
| PIN delete | ja | ja | ja | CAN BUILD NOW |
| PIN read | ja | ja | delvis | REQUIRES Z2M WIRING; unngå secret exposure |
| Clear all PINs | ja | nei | nei | Ikke prioritert; farlig masseoperasjon |
| Weekday schedule | ja | nei | nei | EXTENSION + PHYSICAL TEST |
| Year-day schedule | ja | nei | nei | EXTENSION + PHYSICAL TEST |
| Holiday schedule | ja | nei | nei | EXTENSION + PHYSICAL TEST |
| RFID create/read/delete | ja | nei | nei | EXTENSION + PHYSICAL TEST |
| RFID add/delete event | ja | ja | action-event | CAN BUILD NOW, verifiser fysisk |
| Fingerprint use event | ikke egen credential-kommando | Nimly-spesifikk parsing | ja | CAN BUILD NOW |
| Fingerprint enrollment/delete | nei | nei | nei | UNKNOWN; PHYSICAL/PROTOCOL RESEARCH |
| Historical event log | ja | nei | nei | EXTENSION + PHYSICAL TEST |

## Første upstream-hypotese

Første upstream-bidrag bør ikke være Home Assistant-kode. Etter read-only
capability discovery bør en local external converter bevise én avgrenset flyt:

1. les RFID-capabilities
2. les status for én eksplisitt slot uten å logge credential
3. hvis låsen svarer korrekt, set/clear én test-RFID med response-status
4. legg til convertertester og redigering av credential-data
5. flytt funksjonen til `zigbee-herdsman-converters`

Samme mønster kan senere brukes for schedules, men bare etter at local time og
offline-håndheving er bevist på den fysiske låsen.
