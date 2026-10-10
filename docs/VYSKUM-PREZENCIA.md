# Prečo `input_boolean.simona_pc_pouziva_sa` nesvieti, keď má

Výskum z 6.–7. 9. 2026. Podklad: agent.log a Windows event log z PC, história
a trasy automatizácií z Home Assistanta (HA 2026.9.0), zdrojáky
`PcAgent.ps1` (1.0.0, 406 riadkov) a `ha/packages/simona_cas.yaml`.
Časy: **HA = UTC**, **PC = lokálny (UTC+2)**.
Značky: **FAKT** = priamo z kódu, logu alebo histórie, **ODVODENÉ** = záver
z faktov, **DOMNIENKA** = nepodložené meraním.

> **Dve výhrady, ktoré platia pre celý dokument.**
> 1. Hodiny PC a HA nie sú zosúladené — nameraný rozdiel −0,3 až −2,3 s a nie
>    je konštantný. Každý údaj odvodený z porovnania `agent.log` a HA histórie
>    má toleranciu ±2,5 s.
> 2. Merania robené priamo na PC (CPU agenta, priorita procesu, časy
>    `Measure-Command`) sa dnes nedajú zopakovať — PC je od 6. 9. 17:45
>    lokálne vypnutý. Nesú preto menšiu váhu než čísla z HA, ktoré sú
>    reprodukovateľné.

> **História (doplnené 4. 10. 2026).** V čase výskumu riadil tablet Google
> Family Link a z neho prichádzali aj minúty tabletu, od ktorých závisí strop
> pre PC. Integrácia Family Link prestala fungovať 27. 9. 2026 a 4. 10. 2026
> bola zo systému odstránená; tablet dnes riadi **TimeLimit** (vlastný server
> ako lokálny add-on v HA a MQTT most) a minúty tabletu sú
> `sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes` (vždy povolené
> aplikácie sa nerátajú). Zmienky o Family Link nižšie opisujú stav v čase
> výskumu; na nálezoch o agentovi a prezencii výmena zdroja nič nemení.

---

## 1. Odpoveď

**`pouziva_sa` nie je stav sveta, je to zapamätaná odpoveď posledného
úspešného tiku.** Keď tik zlyhá alebo príde v nesprávnej sekunde, HA nemá
odkiaľ vziať pravdu a nechá starú hodnotu. Nie je tam watchdog, nie je tam
hysterézia a nie je tam druhá cesta k pravde.

### 1.1 Jediný zapisovateľ, jediná cesta — a tá sa dá zastaviť

**FAKT** (`simona_cas.yaml`, pôvodné riadky 656–658): celý beh automatizácie
`simona_cas_pc_tick` sa zastaví na podmienke
`{{ pc is defined and pc.content is defined and pc.content.used is defined }}`.
Až za ňou je jediný zápis `input_boolean.turn_{{ ... }}`.

Dôsledok je symetrický a bolia oba smery:

| Situácia | Čo sa stane | Nameraný prípad |
|---|---|---|
| tik zlyhá počas hrania | `pouziva_sa` ostane **OFF**, hoci dieťa sedí pri PC | 6. 9. 07:45:00 → 08:05:02 UTC, medzera **20,0 min** |
| PC sa vypne | `pouziva_sa` ostane **ON** hodiny | 6. 9. 10:02 → 13:58 UTC, PC vypnutý o 10:42:31 |

**FAKT** (trasy): behy 14:03 a 14:04 UTC skončili `script_execution: aborted`
presne na `action/1` — to je tá podmienka. Toto je cesta, ktorou timeout
ticho vypína aktualizáciu.

### 1.2 Tiky zlyhávajú, lebo jednovláknový agent je v nesprávnej chvíli zaseknutý

**FAKT** `rest_command.pc_tick` mal `timeout: 8` (HA default je 10). V aiohttp
je to `ClientTimeout(total=8)`, teda kumulatívne na celú operáciu.

**FAKT** `PcAgent.ps1:397–406`: slučka je jednovláknová
(`while (-not $ctxTask.Wait(20000)) { Invoke-Tick }`), request čaká vo fronte
http.sys, kým dobehne práve bežiaci tik; po obsluhe sa spúšťa ďalší
bezpodmienečný `Invoke-Tick`.

**FAKT** `PcAgent.ps1:372–387`: akcia `tick` robila **synchrónne pred
odpoveďou** `Save-State`, celý `Invoke-Tick` (vrátane `Get-Process LogonUI`,
`Ensure-Unblocked` a `Invoke-Warnings`) a `Limit-Text`. Pri stupni varovania
`Invoke-Warnings` spúšťa **dva nové procesy** cez `Start-Process` — a to celé
bolo v ceste HTTP odpovede.

Merania:

| Veličina | Hodnota |
|---|---|
| latencia zápisu kontaktu pri hraní (n = 137) | medián 0,51 s, p95 3,72 s, max 6,41 s |
| to isté v nečinnosti (n = 82) | medián 0,02 s, max 0,52 s, 0 tikov nad 1 s |
| beh automatizácie pri rýchlom agentovi | 22–115 ms |
| doložené zaseknutia slučky (`agent.log`) | 6. 9. o 09:46:12 ≈ 12–14 s, 10:00:04 ≈ 4 s |
| chyby v `system_log` za 30,65 h | 353 (`client_error` + `timeout`), teda ~276 / 24 h |

**Dôležité spresnenie:** timeout 8 s **nie je príčina, len prah.** Zaseknutie
14 s by neprežil ani default 10 s. Príčina je, že jedno vlákno robí prácu
v okamihu, keď má odpovedať.

*(Korekcia oproti pracovnej verzii: tvrdenie o „37 s medzi dvoma riadkami tej
istej obsluhy" sa z logu dokázať nedá — varovanie o 12:41:40 mohol rovnako
dobre zapísať bežný timerový tik. Z pôvodne uvádzaných štyroch „stallov" sú
v dôkazovom balíku doložené dva.)*

### 1.3 `active` je bodová vzorka bez hysterézie

**FAKT** `PcAgent.ps1:49,212`: `$active = ($idleMs -lt 60000) -and (-not $locked)`.
HA to preberal 1:1. Stačí, aby v sekunde vzorky bola pauza 60 s, a indikátor
zhasne na celú minútu, hoci dieťa neodišlo.

**FAKT** 6. 9. počas súvislého hrania: `off 08:18:00 → on 08:19:01` a
`off 09:12:00 → on 09:13:01`. Pri riedkom vstupe 14:05–15:09 UTC bol podiel ON
**19 zo 64 minút = 30 %** v **12 epizódach**.

### 1.4 Päťminútový backoff predlžuje krátku poruchu na dlhé okno

**FAKT** podmienka `{{ is_state('binary_sensor.simona_pc_online','on') or now().minute % 5 == 0 }}`
a `online = (teraz − kontakt) < 300 s`.
**ODVODENÉ** štyri zlyhané tiky → 300 s bez kontaktu → `online` off → HA sa
pýta už len o :00 a :05. Z 20-minútového okna tak bolo len 6–7 pokusov
namiesto 20.

### 1.5 Zosilňovač, ktorý sa nepotvrdil: agent beží ako BelowNormal

**FAKT** úloha HA-PcAgent má `Priority=7`. Podľa dokumentácie Microsoftu je 7
`BELOW_NORMAL_PRIORITY_CLASS`; hodnoty 4, 5 aj 6 sú zhodne `NORMAL`.
**DOMNIENKA** že práve priorita naťahuje latenciu. Saturáciu CPU pri hraní
nikto nezmeral a mimo boot-okna vypadli 6. 9. len 3 tiky zo 158, pričom
`online` sa počas hrania ani raz neprepol na off. Je to lacná úprava, ale bez
A/B merania to nie je oprava.

### 1.6 Čo si videl ty 6. 9. o 09:44–10:05 lokálne

| Lokálne | UTC | Zdroj | Čo sa naozaj stalo |
|---|---|---|---|
| 09:43:41 | 07:43:41 | Win id 12 | boot PC |
| 09:44:21 | 07:44:21 | agent.log | agent naštartoval |
| 09:45:00 | 07:45:00 | HA | **posledný úspešný tik**, `pouziva_sa` OFF (Simona ešte nezačala) |
| 09:46:12 | 07:46 | agent.log | tik vybratý z fronty 12–14 s neskoro, odpoveď po timeoute |
| 09:46:58 – 09:49:58 | 07:46–07:49 | agent.log | tiky prijaté načas, HA kontakt sa ani raz nezmenil |
| **09:48:55** | 07:48:55 | HA logbook | **ty si `pouziva_sa` zapol ručne** |
| 09:50:00 | 07:50:00 | HA | `online` OFF → prechod na 5-minútový interval |
| 10:04:58 | 08:04:58 | agent.log | tik prijatý → kontakt 08:05:02, obnova |
| — | 08:05:02 | HA | `pc_pouzite` skočilo **3 → 22** |

**Podstatné:** agent celý čas fungoval a napočítal **19 minút** aktívneho
používania. HA o nich nevedel ani jednu. Indikátor bol OFF, dashboard hlásil
„Agent sa nehlási" a jediné, čo ho zaplo, bola tvoja ruka.

---

## 2. Ďalšie potvrdené nálezy

### 2.1 Strata `state.json` po výpadku napájania (dvakrát doložene)

**FAKT** `Save-State` bol `Set-Content` do `.tmp` + `Move-Item`, **bez
vynúteného zápisu na disk**, volaný asi päťkrát za minútu.
**FAKT** `agent.log`: `state.json necitatelny` 28. 8. o 12:58:25 a 6. 9.
o 16:04:52 lokálne. Druhý prípad je 27 s po Kernel-Power 41 (tvrdý reset).
**FAKT** v HA: `pc_pouzite` **154 → 0** o 14:05:00 UTC. HA regresiu prijal bez
odporu — nemal spodnú zábranu.

Simulácia stavu o 16:40 lokálne (`bez_limitu` on, `snap_pc` 153, `offset_pc` 3):
vypnutie režimu bez limitu by dalo `pc_zapocitane` 0 a **stratilo by 150 minút**,
ktoré by sa cez sync premietli aj do stropu tabletu (v čase výskumu limit vo
Family Link, dnes denný cieľ pre TimeLimit).

*(Korekcia: pôvodné tvrdenie, že súbor bol 0 B, je v rozpore s vlastnou
chybovou hláškou. „Invalid JSON primitive: ." znamená, že v súbore niečo bolo
— NUL bajty alebo samotný BOM. Prázdny súbor by dal iný výsledok: `''` aj
`'   '` vrátia z `ConvertFrom-Json` `$null` bez výnimky. Preto kontrola
prázdneho súboru v novej verzii nie je zbytočná, len jej odôvodnenie bolo
nepresné.)*

**Čo tú stratu naozaj zastaví:** nie ochranná vetva `raw < snap` — tá na
nameranom scenári dá offset 0 a minúty sú aj tak preč. Zastaví ju
**monotónnosť na strane HA** a **seed** späť do agenta.

### 2.2 Falošné ON pri vypnutom PC

Falošné ON samo nič nespustilo, ale je to palivo pre hrany:
`simona_cas_pc_vypnutie_po_limite` má medzi spúšťačmi `pouziva_sa off → on`.
**FAKT** 14:00–14:35 UTC: 9 prechodov, 4 spustili beh vypínacej automatizácie.
Všetky štyri sa zastavili hneď na druhej podmienke, lebo `bez_limitu` bol on.
**FAKT** o 14:05 UTC senzor `online` blikol off→on za **70 ms** (kvantovanie
na hranici minúty) — ďalšia falošná hrana.

### 2.3 Vypnutie po limite vie vypnúť do prázdna a hovorí dvakrát

**FAKT** `last_triggered` tejto automatizácie je dodnes `None` — ostro nebežala
ani raz, takže všetko o jej priebehu je odvodené z konfigurácie.

Tri problémy:
1. **Vypnutie do prázdna.** Podmienka `online == on` je pravdivá ešte 300 s po
   poslednom kontakte. Namerané oneskorenie senzora za realitou: **4 min 50 s**,
   **5 min 29 s** a **4 min 59 s** (tri vypnutia PC 6. 9.). PC, ktorý zhasne
   počas varovnej minúty, je pri kontrole o 60 s neskôr so 100 % istotou stále
   hlásený ako `on`. HA teda pošle príkaz do prázdna a napíše ti nepravdu.
2. **Snímka nesie dva významy naraz.** `simona_pc_snap_vypnutie` znamená
   súčasne „dnes sme už vypínali" (škrtenie) aj „od tejto hodnoty rátame tri
   minúty". Keby sa zapisovala aj pri neúspešnom pokuse, PC by sa v ten deň
   nevyplo ani raz a zároveň by začali chodiť správy „Simonka si zapla
   počítač", hoci ho nikto nevypol.
3. **Varovanie zaznie dvakrát.** Akcia `speak` text prečíta a akcia `msg`
   v agentovi spúšťa `notify.ps1` **aj** `speak.ps1`.

### 2.4 Trojminútové pravidlo po limite

**FAKT** automatizácia sa spúšťa **výlučne** zmenou `input_number.simona_pc_pouzite`.
Keď tiky zlyhávajú, hodnota zamrzne a **upozornenie nepríde vôbec** — presne
o dĺžku slepého okna. 4. 9. tak HA meškal za agentom 9 minút.

**FAKT** `pouzite` sa zapisovalo **pred** `pouziva_sa` a medzera medzi dvoma
susednými akciami toho istého skriptu je 0,95–7,32 ms (medián 3,7 ms), pričom
doručenie triggeru trvá 844 µs. Podmienky sa teda vyhodnocovali nad **starou**
hodnotou prezencie.

**FAKT** `input_number.set_value` s nezmenenou hodnotou nevyvolá `state_changed`,
takže trigger strieľa len na skutočné prírastky. Dôkaz: 6. 9. bol PC online
súvisle od 14:05 do 15:50 UTC a v histórii `pouzite` nie je medzi 14:05 (0) a
14:36 (1) ani jeden riadok — 31 minút identických zápisov, nula udalostí.

### 2.5 Režim bez limitu a polnoc

**FAKT** polnočný reset nastavoval `simona_snap_pc = -1` bezpodmienečne,
zatiaľ čo šablóna `pc_zapocitane` snímku používa len keď je `>= 0`.
**ODVODENÉ** ak režim „bez limitu" prejde cez polnoc, invariant sa poruší a
ranné minúty sa dodatočne započítajú. Zatiaľ sa to nestalo.

### 2.6 Jediné miesto v kóde, ktoré vie zablokovať agenta na minúty

**FAKT** `RunScript` presmeruje `StandardError`, ale **nikdy ho nečíta**. Pri
viac než ~4 kB na stderr sa dcérsky proces zablokuje na plnom pipe až do
zabitia po 15 s. V logu je 9× timeout `volume.ps1` a 10× timeout `status.ps1`.
Akcia `tick` `RunScript` nevolá — je len v `shutdown`, `restart` a `volume`.

### 2.7 Nedostupný strop znamenal, že agent povie dieťaťu „čas sa minul"

**FAKT** `sensor.simona_pc_povolene` má availability naviazanú na minúty
tabletu — v čase výskumu dáta z Family Link, dnes z TimeLimit cez most — a
`'unavailable' | int(0)` je **0**. Agent nulu prijal ako
platný strop, uložil ju na disk a `Invoke-Warnings` má pre nulu vetvu, ktorá
sa vysloví vždy.
**FAKT** zdrojový senzor (vtedy z Family Link) bol za týždeň **11×** v stave
`unknown`, vždy asi 31 s, a 8 z 11 okien prekrylo hranicu minúty.
**FAKT** prienik s časom, keď je PC online, bol zatiaľ prázdny — v produkcii
sa to teda ešte nestalo. Jediné zalogované „zostáva 0 min" (4. 9. o 11:34 UTC)
má inú, doloženú príčinu: strop skokom klesol na 7 a spotreba už bola 7.

---

## 3. Čo sa nepotvrdilo

- **Boot storm** (Windows Update, Defender, MSI, Search) ako spúšťač okna
  z 6. 9. — **vyvrátené**: prvé zlyhanie bolo o 09:46, prvá udalosť Windows
  Update až o 09:56:26, obnova nastala uprostred „búrky". Disk je SSD.
  Protipríklad: 4. 9. boot o 12:22Z → 27/27 tikov v poriadku.
- **Gamepad, RDP alebo iná session** — **vyvrátené**: úloha beží v session 1,
  a `pc_pouzite` rástlo o minútu za minútu, čo dokazuje, že `GetLastInputInfo`
  vstup videl.
- **Saturácia CPU hrou ako mechanizmus** — **nepotvrdené**, nikdy sa nemerala.
- **„19 zlyhaných tikov"** — nepresné: v 20-minútovej medzere chýba 19 tikových
  slotov, ale HA v tom okne poslala len 6–7 requestov (backoff).
- **„Timeout 8 s je príčina"** — nepresné, je to prah.
- **„state.json bol 0 B"** — v rozpore s dôkazom (§2.1).
- **„Ochranná vetva `raw < snap` zachráni tých 150 minút"** — nepravda,
  chráni ich monotónnosť.
- **Sieťové príčiny** (Wi-Fi, power saving, zmena IP, firewall, DNS) a
  **jeden účet pre celú rodinu** — neoverené dohady, nedali sa ani podložiť,
  ani vylúčiť. Nespoliehaj sa na ne v žiadnom smere.
- **Dva doložené stally slučky ostávajú bez vysvetlenia.** V ich okolí nie je
  v `agent.log` žiadne varovanie ani vo Windows logu žiadna udalosť.
  Dôsledok, ktorý treba brať vážne: nová verzia agenta ich nemusí odstrániť.

---

## 3b. Potvrdenie z prevádzky: 13. 9. 2026

Presne ten istý reťazec sa zopakoval naživo a dá sa na ňom ukázať celý.
Jakub sa ozval o 14:23 miestneho času: „PC je zapnutý už 20 minút a agent sa
nehlási."

| Čas (miestny) | Kde | Čo sa stalo |
|---|---|---|
| 08:53:37 | agent.log | `state.json necitatelny` → agent štartuje s `used = 0` |
| 14:03:23 | agent.log | to isté druhýkrát, agent beží s `limit=180min` |
| 14:04:58 | agent.log | tik z HA prijatý |
| 14:05:05 | agent.log | `handle chyba: ... nonexistent network connection` — HA už spojenie zavrel |
| 14:10:19 | agent.log | ďalší tik prijatý, dequeue meškal asi 20 s |
| 14:15:09, 14:20:09 | HA log | `Error for call_service at pos 1: timeout` |
| 14:22–14:24 | ručné testy | `/ping` 1,6 ms, `POST status` 2,9 s, `POST tick` **12–80 ms** |
| ~14:25 | agent.log | prvý tik prešiel sám od seba, kadencia sa vrátila na minútu |

**Čo z toho plynie.** Agent bol celý čas zdravý a rýchly: na ručný tik
odpovedal za dvanásť milisekúnd. Ale v prvých dvadsiatich minútach po štarte
bol občas zaseknutý na desiatky sekúnd, HA po ôsmich sekundách odpoveď
zahodil a päťminútový backoff z toho urobil dvadsaťminútové slepé okno. Presne
mechanizmus z §1.1 až §1.4, len tentoraz s hodinami v ruke.

Druhá vec: `state.json` sa pokazil **dvakrát za jeden deň**. To je ten istý
nález ako v §2.1 a je to dôvod, prečo monotónnosť na strane HA nie je
kozmetika.

## 3c. Druhý incident: 15. 9. 2026 — agent vôbec nebežal

Iná príčina než 13. 9., preto stojí za vlastný odsek.

| Čas | Kde | Čo sa stalo |
|---|---|---|
| 14. 9. 19:13:27 | agent.log | zaznelo varovanie „zostáva 30 min" (spúšťa dva procesy) |
| 14. 9. 19:13:49 | agent.log | posledný riadok, potom už nič |
| 14. 9. večer | Task Scheduler | úloha skončila s `LastTaskResult = 0xC000013A` = proces bol **zabitý** (typicky pri odhlásení) |
| 15. 9. ~17:00 | PC | zapnutý, používaný |
| 15. 9. 17:05–17:35 | HA log | tik zlyháva každých 5 minút na timeout |
| 15. 9. 17:26 | — | Jakub sa ozýva, že sa nič neodpočítava |
| 15. 9. 17:36 | zásah | úloha spustená ručne, agent nabehol a začal počítať |

**Prečo agent nenabehol sám:** úloha `HA-PcAgent` mala jediný spúšťač — *pri
prihlásení*. Keď proces zomrie počas relácie alebo ho zabije odhlásenie a
počítač sa potom len prebudí, žiadne prihlásenie nenastane a agent zostane
mŕtvy. HA v tom čase nevidí nič, len timeouty: port 8799 síce odpovedá na TCP
(drží ho http.sys), ale odpoveď nepríde.

**Prečo to neohlásil ani strážca z 13. 9.:** automatizácia „PC sa prestal
hlásiť" má podmienku, že sa agent *dnes aspoň raz ozval*. Prechod do stavu
offline nastal predošlý večer, takže dnes už nemala na čo reagovať. Je to
vedomý kompromis proti hluku, ale práve tento prípad nechytí.

**Čo sa pri tom ukázalo navyše:** počítač má obdobia, keď neodpovedá **ani
SSH, ani agent** — TCP spojenie sa nadviaže, ale aplikácie mlčia desiatky
sekúnd. To už nie je vlastnosť agenta a žiadna zmena v jeho kóde to nevyrieši.
Spolu s dvojnásobným poškodením `state.json` 13. 9. to vyzerá na problém so
samotným strojom (disk alebo trvalé preťaženie) a treba to zmerať.

### Čo je od 15. 9. 2026 nasadené na PC

- **Úloha `HA-PcAgent` má druhý spúšťač: každých 5 minút.** `MultipleInstances`
  je `IgnoreNew`, takže bežiacemu agentovi to neublíži — len ho naštartuje,
  keď nebeží. Rovnaká zmena je aj v `Install-Agent.ps1`.
- **Nová úloha `HA-PcAgent-Watchdog`** (`ha-agent/Watchdog-Agent.ps1`, každých
  5 minút). Dvakrát si vypýta `/ping`; až keď zlyhajú oba pokusy, zabije
  zaseknutý proces agenta a spustí úlohu znova. Pokrýva prípad z 13. 9., keď
  proces bežal, ale neodpovedal — vtedy opakovaný spúšťač nepomôže, lebo úloha
  je v stave *Running*.

### Čo je od 13. 9. 2026 nasadené

Skripty `ha/packages/rychla-oprava-tiku.py` a `ha/packages/oprava-strazca.py`,
obe len na strane HA:

- **timeout 8 → 20 s** — odpoveď, ktorá mešká, sa už nezahadzuje;
- **backoff podľa veku kontaktu** — prvých 10 minút po strate kontaktu sa
  skúša každú minútu, nie raz za päť;
- **monotónna spotreba** — strata stavu na PC už neprepíše minúty v HA na nulu;
- **`PC offline → zhasnúť používa sa`** — indikátor už neostane svietiť hodiny
  po vypnutí počítača;
- **`PC sa prestal hlásiť`** — po 10 minútach ticha príde správa do Telegramu.
  Pri tomto incidente by bola prišla o 14:15, teda desať minút predtým, než si
  toho Jakub všimol sám.

Zvyšok fázy 0 (odvodená prezencia, horná poistka na skok spotreby, ACK pri
vypínaní, diagnostické helpery) je pripravený v `ha/packages/patch-prezencia.py`
a naanchorovaný na tento nasadený stav.

### 3d. Obrátený smer: agent hlási sám (15. 9. 2026 večer)

Dva incidenty za tri dni mali spoločnú črtu, ktorú predlžovanie timeoutu
nerieši: **meranie a jeho doručenie boli zviazané do jednej synchrónnej
výmeny.** HA sa spýtala a čakala; keď agent na Core2 Duo neodpovedal včas,
HA zahodila aj to, čo už bolo zmerané. Čím slabší stroj, tým viac zahodených
meraní — a timeout sa dá predlžovať donekonečna, stále to bude pretekanie
s plánovačom Windowsu.

Preto smer otáčame. Agent posiela sám, HA nič nezahadzuje. Zmeškaný beh už
nie je strata dát, len oneskorenie.

**Čo to konkrétne znamená:**

- **Agent 1.2.0** (`agent/patch-agent-1.2.0.py`) posiela každých 30 s POST na
  webhook v HA s tým, čo práve vie: `used`, `idle_sec`, `age_sec`, `active`,
  `allowed`, `version`, `needs_seed`, `lag_max`. Beží to v časovačovej vetve
  slučky, **nikdy nie v ceste HTTP odpovede** — inak by sme si vyrobili presne
  ten problém, ktorý riešime. Keď sa zmení `active`, pošle hneď, aby prezencia
  v HA nemeškala. Zlyhanie sa loguje len pri prvom, piatom a dvadsiatom
  neúspechu po sebe, nech z `agent.log` nie je zoznam neúspechov, keď je HA
  pol dňa dole.
- **Strop si agent pýta sám** tým, že v hlásení posiela, na aký strop verí.
  Keď sa líši od `sensor.simona_pc_povolene`, HA mu pošle nový cez
  `limit_set`. V ustálenom stave teda po sieti nechodí nič navyše.
- **Automatizácia `simona_cas_pc_hlásenie`** (`ha/packages/patch-push.py`) robí
  presne to, čo robil tik — zápis kontaktu, značky vstupu, spotreby —
  s rovnakými zábranami. Dáta z PC sú nedôveryhodné v oboch smeroch a webhook
  je navyše otvorený každému v LAN, kto pozná jeho id, takže spotreba sa zapíše
  len monotónne a len do stropu, ktorý sa dal stihnúť. Zamietnutý skok zvýši
  `counter.simona_pc_skok_zamietnuty` a zapíše sa do logu.
- **Tik ostáva ako záchranná sieť**, ale spustí sa až keď hlásenie nechodí
  viac než 150 s — teda keď je agent starý, zle nastavený alebo mŕtvy.
  Protokol sa teda neláme a starší agent funguje ďalej ako predtým.

Adresa webhooku (vrátane jeho id) je v `config.json` na PC a v `secrets.yaml`
v HA. Do repozitára nepatrí, rovnako ako token.

**Čo sa pri nasadení ukázalo:** na PC bežala stále verzia 1.0.x — záplata
1.1.0 sa tam nikdy nedostala, hoci v repozitári bola. Verzia 1.2.0 nesie oboje
naraz. Úloha `HA-PcAgent` mala aj naďalej prioritu 7 (*below normal*), čo ju na
vyťaženom stroji radí do fronty za prehliadač; nastavená je teraz na 5
(*normal*).

**Nameraný efekt hneď po prepnutí (20:05):** kontakt sa predtým obnovoval raz
za tri minúty (tik s backoffom), po prepnutí každých 40 s — slučka tiká po
20 s a hlásenie má prah 30 s. To je hlboko pod prahom 150 s, takže tik sa
odvtedy nespustil ani raz. `input_number.simona_pc_pouzite` rástlo plynule
ďalej (30 → 32 → 33 → 34), nič sa pri prechode nestratilo, lebo stav si agent
číta z `D:\ProgramData\PcControl\state.json`.

**A potom prišiel dôkaz, ktorý sa nedal naplánovať.** O 20:21, keď som chcel
prečítať `shutdown.ps1`, počítač prestal odpovedať na SSH — presne ten stav
z 3c, keď sa TCP spojenie nadviaže a aplikácia mlčí. V tej istej sekunde
`input_datetime.simona_pc_kontakt` ukazoval `20:21:21`, teda hlásenie staré
dve sekundy. **Agent hlásil ďalej cez výpadok, ktorý zabil interaktívny
kanál.** V starom modeli by tá istá porucha znamenala zahodený tik, potom
druhý, a napokon mlčanie — lebo HA sa pýtala práve tým kanálom, ktorý bol
zaseknutý. Vypnúť počítač sa nakoniec podarilo cez agenta (`rest_command`,
odpoveď `vypinam o 5 s`), nie cez SSH.

Helpery, ktoré nová automatizácia potrebuje (`simona_pc_vstup`,
`simona_pc_lag_max` a dva z rovnakého bloku), sú nasadené tiež — bez nich HA
každých 40 s varovala a značka vstupu sa nikam nezapisovala. Načítali sa za
behu cez `input_number.reload` a `input_datetime.reload`, bez reštartu;
`input_number.simona_pc_pouzite` prežilo reload s hodnotou 34. Zvyšok fázy 0
(odvodený senzor prezencie, prepis tiku, ACK pri vypínaní) nasadený **nie je**.

Prvé merané `lag_max` je 39 s.

---

## 4. Riešenie

**Princíp: prezencia prestane byť zapamätaná hodnota a stane sa funkciou veku
dvoch časových značiek. Účtovanie sa nedotkne, ale prestane sa dať vynulovať.
Agent prestane robiť prácu v ceste HTTP odpovede.**

Kód je hotový a v repozitári. Nasadený **nie je** — čaká na tvoje slovo.

- `ha/packages/patch-prezencia.py` — celá strana HA, idempotentný patch.
- `agent/patch-agent-1.1.0.py` — agent 1.0.0 → 1.1.0.
- `agent/tests/state-test.ps1` a `agent/tests/tick-test.ps1` — 40 testov,
  všetky prechádzajú (`pwsh -File ...`).

### 4.1 Strana Home Assistanta

| Značka | Zmena | Číslo a prečo práve ono |
|---|---|---|
| H1 | nový `binary_sensor.simona_pc_sedi` | kontakt < **150 s** = tolerancia práve jedného strateného tiku (pri perióde 60 s je obnova po jednom výpadku o T+120 s, po dvoch až o T+180 s); zámerne menej než 300 s okno senzora „online", aby nikdy nevznikol stav „sedí pri PC, ktorý sa nehlási". Vstup < **240 s**: najdlhšia medzera medzi napočítanými minútami vnútri súvislého hrania bola 179,9 s, prah 180 s by tam padal náhodne podľa latencie. |
| H2 | prepis akcií tiku | kontakt sa zapisuje **vždy**, vstup **pred** spotrebou, spotreba je v rámci dňa monotónna (výnimka 00:00–00:10, keď agent už resetoval a HA ešte nie) |
| H2b | horná poistka na skok spotreby | `floor(odstup/60) + 2` minút, a nikdy viac, než ubehlo od polnoci. Overené na 138 zmenách zo 6. 9.: neodmietlo by ani jednu, vrátane legitímneho skoku +19 po slepom okne. Konštanta by nefungovala — musí to byť funkcia odstupu. |
| H3 | `used_min` v payloade, `allowed` cez `int(-1)` | seed pre agenta po strate stavu; „-1" nevyhovie regexu agenta, takže si podrží posledný známy strop |
| H4 | timeout 8 → **20 s** | doložené čakania vo fronte 12–14 s; horná hranica je perióda tiku 60 s pri `mode: single`, takže tretina periódy je bezpečná. Precedens: `pc_cmd` má 25 s. |
| H5 | backoff podľa veku kontaktu < **600 s** | dvojnásobok hysterézie senzora „online"; prvých 10 minút po strate kontaktu je ešte reálne, že PC žije. Cena: sedem pokusov o spojenie navyše na jedno vypnutie PC. |
| H6 | vypínanie po limite | hrana `online` odhlučnená cez `for: 5 s`, poistný `time_pattern /5`, `msg` → `notify`, **snímka len po potvrdení od agenta (ACK)**, neúspešný pokus sa eviduje zvlášť a opakuje sa najskôr o 10 minút |
| H7 | polnoc | snímka režimu „bez limitu" ostáva platná, keď režim pokračuje cez polnoc |
| H8 | koniec režimu bez limitu | vetva pre `raw < snap`, aby sa offset neprepočítal do nezmyslu |
| H9 | nové helpery | `simona_pc_vstup`, `simona_pc_ticho`, `simona_pc_vypnutie_pokus`, `simona_pc_latencia`, `simona_pc_lag_max`, counter `simona_pc_skok_zamietnuty` |
| H10 | tri nové automatizácie | „PC offline → zhasnúť používa sa", „PC sa prestal hlásiť" (Telegram po 10 min offline = 15 min úplného ticha), „PC hlási nedôveryhodnú spotrebu" |

**Prečo ACK a nie senzor „online".** Senzor je len test veku kontaktu, takže
za realitou mešká takmer päť a pol minúty (§2.3). Agent na príkaz `shutdown`
odpovedá HTTP 200 s `{"ok":true,...}` a `rest_command` vie odpoveď vrátiť do
`response_variable`. Snímka sa preto zapíše len vtedy, keď vypnutie naozaj
odišlo; inak zostáva na −1 a ide správa „vypnúť sa nepodarilo, skúsim znova".

**Čo tá istá zmena zámerne nerobí.** Podmienka
`has_value('sensor.simona_pc_povolene')` v tiku **nie je** — zastavila by celý
beh, teda aj zápis kontaktu a vstupu, vždy keď na chvíľu vypadnú minúty
tabletu (v čase výskumu na 31 s dáta z Family Link, dnes ich dodáva most
TimeLimit). Nedostupný strop rieši `allowed: -1` na oboch stranách.

### 4.2 Agent 1.1.0

| Značka | Zmena |
|---|---|
| A1 | tick odpovedá **zo snímky**, bez akéhokoľvek I/O. Prevzatie stropu a seedu je pred odpoveďou zámerne: pri už zavretom spojení by výnimka preskočila zvyšok a agent by ostal na starom strope. |
| A2 | bezpodmienečný `Invoke-Tick` po každom requeste zrušený (len keď od posledného ubehlo 20 s). Presnosť účtovania sa nemení — `elapsed` sa počíta z hodín, nie z počtu volaní. |
| A3 | `Invoke-Tick` plní snímku (`ts`, `used`, `active`, `idle`, `valid`), počíta neorezané meškanie slučky a drží jeho **denné** maximum |
| A4 | `Save-State`: `FileStream` + `Flush($true)`, `.bak` až po overenom zápise, škrtenie na 60 s (`-Force` pre kritické zápisy). `Load-State`: kontrola prázdneho súboru, povinných polí a rozsahu, fallback na `.bak`, poškodený súbor sa odkladá ako `.bad-<čas>`. |
| A5 | `RunScript` dočítava stderr (bez toho deadlock pri viac než 4 kB), timeout 15 → 6 s, `shutdown` a `restart` idú fire-and-forget |
| A6 | seed z HA: len po skutočnej strate stavu, len raz, len do 10 minút od štartu, len nahor a najviac po „koľko minút dnes ubehlo" |
| A7 | log: riadok na každý tik → hodinový súhrn |
| A9 | agent hlási svoju verziu (kontrola po aktualizácii z OMV) |

Nové polia v odpovedi na tick: `idle_sec`, `age_sec`, `needs_seed`, `lag_max`,
`version`. Popis je v `docs/AGENT.md`.

**Čo sa zámerne nemení:** vzorec účtovania `max(0, elapsed − idleSec)` a prah
60 s. Tvoja požiadavka „keď nehýbe myšou a nepíše, čas sa neráta" platí ďalej,
doslova. Prezencia je oddelený signál. Nemení sa ani model bez blokovania,
ani cesta na TV a k limitu tabletu (vtedy Family Link, dnes TimeLimit), ani
bezpečnostný model agenta.

### 4.3 Odhad dopadu na PC

| Veličina | Dnes | Po zmene |
|---|---|---|
| `Invoke-Tick` za minútu | 4 | 3 |
| zápisy `state.json` | asi 5 za minútu, bez flushu | najviac 1 za minútu, 0 v nečinnosti, s flushom |
| riadky v `agent.log` | jeden na každý tik | asi 30 za deň |
| cesta HTTP odpovede | 22–115 ms v kľude, plus celá práca tiku | jednotky ms po vybratie requestu z fronty |
| RAM | 26–29 MB | bez zmeny (žiadny nový modul) |

Pridané náklady: jeden `Flush` na 188 bajtov raz za minútu a jedno kopírovanie
zálohy. Nič iné.

**Výhrada, ktorú netreba prehliadnuť:** práca presunutá **za** odpoveď beží
stále na tom istom vlákne. Dlhý stall sa preto premietne do oneskoreného
vybratia **nasledujúceho** requestu — jeden tik môže vypadnúť aj po tejto
zmene. Úplne to odstráni až presun práce na iné vlákno, čo je mimo rozsahu.

---

## 5. Alternatívy, ktoré prehrali

- **Push z agenta na webhook HA.** Koncepčne najsilnejšie, ale nerieši ani
  jednu z troch koreňových príčin a pridáva na detský počítač trvalé TLS
  spojenie, nové tajomstvo a zápis do `hosts`. Prevzal som z neho seed
  handshake, zálohu až po overenom zápise a fakt, že 8 s nie je posvätných.
- **Prezencia z Windows signálov bez vstupu.** Pokryla by pasívne video, ale
  sémantika `SystemExecutionState` nie je istá a `SHQueryUserNotificationState`
  pre bežné okno prehliadača nezaberie. Stálo by to druhý `Add-Type` a viac
  prebudení slučky.
- **Len zdvihnúť prah nečinnosti na 180 s a pridať hranový watchdog.**
  Najmenší zásah, ale prezencia ostáva uložená bodová vzorka a hranový
  watchdog neopraví stav, ktorý je zamrznutý už predtým — presne to, čo si
  6. 9. opravoval ručne.
- **Zdvihnúť len timeout.** Lacné, ale nerieši ani zamrznutie, ani blikanie.
  Zostáva ako súčasť riešenia, nie ako riešenie.

---

## 6. Ako to nasadiť a ako to otestovať

### 6.1 Poradie fáz

| Poradie | Fáza | Čo sa deje | Podmienka postupu |
|---|---|---|---|
| 1 | **0** | helpery a senzor `simona_pc_sedi`, konzumenti ostávajú na starom | konfigurácia prejde kontrolou |
| 2 | **0b** | tik zapisuje značku vstupu vrátane náhradného signálu; senzor beží naslepo, nikto ho nekonzumuje | 48 h merania |
| 3 | **1b** | agent **1.1.0** | v trase tiku je vidieť pole `idle_sec` |
| 4 | **0c** | prepnutie konzumentov: podmienka v „PC po vyčerpaní času" a dlaždica na dashboarde | kritériá zmerané na dátach z 1.1.0 |

**Toto poradie nie je kozmetika.** Pri dnešnom agentovi 1.0.0 by prepnutie
konzumentov znamenalo, že trojminútové upozornenie po limite prestane chodiť
**úplne a bez chyby v logu** — značka vstupu by sa nemala z čoho posúvať.
Preto je v YAML na tom mieste komentár a podmienka ostáva stará.

Aby senzor niečo ukazoval už vo fáze 0b, má tik **náhradný signál**: pri starom
agentovi je jediným dôkazom prítomnosti **rast počtu napočítaných minút** — a
tie rastú len zo skutočného vstupu. Zneplatniť značku („nikto tu nie je") smie
len nový agent; starý mlčí a značka sa nechá dobehnúť sama.

### 6.2 Testy, ktoré nič nemenia

- **T0 — základ pred zmenou.** Rozdelenie latencie a medzier z histórie
  kontaktu za 48 h, počty chýb v `system_log` aj s časom prvého a posledného
  výskytu, trasy tiku. Na PC len čítacie príkazy; výstupy uložiť, inak ostanú
  čísla z PC navždy neoveriteľné.
- **T1 — suchý beh šablón.** Už prebehol: všetkých šesť vetiev nového tiku
  som prerenderoval proti živému HA (starý agent bez `idle_sec`, nový agent
  aktívny aj nečinný, strata stavu, divoký skok). Žiadna nevyhodila výnimku,
  divoký skok bol správne odmietnutý.
- **T2 — tieňové pozorovanie 48 h.** Merať sa dá až od fázy 0b a naozaj
  vypovedajúce je až na dátach z agenta 1.1.0. Kritériá: p95 latencie < 2 s;
  `sedi` nikdy ON dlhšie než 5 minút po tom, čo `online` prejde na off; počet
  prepnutí `sedi` aspoň päťkrát nižší než počet prepnutí surovej vzorky;
  `pouzite` počas dňa ani raz neklesne; žiadna epizóda dlhšia než 10 minút,
  kde `sedi` svieti a `pouzite` nerastie.
- **T7 — regresia účtovania, 7 dní.** Denne porovnať `pc_pouzite` v HA proti
  `usedSeconds` v `state.json` čítanom cez ssh. Kritérium: rozdiel do 1 minúty,
  žiadny pokles v rámci dňa.

### 6.3 Testy, ktoré vyžadujú tvoj súhlas

**Poradie je záväzné:** `bez_limitu` sa smie použiť ako testovacia poistka až
po nasadení monotónnosti a vetvy `raw < snap` — jeho zapnutie a vypnutie
spúšťa presne tú aritmetiku, ktorá raz stála 150 minút.

- **T3 „Prezencia" (~12 min).** Dve minúty pohyb myšou, tri minúty ruky preč,
  minúta pohyb, potom odídeš. Očakávam: `sedi` svieti súvislo vrátane
  trojminútovej pauzy a zhasne najneskôr o 10:00; surová vzorka naopak v pauze
  zhasne; `pouzite` narastie asi o 3 minúty, nie o 6.
- **T4 „Záťaž" (~15 min).** Spustíš presne tú hru, ktorú hrá Simona, a hráš.
  Kritériá: nula zhasnutí `sedi` počas súvislého hrania, p95 pod 2 s, prírastok
  CPU agenta pod 100 ms/min. Toto je jediný test, ktorý vie potvrdiť alebo
  vyvrátiť vplyv priority — a jediná šanca chytiť tie dva nevysvetlené stally.
- **T5 „Strata napájania".** Tvrdý reset počas používania. Overí sa, že
  `agent.log` neobsahuje `necitatelny` bez následného „obnovené zo zálohy", že
  existujú `state.json` aj `.bak`, a že `pc_pouzite` v HA neklesne. Ak nechceš
  tvrdý reset, bežný reštart overí rotáciu zálohy, ale nie odolnosť voči
  výpadku.
- **T6 „Vypnutie po limite".** Jediný test, ktorý naozaj vypne PC. Vyžaduje tvoju
  prítomnosť. Aby počas neho nešlo nič na TV, treba pridať jeden helper
  `input_boolean.simona_test_rezim` a jednu podmienku ako prvý krok skriptu
  `simona_tv_oznam`.
  **Dôkaz „na TV nešlo nič" musí byť z trasy skriptu**, nie z `last_triggered`
  — ten sa nastaví aj vtedy, keď beh hneď zastaví prvá podmienka.

### 6.4 Návrat

Fáza 0 sa vracia jedným `git checkout` a reloadom, do minúty, bez zásahu do PC.
Staré entity sa zapisujú ďalej, takže návrat je bezstratový. Agent sa vracia
cez aktualizačný kanál (`Update-PcAgent.ps1` má zálohu aj poistku proti
cyklu pádov) — ale **ten kanál na PC ešte nie je zapnutý**, viď otázka 5.

---

## 7. Otvorené otázky

1. **Má prezencia svietiť pri pasívnom pozeraní videa** (viac než štyri minúty
   bez dotyku myši)? Návrh hovorí nie. Ak áno, je to jedno číslo v šablóne —
   ale nikdy nie viac než 300 s, inak by prezencia prežila senzor „online".
2. **Sedí okno 240 s pre Simonu?** Je odvodené z jedného pozorovaného dňa. Ak
   má pri hraní pravidelne dlhšie pauzy, zdvihneme ho.
3. **Súhlasíš s testovacím režimom pre T6** (jeden helper a jeden riadok
   v skripte pre TV)? Bez neho sa vypínanie po limite nedá otestovať bez toho,
   aby na televízor niečo išlo.
4. **Súhlasíš s testom T5** (tvrdý reset napájania počas používania)? Je to
   jediný spôsob, ako naozaj overiť opravu straty stavu. Bez neho oprava
   ostane neoverená a bude čakať na ďalší skutočný výpadok.
5. **Zapneme na PC aktualizačný kanál?** Sú to tri zápisy: prepnúť akciu úlohy
   na `Update-PcAgent.ps1`, doplniť `UpdateUrl` a `UpdateKey` do `config.json`
   a položiť súbor `VERSION`. Bez toho sa agent nasadí ručným patchom a
   **rollback je potom výlučne ručný**.
6. **Defender `ExclusionPath`** pre adresár so stavom — áno alebo nie? Znížilo
   by cenu každého zápisu, ale je to oslabenie ochrany na počítači dieťaťa.
   Rozhodnutie je tvoje, riešenie bez neho funguje.
7. **Prah upozornenia „PC sa prestal hlásiť"** = 10 minút offline a okno
   07:00–21:00 — sedí? Pri týchto hodnotách by 6. 9. prišla práve jedna správa,
   presne na tú poruchu.

---

**Bokom, ako samostatné úlohy:** token agenta je v `pc_control.yaml`
v otvorenom texte, nie cez `!secret`. A staré automatizácie `/pridat_30`,
`/pridat_60` a víkendový režim v čase výskumu zapisovali priamo do Family
Linku, kde ich sync prepísal — buď ich zrušiť, alebo prepnúť na `/cas_add`.
*(Stav k 4. 10. 2026: Family Link je preč. Tlačidlá +30/+60 v menu „Simonka
Tablet" pridávajú do spoločného rozpočtu — pri vypnutom zdieľaní priamo ako
extra čas v TimeLimit — a prázdninová/víkendová ponuka nastaví spoločný
rozpočet na 150 min.)*
