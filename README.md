# Rodičovský dohľad so zdieľaným časom

Jeden denný rozpočet obrazovkového času pre **tablet** (Android, Google Family
Link) a **Windows PC** dokopy. Keď Simonka odsedí hodinu na tablete, na PC jej
zostanú dve — a naopak. Ovláda sa z Telegramu; týždenný rozvrh je v Home
Assistante ako kópia toho z Family Link (viac nižšie).

## Ako to funguje

Jediný účet vedie Home Assistant. Obe zariadenia sú len spotrebitelia jedného
čísla a každé si svoj strop vynucuje samo:

```
        týždenný rozvrh v HA (input_number.simona_rozvrh_po … _ne)
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
  Family Link zamkne tablet              agent varuje hlasom; po nule
  keď ho tablet vyčerpá                  HA počítač raz vypne
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
prepis týždenného rozvrhu. Týždenný rozvrh v Google tak zostáva nedotknutý a my
doňho len denne píšeme výnimku. O 23:57 ju vraciame na hodnotu rozvrhu, aby po
nás nezostal žiadny override.

### Rozvrh je v HA, nie vo Family Link

Týždenný rozvrh sa z Family Link **prečítať nedá**. Integrácia sprístupňuje len
`appliedTimeLimits`, teda limit platný na dnešný deň — a v tom je už započítaný
náš vlastný override. `sensor.iplay_50_daily_limit` teda neukazuje rozvrh, ale
to, čo sme tam sami zapísali. (V zdrojáku integrácie existuje
`parse_daily_limit_schedule`, ale nikto ju nevolá — je to mŕtvy kód.)

Pôvodne si polnočný reset bral rozpočet práve odtiaľ, a tým si čítal vlastný
včerajší zvyšok. Rozpočet sa preto deň po dni scvrkával: **180 → 75 → 61**.
Bola to chyba návrhu na našej strane, nie Family Linku.

Rozvrh preto držíme v HA ako sedem helperov `input_number.simona_rozvrh_po`
… `_ne`. Nastavené sú podľa rozvrhu v aplikácii:

| Deň | Minút |
|---|---:|
| pondelok – piatok | 60 |
| sobota, nedeľa | 180 |

`sensor.simona_rozvrh_dnes` z nich vyberie dnešnú hodnotu (atribúty `den` a
`zajtra`), o 00:05 sa ňou naplní rozpočet a o 23:57 sa ňou prepíše aj limit vo
Family Link.

### Zmena v aplikácii sa preberie sama

Keď zmeníš denný limit priamo v aplikácii Family Link, HA to prevezme —
prepíše si tým rozpočet na dnes **aj** hodnotu rozvrhu na dnešný deň, a pošle
ti o tom správu do Telegramu. Kópia v HA tak zostáva verná.

Háčik je v tom, že do `sensor.iplay_50_daily_limit` píšeme aj my sami:
`familylink.set_daily_limit` si po zápise hneď vyžiada refresh koordinátora,
takže **každý náš zápis sa do toho senzora o pár sekúnd vráti** ako „zmena".
Pri 30-sekundovom pollingu by slepé preberanie znamenalo, že si každú minútu
prečítame vlastný odpočet — tá istá degradácia ako predtým, len 30× rýchlejšie.

Preto si posledných päť hodnôt, ktoré sme do Family Link zapísali, pamätáme v
`input_text.simona_fl_zapisane` a preberáme len takú zmenu, ktorá sa **ani
jednej z nich nerovná** — teda tú, ktorú urobil rodič.

Ďalšie poistky v `simona_cas_fl_zmena`:

- prechody cez `unknown` / `unavailable` (reštart HA, výpadok Google) sa
  ignorujú,
- **nula sa neberie** — chodí aj z nočného a školského režimu,
- kým je tablet zamknutý ručne, Family Link zmeny neprijíma a hlási neaktuálne
  čísla, tak sa vtedy nepreberá nič.

Medzi **00:00 a 00:10** do Family Link zámerne nezapisujeme: práve vtedy sa v
ňom objaví rozvrh na nový deň a náš zápis by ho prepísal skôr, než by sme si
ho stihli prečítať. Z rovnakého dôvodu má polnočný reset minútovú pauzu.

Polnočný reset preto naďalej berie hodnotu z **lokálneho** rozvrhu, nie priamo
z Family Link — o 00:05 ešte nemusí byť načítaná a čítať vtedy naslepo bola
pôvodná chyba. Skutočnú hodnotu prevezme `simona_cas_fl_zmena`, len čo dorazí.

## Entity

| Entita | Význam |
|---|---|
| `input_number.simona_rozvrh_po` … `_ne` | Týždenný rozvrh: minúty na jednotlivé dni. Kópia rozvrhu z Family Link. |
| `sensor.simona_rozvrh_dnes` | Koľko minút dáva rozvrh na dnes (atribúty `den`, `zajtra`). |
| `input_text.simona_fl_zapisane` | Posledných 5 hodnôt zapísaných do Family Link — slúži na rozoznanie vlastnej ozveny. |
| `input_number.simona_rozpocet_dnes` | Rozpočet na dnes (R) v minútach. O 00:05 sa preberá z rozvrhu v HA. |
| `input_number.simona_pc_pouzite` | Minúty odsedené dnes pri PC. Plní agent. |
| `input_boolean.simona_zdielany_cas` | Hlavný vypínač. Keď je `off`, HA nezasahuje do ničoho. |
| `input_boolean.simona_bez_limitu` | Režim bez limitu — kým je zapnutý, čas sa neráta. |
| `input_number.simona_offset_tablet`, `…_pc` | Minúty, ktoré sa nezapočítali (nazbierané počas režimu bez limitu). |
| `input_number.simona_snap_tablet`, `…_pc` | Stav v okamihu zapnutia režimu. |
| `sensor.simona_pc_zapocitane` | Minúty pri PC po odrátaní nezapočítaných. |
| `input_datetime.simona_pc_kontakt` | Posledné úspešné spojenie s agentom. |
| `input_number.simona_pc_snap_vypnutie` | Minúty agenta v okamihu vypnutia PC. `−1` = dnes sa ešte nevypínalo. |
| `input_datetime.simona_pc_upozornenie` | Kedy naposledy odišlo upozornenie „sedí pri PC po limite". |
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
| `/cas` | Prehľad: rozvrh na dnes, rozpočet, spotreba po zariadeniach, zostatok, stav PC. |
| `/cas_add 30` | Pridá 30 min do dnešného rozpočtu (platí pre obe zariadenia). |
| `/cas_set 120` | Nastaví dnešný rozpočet na 120 min. |
| `/cas_stop` | Ukončí čas hneď — rozpočet zroluje na už spotrebované, tablet sa zamkne. |
| `/cas_pauza`, `/cas_start` | Vypne / zapne zdieľanie (kým je vypnuté, HA nezasahuje). |
| `/cas_bez`, `/cas_limit` | Zapne / vypne režim bez limitu. |

Prístup majú len chaty Jakub (`5756450012`) a Mama (`8413756301`), rovnako ako
pri ostatných automatizáciách.

Rodičia dostanú upozornenie pri **30**, **10** a **0** zostávajúcich minútach
(v režime bez limitu nechodí nič).

### Režim „bez limitu"

Na prázdniny, chorobu alebo výnimočný deň. Kým je zapnutý, **čas sa neráta** —
ani na tablete, ani na počítači, a nechodia žiadne upozornenia.

Nestačí prestať vynucovať: Family Link aj agent merajú ďalej, nedá sa im to
zakázať. Preto si pri zapnutí odložíme snímku stavu a pri vypnutí rozdiel
pripočítame do „nezapočítaných" minút. Spotreba tak po vypnutí pokračuje
presne tam, kde sa zastavila.

Family Link porovnáva svoj limit proti **svojim** nameraným minútam, nie proti
našim započítaným — preto sa nezapočítané minúty musia k stropu pripočítať,
inak by sa tablet zamkol predčasne.

Zapína sa prepínačom na dashboarde, tlačidlom v Telegrame alebo `/cas_bez`.
Polnočný reset ho nevypína, ale nuluje nazbierané offsety.

Snímka má hodnotu **−1, keď režim nebeží**, a ukončenie odpíše minúty len
vtedy, keď je snímka platná. Bez tejto poistky sa raz stalo, že `reload_all`
prehodil prepínač `on → off`, ukončenie sa spustilo naprázdno a odpísalo
celú dennú spotrebu ako nezapočítanú.

### Po vyčerpaní času sa PC raz vypne

Keď sa spoločný čas minie, počítač sa **vypne** — ale nie zákerne:

1. agent to povie nahlas a napíše na obrazovku,
2. **minúta** na uloženie rozrobeného,
3. `shutdown` s ďalšími 10 sekundami,
4. Jakubovi príde do Telegramu, že sa tak stalo.

Vypína sa **raz za deň**. Keď rodič pridá čas a ten sa znova minie, vypne sa
znova (`simona_cas_pc_obnova_vypnutia` na to vynuluje snímku).

### Keď ho potom zapne znova

Do počítača už **nesiahame** — v tom zostáva pôvodný zámer, že sa má vedieť
zastaviť sama. Keď pri ňom po opätovnom zapnutí odsedí **viac ako 3 minúty**,
odíde len upozornenie:

> Simonka si zapla počítač napriek tomu, že už ho nemá používať!!! Choď to
> vyriešiť!!!

- **do Telegramu** Jakubovi,
- **prekrytie na TV** (`notify.tvoverlaynotify`) — posiela sa vždy, aj keď je
  TV vypnutá.

Tie tri minúty sa rátajú z agentových minút od okamihu vypnutia
(`input_number.simona_pc_snap_vypnutie`), nie zo súvislého sedenia — krátka
prestávka teda počítadlo nevynuluje. Kým pri ňom sedí, pripomenie sa najviac
raz za pol hodinu.

Minúty nad rámec rozpočtu sa rátajú ďalej, takže v `/cas` je vidieť, o koľko
limit prekročila — a zajtrajší rozpočet tým nie je dotknutý.

#### Prečo ide TV cez samostatný skript

`continue_on_error: true` **nestačí**. Keď je TV nedostupná, `notify` prepustí
surovú aiohttp chybu („All connection attempts failed"), ktorú Home Assistant
nepovažuje za `HomeAssistantError` — a beh automatizácie sa zastaví. Kým bola
TV prvá v poradí, správa do Telegramu preto pri vypnutej TV **nikdy neodišla**.

Teraz ide Telegram prvý a TV až za ním, cez `script.turn_on
script.simona_tv_oznam` — to je „pošli a zabudni", takže prípadná chyba
zostane v skripte. (`rest_command` sa naopak správa správne, `continue_on_error`
tam funguje — overené na trasách `simona_cas_pc_tick`.)

## Dashboard v Home Assistante

V bočnom paneli je **Simonka** (`/simonka-cas`) — samostatný dashboard s
piatimi sekciami: prehľad spoločného času, rýchle akcie, týždenný rozvrh,
tablet a počítač.

Zámerne to nie je view v hlavnom *Prehľade* — ten má 205 kB konfigurácie a
nemá zmysel ho kvôli tomuto prepisovať. Samostatný dashboard nemôže nič
existujúce rozbiť.

Tlačidlá volajú skripty (`simona_cas_pridaj`, `simona_cas_nastav`,
`simona_cas_ukonci`, `simona_pc_prikaz`), lebo karta typu *button* nevie
odovzdať parameter priamo do `input_number.set_value`.

## Súbory

| Súbor | Kam patrí |
|---|---|
| `ha/packages/simona_cas.yaml` | `/config/packages/` — rozvrh, účtovanie, prepočty, synchronizácia s Family Link, skripty pre dashboard |
| `ha/packages/simona_cas_telegram.yaml` | `/config/packages/` — Telegram prehľad a tlačidlá |
| `ha/packages/patch-*.py` | idempotentné záplaty, ktorými sa obe kópie (repo aj `/config/`) menili naraz — po zbehnutí majú rovnaký md5 |
| `ha/dashboard/simonka-cas.yaml` | obsah dashboardu (surový editor konfigurácie) |
| `agent/` | Windows agent (viď `docs/AGENT.md`) |
| `ha/addons/timelimit/` | `/addons/timelimit/` na HA — lokálny add-on **TimeLimit Server** (self-hostovaná náhrada Family Link, zatiaľ len beží; viď `ha/addons/timelimit/README.md`) |

Do existujúceho `packages/pc_control.yaml` bola pridaná jediná vec — položka
menu, v oboch blokoch, kde sa hlavné menu skladá:

```yaml
- "🤝 Spoločný čas:/pct_main"
```

Token agenta je v `secrets.yaml` ako `pc_agent_token`.

## TimeLimit server (príprava odchodu od Google)

Celé zdieľanie času dnes stojí na HAFamilyLink, teda na neoficiálnom API,
ktoré Google môže kedykoľvek rozbiť. Ako záložná cesta beží v HA lokálny
add-on **TimeLimit Server** (`local_timelimit`) — self-hostovaný server pre
open-source rodičovský dohľad [TimeLimit](https://timelimit.io), spolu
s Mailpitom na prihlasovacie kódy. API je verejne na
`https://timelimit.fabrici.xyz` (cez Caddy, bez VPN — appka ho potrebuje aj
mimo domu), na LAN `http://192.168.1.102:8080`; maily len na LAN na
`http://192.168.1.102:8025`; databáza v add-one MariaDB. Prihlasovacie kódy
server pošle len adresám `@fabrici.xyz`, nikto cudzí si rodinu nezaloží.

**Simonkin tablet ostáva na Family Linku.** Server zatiaľ len beží a čaká na
test na náhradnom zariadení; napojenie na zdieľaný rozpočet nie je urobené.
Podrobnosti, obídené chyby v oficiálnom image a ďalšie kroky sú v
`ha/addons/timelimit/README.md`.

## Na čo si dať pozor

- **Zmena v aplikácii prepíše aj rozvrh v HA, nielen dnešok.** Ak si chcel dať
  výnimku len na dnes, oprav rozvrh na dashboarde — Telegram ti to pripomenie.
  Na jednorazové pridanie času je lepší `/cas_add` alebo bonus vo Family Link.
- **Denný limit musí byť vo Family Link zapnutý** (`switch.simona_fabriciova_daily_limit`).
  Keď je vypnutý, Google nič nevynucuje a strop tabletu je len číslo.
- **`switch.iplay_50` má obrátenú logiku, než by si čakal:** `on` znamená
  *odomknuté*, `off` znamená *zamknuté* (v integrácii je `async_turn_on` =
  unlock). Preto sú na dashboarde dve tlačidlá a nie prepínač — prepínač
  nazvaný „Zamknúť tablet" zvádzal k tomu, že jeho vypnutím sa tablet práve
  zamkol.
- **Kým je tablet zamknutý ručne, Family Link neprijíma zmeny denného
  limitu.** Strop tak zamrzne na poslednej hodnote a po odomknutí sa dorovná
  až pri najbližšom prepočte. Dashboard aj `/cas` na to upozornia.
- **Chromecast HD je mimo rozpočtu** — má vo Family Link vlastný limit.
  Pozeranie Jellyfinu na TV teda čas na tablete ani na PC neujedá.
- **Bonus dávaj cez Telegram**, nie v aplikácii Family Link. Cez Telegram sa
  pridá do spoločného rozpočtu; bonus z appky sa síce tiež započíta
  (`sensor.iplay_50_active_bonus`), ale platí len pre tablet.
- **Keď je PC vypnutý**, HA sa naň pýta raz za päť minút a posledná známa
  spotreba ostáva platiť. Vypnutím PC sa teda čas nedá „vrátiť".
- **Vypnutie PC nie je blokovanie.** Zapnúť si ho môže hneď znova — vtedy už
  chodia len upozornenia. Kto chce tvrdé blokovanie, musí to riešiť inak.
- **Keď Family Link nedá dáta**, systém úmyselne nerobí nič — radšej žiadny
  zásah než omylom nastavený limit 0.
