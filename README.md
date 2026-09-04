# Rodičovský dohľad so zdieľaným časom

Jeden denný rozpočet obrazovkového času pre **tablet** (Android, Google Family
Link) a **Windows PC** dokopy. Keď Simonka odsedí hodinu na tablete, na PC jej
zostanú dve — a naopak. Ovláda sa z Telegramu, rozvrh zostáva vo Family Link.

## Ako to funguje

Jediný účet vedie Home Assistant. Obe zariadenia sú len spotrebitelia jedného
čísla a každé si svoj strop vynucuje samo:

```
              rozvrh Family Link (koľko hodín na dnešný deň)
                              │
                    00:05 ─── ▼ ────────────────────────┐
                    input_number.simona_rozpocet_dnes = R│
                              │                          │
        ┌─────────────────────┴──────────────────────┐   │
        ▼                                            ▼   │
  FL denný limit                              povolené na PC
  tabletu := R − pc                           := R + bonus − tablet
        │                                            │
        ▼                                            ▼
  Family Link zamkne tablet              agent len varuje hlasom
  keď ho tablet vyčerpá                  a hlási spotrebu — PC beží
        │                                            │
        └──────────► skutočná spotreba ◄─────────────┘
                 tablet: sensor.iplay_50_…used_minutes
                 pc:     agent hlási každú minútu
```

Prepočet beží každú minútu, takže keď hrá na oboch zariadeniach naraz, obom sa
strop priebežne uťahuje a odchýlka je nanajvýš minúta či dve.

### Prečo takto a nie inak

Family Link **nemá verejné API**, ale integrácia
[noiwid/HAFamilyLink](https://github.com/noiwid/HAFamilyLink) hovorí s tými
istými internými endpointmi ako appka. Kľúčové je, že `familylink.set_daily_limit`
posiela `timeLimitOverrides:batchCreate` — teda **override na dnešný deň**, nie
prepis týždenného rozvrhu. Rozvrh tak môže zostať zdrojom pravdy a my ho len
dennodenne prepisujeme. Pre istotu ho o 23:57 vraciame na pôvodnú hodnotu, aby
po nás v Google nezostal žiadny override.

## Entity

| Entita | Význam |
|---|---|
| `input_number.simona_rozpocet_dnes` | Rozpočet na dnes (R) v minútach. O 00:05 sa preberá z rozvrhu Family Link. |
| `input_number.simona_pc_pouzite` | Minúty odsedené dnes pri PC. Plní agent. |
| `input_boolean.simona_zdielany_cas` | Hlavný vypínač. Keď je `off`, HA nezasahuje do ničoho. |
| `input_datetime.simona_pc_kontakt` | Posledné úspešné spojenie s agentom. |
| `sensor.simona_tablet_pouzite` | Minúty na tablete (čítané z Family Link). |
| `sensor.simona_rozpocet_celkom` | R + bonus pridaný v aplikácii Family Link. |
| `sensor.simona_cas_pouzity` | Spolu tablet + PC (atribúty `tablet`, `pc`). |
| `sensor.simona_cas_zostava` | Koľko z rozpočtu ešte zostáva. |
| `sensor.simona_tablet_cielovy_limit` | Strop, ktorý sa zapisuje do Family Link. |
| `sensor.simona_pc_povolene` | Koľko celkovo smie dnes odsedieť pri PC. |
| `binary_sensor.simona_pc_online` | Či sa agent ohlásil za posledných 5 minút. |

## Ovládanie z Telegramu

V menu **Simonka PC** je nová položka „🤝 Spoločný čas" s prehľadom a tlačidlami.
Píše sa aj priamo:

| Príkaz | Čo urobí |
|---|---|
| `/cas` | Prehľad: rozpočet, spotreba po zariadeniach, zostatok, stav PC. |
| `/cas_add 30` | Pridá 30 min do dnešného rozpočtu (platí pre obe zariadenia). |
| `/cas_set 120` | Nastaví dnešný rozpočet na 120 min. |
| `/cas_stop` | Ukončí čas hneď — rozpočet zroluje na už spotrebované, tablet sa zamkne. |
| `/cas_pauza`, `/cas_start` | Vypne / zapne zdieľanie (kým je vypnuté, HA nezasahuje). |

Prístup majú len chaty Jakub (`5756450012`) a Mama (`8413756301`), rovnako ako
pri ostatných automatizáciách.

Rodičia dostanú upozornenie pri **30**, **10** a **0** zostávajúcich minútach.

### PC sa nikdy neblokuje

Počítač sa po vyčerpaní času **nezamyká, neuspáva ani nevypína** — Simonka sa
má vedieť zastaviť sama. Agent ju len upozorní hlasom a textom, koľko jej
zostáva, a po nule už nespraví nič.

Keď si po vyčerpanom čase k PC sadne, dozvieš sa o tom:

- **prekrytie na TV** (`notify.tvoverlaynotify`) — posiela sa vždy, aj keď je TV vypnutá,
- **správa do Telegramu** Jakubovi.

Kým pri ňom sedí, pripomenie sa najviac raz za pol hodinu. Minúty nad rámec
rozpočtu sa rátajú ďalej, takže v `/cas` je vidieť, o koľko limit prekročila —
a zajtrajší rozpočet tým nie je dotknutý.

## Dashboard v Home Assistante

V bočnom paneli je **Simonka** (`/simonka-cas`) — samostatný dashboard so
štyrmi sekciami: prehľad spoločného času, rýchle akcie, tablet a počítač.

Zámerne to nie je view v hlavnom *Prehľade* — ten má 205 kB konfigurácie a
nemá zmysel ho kvôli tomuto prepisovať. Samostatný dashboard nemôže nič
existujúce rozbiť.

Tlačidlá volajú skripty (`simona_cas_pridaj`, `simona_cas_nastav`,
`simona_cas_ukonci`, `simona_pc_prikaz`), lebo karta typu *button* nevie
odovzdať parameter priamo do `input_number.set_value`.

## Súbory

| Súbor | Kam patrí |
|---|---|
| `ha/packages/simona_cas.yaml` | `/config/packages/` — účtovanie, prepočty, synchronizácia s Family Link, skripty pre dashboard |
| `ha/packages/simona_cas_telegram.yaml` | `/config/packages/` — Telegram prehľad a tlačidlá |
| `ha/dashboard/simonka-cas.yaml` | obsah dashboardu (surový editor konfigurácie) |
| `agent/` | Windows agent (viď `docs/AGENT.md`) |

Do existujúceho `packages/pc_control.yaml` bola pridaná jediná vec — položka
menu, v oboch blokoch, kde sa hlavné menu skladá:

```yaml
- "🤝 Spoločný čas:/pct_main"
```

Token agenta je v `secrets.yaml` ako `pc_agent_token`.

## Na čo si dať pozor

- **Denný limit musí byť vo Family Link zapnutý** (`switch.simona_fabriciova_daily_limit`).
  Keď je vypnutý, Google nič nevynucuje a strop tabletu je len číslo.
- **Chromecast HD je mimo rozpočtu** — má vo Family Link vlastný limit.
  Pozeranie Jellyfinu na TV teda čas na tablete ani na PC neujedá.
- **Bonus dávaj cez Telegram**, nie v aplikácii Family Link. Cez Telegram sa
  pridá do spoločného rozpočtu; bonus z appky sa síce tiež započíta
  (`sensor.iplay_50_active_bonus`), ale platí len pre tablet.
- **Keď je PC vypnutý**, HA sa naň pýta raz za päť minút a posledná známa
  spotreba ostáva platiť. Vypnutím PC sa teda čas nedá „vrátiť".
- **Keď Family Link nedá dáta**, systém úmyselne nerobí nič — radšej žiadny
  zásah než omylom nastavený limit 0.
