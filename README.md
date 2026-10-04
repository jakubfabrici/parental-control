# Rodičovský dohľad so zdieľaným časom

Jeden denný rozpočet obrazovkového času pre **tablet** (Android, appka
[TimeLimit](https://timelimit.io) proti vlastnému serveru) a **Windows PC**
dokopy. Keď Simonka odsedí hodinu na tablete, na PC jej zostanú dve — a
naopak. Ovláda sa z Telegramu a z dashboardu; týždenný rozvrh je v Home
Assistante a je jediným zdrojom pravdy.

## Ako to funguje

Jediný účet vedie Home Assistant. Obe zariadenia sú len spotrebitelia jedného
čísla a každé si svoj strop vynucuje samo:

```
        týždenný rozvrh v HA (input_number.simona_rozvrh_po … _ne)
                              │
                       00:06  ▼
            input_number.simona_rozpocet_dnes = R
                              │
        ┌─────────────────────┴──────────────────────┐
        ▼                                            ▼
  cieľ tabletu T := R − pc                    povolené na PC
  MQTT timelimit/cmd → set_total              := R − tablet
        │                                            │
        ▼                                            ▼
  most → TimeLimit server → appka             agent varuje hlasom; po nule
  na tablete zablokuje „Ostatné               HA počítač raz vypne
  aplikácie", keď sa T minie
        │                                            │
        └──────────► skutočná spotreba ◄─────────────┘
     tablet: sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes
     pc:     agent hlási každú minútu
```

PC dostáva nový strop každú minútu. Tabletu HA posiela cieľ pri každej zmene
(a pre istotu raz za päť minút); most ho pri uťahovaní posúva po
5-minútových krokoch a presne až v posledných 15 minútach, lebo každá zmena
tablet zobudí a ujedá mu baterku. Pridaný čas sa prejaví hneď. Keď hrá na
oboch zariadeniach naraz, tablet spoločný rozpočet neprekročí a na PC je
odchýlka nanajvýš minúta či dve.

### Prečo TimeLimit

Family Link od Google **nemá verejné API** a neoficiálna integrácia, cez
ktorú ho HA kedysi riadil, 27. 9. 2026 prestala fungovať a 4. 10. 2026 sa
z HA odstránila (viď [História](#história)).
[TimeLimit](https://timelimit.io) je open-source rodičovský dohľad pre
Android a jeho server beží **doma**, ako add-on v Home Assistante:

- protokol sa mení len vtedy, keď server aktualizuješ ty, nie keď sa tak
  rozhodne Google,
- most sa do rodiny prihlási ako ďalšie rodičovské zariadenie a píše len do
  vlastného pravidla a extra času — pravidlá appky nechá tak,
- minúty sa rátajú **po kategóriách**, takže vždy povolené aplikácie sa do
  spoločného času nerátajú.

### Rozvrh je v HA, pravidlá appky sú len záchranná sieť

Týždenný rozvrh je v HA ako sedem helperov `input_number.simona_rozvrh_po`
… `_ne`:

| Deň | Minút |
|---|---:|
| pondelok – piatok | 60 |
| sobota, nedeľa | 180 |

`sensor.simona_rozvrh_dnes` z nich vyberie dnešnú hodnotu (atribúty `den` a
`zajtra`) a o 00:06 sa ňou naplní rozpočet na nový deň (prečo nie o 00:00,
viď [Polnoc](#polnoc)). Je to lokálna hodnota, takže polnočný reset nemôže
zlyhať na nedostupnom serveri.

Kategória „Ostatné aplikácie" má v appke TimeLimit vlastné pravidlá s
rovnakými číslami (60 min denne po–pia, 180 min denne so–ne, `perDay`). Tie
sú len **záchranná sieť**: platia, keď HA alebo most nebeží, a krátko po
polnoci (viď nižšie). Kým HA beží, most ich nemení, ale ide cez ne oboma
smermi — nižšie vlastným pravidlom HA, vyššie extra časom. Rozvrh preto meň
**len v HA** (dashboard); pravidlá appky sa prejavia iba pri výpadku.

## Tablet: TimeLimit

Tablet (iPlay 50) riadi appka TimeLimit, v ktorej je prihlásená Simonka.
Server beží v HA ako lokálny add-on **TimeLimit Server** (`local_timelimit`,
v repe `ha/addons/timelimit/`), spolu s Mailpitom na prihlasovacie kódy. API
je verejne na `https://timelimit.fabrici.xyz` (cez Caddy, bez VPN — appka ho
potrebuje aj mimo domu), na LAN `http://192.168.1.102:8080`; maily len na LAN
na `http://192.168.1.102:8025`; databáza v add-one MariaDB. Prihlasovacie
kódy server pošle len adresám `@fabrici.xyz`, nikto cudzí si rodinu nezaloží.

Súčasťou add-onu je **most do HA** (`bridge/bridge.js`): prihlási sa do
rodiny ako ďalšie rodičovské zariadenie „Home Assistant", cez MQTT discovery
dáva do HA entity na dieťa (použité minúty, zostatok, zablokované, bez
limitu, extra čas, strop na dnes) aj na kategórie a príkazy prijíma na
topicu `timelimit/cmd`. Podrobnosti, celý zoznam entít a obchádzky chýb
v oficiálnom image sú v `ha/addons/timelimit/README.md`.

### Kategórie u Simonky

| Kategória | Čo v nej je | Pravidlá |
|---|---|---|
| Allowed Apps | vybrané aplikácie + `.dummy.system_image` (= všetky nezaradené **systémové** aplikácie) | žiadne — povolené stále, do spoločného času sa nerátajú |
| Ostatné aplikácie | predvolená kategória pre každú nezaradenú aplikáciu | 60 min denne po–pia, 180 min denne so–ne (`perDay`) — len záchranná sieť |

Vždy povolené aplikácie sa pridávajú a odoberajú z dashboardu (viď nižšie).

### Cieľ na dnes

HA počíta pre tablet **cieľ** `sensor.simona_tablet_cielovy_limit` = R − PC
(plus minúty nezapočítané v režime bez limitu; kým režim beží, 1440) a
posiela ho mostu:

```json
{"action": "set_total", "child": "Simonka", "category": "Ostatné aplikácie", "minutes": T}
```

Most cieľ drží v stave (aj cez reštart, platí len pre daný deň) a pri každej
synchronizácii ho premieta do TimeLimit:

- vlastné pravidlo HA = min(T, strop appky); keď T ≥ strop appky, pravidlo
  HA netreba,
- čo je nad strop appky, doplní **extra časom** a dorovnáva ho na presný
  zvyšok, takže appke vždy zostáva T − použité.

Sprísnenie (PC ujedá z rozpočtu) posiela po 5-minútových krokoch a presne až
v posledných 15 minútach tabletu; uvoľnenie (pridaný čas) ide hneď. Tablet
totiž zobudí každá zmena — server mu cez websocket pošle „should sync".

Keď sa zdieľanie vypne (`input_boolean.simona_zdielany_cas` = `off`), HA
pošle `clear_total` a most svoje pravidlo aj extra čas uprace — platia len
pravidlá appky.

### Aktuálnosť času tabletu

Appka TimeLimit odosiela spotrebu sama len raz za 10 minút a pri zhasnutej
obrazovke sa odpája. Server (doplnok v add-one, `patches/ha-sync.js`) preto
tablet, kým na ňom pribúda spotreba, každých 30 s požiada o synchronizáciu;
pri nečinnosti dá jednu záverečnú a potom ho nebudí. Most zmeny ťahá každých
15 s — HA má čas tabletu oneskorený najviac asi o minútu. Na tablete treba raz
zapnúť *TimeLimit → About → Error diagnose → Experimental flags → „Keep
connected when the screen is off"* (dostane sa tak do HA aj spotreba tesne
pred zhasnutím) a v companion appke HA senzor **Interactive** (pri zapnutí
obrazovky HA tablet hneď synchronizuje, `ha/packages/simona_tablet_sync.yaml`).
Podrobnosti v
[`ha/addons/timelimit/README.md`](ha/addons/timelimit/README.md#aktuálnosť-času-tabletu-v-ha).

### Polnoc

Rozpočet sa z rozvrhu naplní o **00:06** a vtedy sa vynulujú aj včerajšie
čísla (minúty PC, nezapočítané minúty, snímky). Nie o 00:00: agent na PC
nuluje o 00:00 a most ohlási minúty nového dňa až pri prvej synchronizácii
po polnoci (raz za minútu). O 00:06 sú obe strany dávno na novom dni, takže
sa nový rozpočet nestretne so včerajšími minútami — inak by prišlo falošné
„čas sa minul" a vypnutie PC o polnoci.

Cieľ aj vlastné pravidlo HA platia len pre deň, v ktorý vznikli; pri prvej
synchronizácii po polnoci ich most zahodí sám (extra čas je v TimeLimit tiež
len na konkrétny deň). Kým HA nepošle prvý cieľ nového dňa (posiela ho pri
zmene a raz za päť minút), ide tablet podľa pravidiel appky. Do 00:06 sa
cieľ počíta ešte zo včerajšieho rozpočtu, potom už z nového.

## Entity

| Entita | Význam |
|---|---|
| `input_number.simona_rozvrh_po` … `_ne` | Týždenný rozvrh: minúty na jednotlivé dni. Jediný zdroj pravdy. |
| `sensor.simona_rozvrh_dnes` | Koľko minút dáva rozvrh na dnes (atribúty `den`, `zajtra`). |
| `input_number.simona_rozpocet_dnes` | Rozpočet na dnes (R) v minútach. O 00:06 sa preberá z rozvrhu v HA; pridanie času ho zvýši. |
| `input_number.simona_pc_pouzite` | Minúty odsedené dnes pri PC. Plní agent. |
| `input_boolean.simona_zdielany_cas` | Hlavný vypínač. Keď je `off`, HA nezasahuje do ničoho. |
| `input_boolean.simona_bez_limitu` | Režim bez limitu — kým je zapnutý, čas sa neráta. |
| `input_number.simona_offset_tablet`, `…_pc` | Minúty, ktoré sa nezapočítali (nazbierané počas režimu bez limitu). |
| `input_number.simona_snap_tablet`, `…_pc` | Stav v okamihu zapnutia režimu. |
| `sensor.simona_pc_zapocitane` | Minúty pri PC po odrátaní nezapočítaných. |
| `input_datetime.simona_pc_kontakt` | Posledné úspešné spojenie s agentom. |
| `input_number.simona_pc_snap_vypnutie` | Minúty agenta v okamihu vypnutia PC. `−1` = dnes sa ešte nevypínalo. |
| `input_datetime.simona_pc_upozornenie` | Kedy naposledy odišlo upozornenie „sedí pri PC po limite". |
| `sensor.simona_tablet_namerane` | Minúty tabletu z TimeLimit (len kategória Ostatné aplikácie) pred odrátaním nezapočítaných. |
| `sensor.simona_tablet_pouzite` | Minúty na tablete po odrátaní nezapočítaných. |
| `sensor.simona_rozpocet_celkom` | Celkový rozpočet na dnes, = R. |
| `sensor.simona_cas_pouzity` | Spolu tablet + PC (atribúty `tablet`, `pc`). |
| `sensor.simona_cas_zostava` | Koľko z rozpočtu ešte zostáva. |
| `sensor.simona_tablet_cielovy_limit` | Cieľ na dnes, ktorý sa posiela mostu TimeLimit (`set_total`). |
| `sensor.simona_pc_povolene` | Koľko celkovo smie dnes odsedieť pri PC. |
| `binary_sensor.simona_pc_online` | Či sa agent ohlásil za posledných 5 minút. |

Z mosta TimeLimit sa používajú najmä
`sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes` (minúty tabletu,
z ktorých sa ráta spoločný čas), `switch.timelimit_simonka_zablokovane`
(dočasné zablokovanie tabletu), `sensor.timelimit_most` (stav mosta) a
entity vždy povolených aplikácií. Úplný zoznam je
v `ha/addons/timelimit/README.md`.

## Ovládanie z Telegramu

V menu **Simonka PC** je položka „🤝 Spoločný čas" s prehľadom a tlačidlami.
Píše sa aj priamo:

| Príkaz | Čo urobí |
|---|---|
| `/cas` | Prehľad: rozvrh na dnes, rozpočet, spotreba po zariadeniach, zostatok, stav PC; keď je tablet zablokovaný, aj „🔒 Tablet je zablokovaný". |
| `/cas_add 30` | Pridá 30 min do dnešného rozpočtu (platí pre obe zariadenia). |
| `/cas_set 120` | Nastaví dnešný rozpočet na 120 min. |
| `/cas_stop` | Ukončí čas hneď — rozpočet zroluje na už spotrebované, takže obom zariadeniam zostane 0 (na tablete idú ďalej len vždy povolené aplikácie). |
| `/cas_pauza`, `/cas_start` | Vypne / zapne zdieľanie (kým je vypnuté, HA nezasahuje). |
| `/cas_bez`, `/cas_limit` | Zapne / vypne režim bez limitu. |

Prístup majú len chaty Jakub (`5756450012`) a Mama (`8413756301`), rovnako ako
pri ostatných automatizáciách.

Menu **Simonka Tablet** a ranná ponuka víkendového režimu cez sviatky sú
automatizácie v `/config/automations.yaml` (nie v balíku, mimo repa). Menu
ukazuje minúty a zostatok tabletu a spoločný čas z TimeLimit. „Pridať
30/60 min" pridá do spoločného rozpočtu (pri vypnutom zdieľaní priamo extra
čas v TimeLimit), „Zablokovať/Odblokovať" prepína
`switch.timelimit_simonka_zablokovane` a víkendový režim nastaví spoločný
rozpočet na 150 min. Záloha pred prechodom na TimeLimit:
`automations.yaml.bak-pred-timelimit-telegram`.

Rodičia dostanú upozornenie pri **30**, **10** a **0** zostávajúcich minútach
(v režime bez limitu nechodí nič).

### Režim „bez limitu"

Na prázdniny, chorobu alebo výnimočný deň. Kým je zapnutý, **čas sa neráta** —
ani na tablete, ani na počítači, a nechodia žiadne upozornenia.

Nestačí prestať vynucovať: TimeLimit aj agent merajú ďalej, nedá sa im to
zakázať. Preto si pri zapnutí odložíme snímku stavu a pri vypnutí rozdiel
pripočítame do „nezapočítaných" minút. Spotreba tak po vypnutí pokračuje
presne tam, kde sa zastavila. Kým režim beží, dostane most cieľ 1440 min.

Most aj appka porovnávajú cieľ so **svojimi** nameranými minútami, nie s
našimi započítanými — preto sa nezapočítané minúty musia k cieľu pripočítať,
inak by sa tablet zablokoval predčasne.

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

> **Pripravená zmena (zatiaľ nenasadená).** Výskum zo 7. 9. 2026 ukázal, prečo
> indikátor „práve pri ňom sedí" často klame: je to zapamätaná odpoveď
> posledného úspešného ticku, takže pri zlyhaní ticku ostane zhasnutý (19 minút
> hrania, o ktorých HA nevedel) a po vypnutí PC ostane svietiť (3 h 16 min).
> Riešenie je v `docs/VYSKUM-PREZENCIA.md`, kód v `ha/packages/patch-prezencia.py`
> a `agent/patch-agent-1.1.0.py`. Prezenciu bude odvodzovať nový
> `binary_sensor.simona_pc_sedi` z veku dvoch značiek (posledný kontakt
> a posledný vstup), pribudnú `input_datetime.simona_pc_vstup`,
> `simona_pc_ticho`, `simona_pc_vypnutie_pokus`, `input_number.simona_pc_latencia`,
> `simona_pc_lag_max`, counter `simona_pc_skok_zamietnuty` a automatizácie
> „PC offline → zhasnúť používa sa", „PC sa prestal hlásiť" a „PC hlási
> nedôveryhodnú spotrebu". Upozornenie po limite ostáva na starej podmienke,
> kým na PC nebeží agent 1.1.0 — inak by prestalo chodiť úplne.

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

Sekcia **Tablet (TimeLimit)**: stav a zostatok, limit na dnes, zablokovanie,
bez limitu, tlačidlá, ktoré pridávajú do spoločného rozpočtu, blok na
30 min, rozpis po kategóriách, správa **vždy povolených aplikácií**
(zbaliteľný zoznam, výber na odobratie, pridanie balíka menom) a stav mosta
s tlačidlom na synchronizáciu.

## Súbory

| Súbor | Kam patrí |
|---|---|
| `ha/packages/simona_cas.yaml` | `/config/packages/` — rozvrh, účtovanie, prepočty, cieľ pre TimeLimit, PC, skripty pre dashboard |
| `ha/packages/simona_cas_telegram.yaml` | `/config/packages/` — Telegram prehľad a tlačidlá |
| `ha/packages/simona_tablet_sync.yaml` | `/config/packages/` — pri zapnutí obrazovky tabletu (senzor Interactive z companion appky) požiada TimeLimit o synchronizáciu |
| `ha/packages/patch-*.py` | idempotentné záplaty, ktorými sa obe kópie (repo aj `/config/`) menili naraz — po zbehnutí majú rovnaký md5; staršie sú záznamom histórie |
| `ha/packages/patch-bez-familylink.py` | posledná z nich (4. 10. 2026): z oboch balíkov odstránila vetvu Family Link |
| `ha/dashboard/simonka-cas.yaml` | obsah dashboardu (surový editor konfigurácie) |
| `agent/windows-remote-control/` | kanonický zdroj Windows agenta — presne to, čo beží na PC (bez `config.json`) |
| `agent/release.sh`, `agent/omv/` | vydanie novej verzie na OMV a jednorazová príprava OMV (viď `docs/UPDATE.md`) |
| `agent/patch-agent*.ps1` | historické záplaty, ktorými vznikla dnešná verzia agenta |
| `ha/addons/timelimit/` | `/addons/timelimit/` na HA — lokálny add-on **TimeLimit Server** (server, Mailpit a most do HA `bridge/bridge.js`; viď `ha/addons/timelimit/README.md`) |

Do existujúceho `packages/pc_control.yaml` bola pridaná jediná vec — položka
menu, v oboch blokoch, kde sa hlavné menu skladá:

```yaml
- "🤝 Spoločný čas:/pct_main"
```

Token agenta je v `secrets.yaml` ako `pc_agent_token`.

## Na čo si dať pozor

- **Na tablete musí byť v appke TimeLimit prihlásená Simonka.** Kto je
  prihlásený, ukazuje dashboard („Na tablete prihlásený"); keď je tam rodič,
  appka nevynucuje nič.
- **Na tablete zapni „Keep connected when the screen is off" (TimeLimit) a
  senzor Interactive (companion appka HA).** Bez prvého sa spotreba tesne
  pred zhasnutím obrazovky (do ~1 minúty) dostane do HA až pri ďalšom zapnutí;
  bez druhého sa tablet s prvým prepínačom po zapnutí obrazovky ozve až pri
  ďalšej spotrebe (viď [Aktuálnosť času tabletu](#aktuálnosť-času-tabletu)).
- **Pravidlá appky (1 h / 3 h) sú len záchranná sieť.** Platia, keď HA alebo
  most nebeží, a krátko po polnoci, kým HA nepošle cieľ nového dňa. Rozvrh
  meň v HA, nie v appke.
- **Ručný extra čas a strop na dnes sa pri zapnutom zdieľaní prepíšu.** Most
  ich pri každej synchronizácii dorovná podľa cieľa z HA — čas pridávaj cez
  spoločný rozpočet (`/cas_add`, tlačidlá v Telegrame a na dashboarde). Ručné
  nastavenie vydrží, len keď je zdieľanie vypnuté.
- **Keď most nebeží**, HA nič nemení — radšej žiadny zásah než omylom
  nastavený limit 0. Entity TimeLimit sú vtedy `unavailable`, tablet ide
  podľa toho, čo server dostal naposledy (spotreba na PC sa mu odvtedy
  neodráta), a PC si drží posledný strop. Stav ukazuje `sensor.timelimit_most`.
- **Dohľad Google na tablete vypína len rodič** — viď nasledujúcu sekciu.
  Kým beží, môže tablet zastaviť skôr, než by ho zastavil TimeLimit.
- **Chromecast HD a TV Philips sú mimo tohto systému.** Pozeranie Jellyfinu
  na TV čas na tablete ani na PC neujedá.
- **Keď je PC vypnutý**, HA sa naň pýta raz za päť minút a posledná známa
  spotreba ostáva platiť. Vypnutím PC sa teda čas nedá „vrátiť".
- **Vypnutie PC nie je blokovanie.** Zapnúť si ho môže hneď znova — vtedy už
  chodia len upozornenia. Kto chce tvrdé blokovanie, musí to riešiť inak.

## Čo musí urobiť rodič na strane Google

Z Home Assistanta je Family Link preč, na tablete však Googlov dohľad beží
ďalej. Vypnúť sa dá len v appke Family Link na rodičovskom telefóne:

- pre iPlay 50 vypnúť **denný limit** (Daily limit), **večierku**
  (Downtime/Bedtime) a **školský čas** (School time) a tablet odomknúť,
  **alebo**
- ukončiť dohľad nad Google účtom Simony, ak to Google v jej veku dovolí.

Inak beží Googlov limit na tablete **súbežne** s TimeLimit a vyhráva ten
prísnejší. To isté rozhodnutie sa týka aj Chromecastu HD a TV Philips (nie
sú súčasťou tohto systému). Pomocná appka Family Link
(`com.google.android.apps.kids.familylinkhelper`) ostáva v Allowed Apps
zámerne, kým sa dohľad Google neukončí.

## História

**Family Link (do 27. 9. 2026).** Pôvodne tablet riadil Google Family Link
cez neoficiálnu integráciu z HACS
[noiwid/HAFamilyLink](https://github.com/noiwid/HAFamilyLink). HA do neho
priebežne zapisoval **override na dnešný deň** (`familylink.set_daily_limit`,
teda `timeLimitOverrides:batchCreate`) a o 23:57 ho vracal na hodnotu
rozvrhu. Týždenný rozvrh sa z Family Link vyčítať nedal — integrácia dávala
len limit platný na dnes, vrátane nášho override. Keď si z neho polnočný
reset bral rozpočet, čítal vlastný včerajší zvyšok a rozpočet sa scvrkával
(180 → 75 → 61); odvtedy je rozvrh v HA. Zmenu limitu urobenú v appke HA
preberal sám a vlastnú ozvenu rozoznával podľa posledných piatich zapísaných
hodnôt (`input_text.simona_fl_zapisane`); medzi 00:00 a 00:10 do Family Link
nezapisoval. Bonus pridaný v appke sa pripočítaval k rozpočtu.

**Výpadok 27. 9. 2026.** Integrácia prestala fungovať o 10:28 (08:28 UTC),
keď sa HA reštartoval a prvýkrát načítal verziu 2.2.1, ktorú HACS stiahol
25. 9. o 17:38. Odvtedy boli všetky jej entity `unavailable` a config entry
ostal v `setup_retry` (auth server vracal 403). Tablet sa do spoločného času
nerátal a PC dostával strop 0.

**Prechod na TimeLimit.** Self-hostovaný TimeLimit server bežal v HA najprv
ako záložná cesta; od 3. 10. sa cez neho rátal zdieľaný čas tabletu,
s prepínačom zdroja TimeLimit / Family Link. **4. 10. 2026** prešiel tablet
na TimeLimit úplne (zdieľaný čas s PC ostal v HA, PC ďalej riadi Windows
agent) a Family Link sa z Home Assistanta odstránil:
integrácia, jej config entry a entity, add-on „Google Family Link Auth"
(`92c20130_familylink-playwright`) aj jeho repozitár add-onov, položka v
HACS, uložené cookies v `/share/familylink` a jej história v recorderi.
Z balíkov vetvu Family Link odstránil `ha/packages/patch-bez-familylink.py`
— zmizol prepínač zdroja, evidencia zápisov a preberanie zmeny z appky,
večerné vracanie override aj pauza 00:00–00:10. Windows agent sa logikou
nezmenil; verzia 1.2.1 len preformulovala dva komentáre, ktoré Family Link
spomínali.

Staršie záplaty `ha/packages/patch-*.py` (napr. `patch-rozvrh.py`,
`patch-fl-zmena.py`, `patch-timelimit.py`) sú záznam histórie; ostávajú, ako
boli, a Family Link v nich zostáva.
