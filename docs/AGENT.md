# Windows agent — čo sa doňho dopĺňa

Na PC (`192.168.1.104`, používateľ `kuko`) beží agent na porte **8799**, ktorý
už dnes obsluhuje `POST /cmd` s telom:

```json
{"token": "<token>", "action": "<akcia>", "args": "<text>", "delay": 5}
```

a odpovedá JSONom, z ktorého Home Assistant číta `text` (a `shot` pri
screenshote). Používajú ho tieto akcie z Telegram menu: `status`, `screenshot`,
`lock`, `sleep`, `logoff`, `shutdown`, `restart`, `cancel`, `speak`, `msg`,
`volume`, `mute`, `unmute`, `usage`, `limit_get`, `limit_set`, `addtime`,
`block`, `unblock`.

Agent sa **neprepisuje**. Dopĺňa sa doň hlásenie do HA, akcia `tick` a
varovania; jeho doterajší lokálny limit prestáva byť autoritou, lebo účet
teraz vedie Home Assistant.

## Hlásenie do HA (od verzie 1.2.0) — hlavná cesta

Agent sám **každých 30 s** (a hneď, keď sa zmení `active`) pošle `POST` na
webhook Home Assistanta. Celá adresa je v `config.json` na PC ako `PushUrl`
(id webhooku je v HA v `secrets.yaml` ako `simona_pc_webhook`; webhook
prijíma len z LAN). Telo:

```json
{"used": 18, "active": true, "allowed": 105, "idle_sec": 3, "age_sec": 0,
 "version": "1.2.1", "needs_seed": false, "lag_max": 0}
```

Polia znamenajú to isté ako v odpovedi na `tick` (tabuľka nižšie). Prijíma
ho automatizácia `simona_cas_pc_hlasenie`: zapíše kontakt, značku vstupu
`input_datetime.simona_pc_vstup` (ešte pred spotrebou),
`input_boolean.simona_pc_pouziva_sa` podľa `active`, spotrebu len hodnovernú
a v rámci dňa len smerom nahor (zamietnuté skoky ráta
`counter.simona_pc_skok_zamietnuty`) a `lag_max`. Strop
`sensor.simona_pc_povolene` pošle agentovi späť akciou `limit_set` cez
`/cmd` **len vtedy, keď sa líši** od `allowed` v hlásení — v ustálenom stave
smerom k PC nechodí nič. Keď to zlyhá, agent si drží posledný strop a HA ho
skúsi pri ďalšom hlásení.

## Akcia `tick` — záložná cesta

Home Assistant ju volá (`simona_cas_pc_tick`) každú minútu, ale **len keď
hlásenie nechodí viac ako 150 s** — teda keď je agent starý, zle nastavený
alebo zaseknutý. Keď kontakt chýba viac ako 10 minút (PC je vypnuté), skúša
to len raz za päť minút. Požiadavka dnes:

```json
{"token": "<token>", "action": "tick", "args": "<povolené minúty na dnes>"}
```

Odpoveď musí obsahovať aspoň `used`:

```json
{"used": 42, "active": true, "allowed": 120, "idle_sec": 12, "age_sec": 3,
 "needs_seed": false, "lag_max": 0, "version": "1.2.1"}
```

| Pole | Význam |
|---|---|
| `used` | Minúty **skutočne odsedené dnes pri PC**. Toto je jediné číslo, ktoré HA preberá. |
| `active` | Surová vzorka agenta: bol vstup mladší než 60 s v okamihu posledného merania? HA z neho dnes nastavuje `input_boolean.simona_pc_pouziva_sa`, od ktorého závisí upozornenie po limite. Na čistú diagnostiku sa zmení až s `binary_sensor.simona_pc_sedi` a fázou 0c (viď README, *Prezencia pri PC*). |
| `allowed` | Echo prijatého stropu (nepovinné, na kontrolu). |
| `idle_sec` | Sekundy od posledného dotyku myši alebo klávesnice v okamihu merania. |
| `age_sec` | Koľko sekúnd staré je to meranie. HA z dvojice určuje, či bol vstup čerstvý (`idle_sec` < 60 a `age_sec` < 90), a podľa toho posunie značku posledného vstupu — dnes len v hlásení; záložný tick obe polia zatiaľ ignoruje (doplní to H2 v `patch-prezencia.py`). Obe polia chýbajú, kým agent nemá platnú snímku (napr. hneď po štarte) — vtedy si HA nechá predošlú značku. |
| `needs_seed` | `true` = agent prišiel o svoj stav a čaká, kým mu HA v `used_min` vráti dnešnú spotrebu (to zatiaľ nechodí, viď nižšie). |
| `lag_max` | Najväčšie meškanie tiku **za dnešok**, v sekundách; 0 je normál. Denné maximum zámerne: práve tik s veľkým meškaním najčastejšie padne na timeout, takže hodnota „od posledného ticku“ by sa stratila. Agent ho nuluje pri zmene dňa, HA si drží `max(vlastná hodnota, hlásená)` (o polnoci ho zatiaľ nenuluje). |
| `version` | Verzia agenta zo súboru `VERSION` — kontrola po aktualizácii z OMV. |

**`used_min` je pole POŽIADAVKY, nie odpovede — a HA ho zatiaľ neposiela.**
Majú to byť minúty, ktoré si o dnešku pamätá Home Assistant
(`input_number.simona_pc_pouzite`). Agent ich prevezme **len keď mu vlastný
stav chýba** (`needs_seed`), prevezme ich **raz**, len do 10 minút od svojho
štartu, len smerom nahor a najviac po hodnotu „koľko minút dnes vôbec
ubehlo". `-1` znamená „HA hodnotu nemá". Agent to už vie; v HA pole do
ticku pridá až `ha/packages/patch-prezencia.py` (H3, **čaká**). Ani potom
nebude seed chodiť, kým funguje hlásenie: agent ho prijme len v akcii
`tick` a tú HA pri fungujúcom hlásení nevolá — `simona_cas_pc_hlasenie` na
`needs_seed` zatiaľ nereaguje. Kým to tak je, agent po strate stavu ráta od
nuly a HA si drží svoju vyššiu hodnotu, takže minúty odsedené po strate
stavu sa v HA prejavia až vtedy, keď ich agent prerastie.

`args` (aj `limit_set`) je strop pre celý dnešný deň, nie zostatok; čas sa
minul pri `used >= allowed`. Agent podľa neho len varuje (viď nižšie).

## Meranie času

Počítať sa má **aktívne používanie**, nie čas, keď PC len svieti:

- session musí byť odomknutá (`WTSGetActiveConsoleSessionId`, `SESSION_LOCK` /
  `SESSION_UNLOCK` cez `WM_WTSSESSION_CHANGE`, alebo prakticky
  `GetLastInputInfo`),
- **ráta sa len čas, keď sa naozaj hýbalo myšou alebo písalo**: z každého
  intervalu sa odráta, ako dlho je už ticho (`GetLastInputInfo`). Ticho celý
  interval → nepripočíta sa nič; prestala v jeho polovici → pripočíta sa
  polovica. Predtým stačil jeden pohyb myšou za minútu na to, aby sa
  pripočítal celý interval,
- **dôsledok:** pozeranie videa bez dotyku myši sa neráta,
- počítadlo je perzistentné (prežije reštart agenta aj PC) a viaže sa na dátum —
  po polnoci sa nuluje. HA si ho nuluje tiež, polnočným resetom
  (`simona_cas_polnocny_reset`) pár minút po polnoci, takže obe strany
  začínajú deň na nule.

## Vynucovanie: agent nič, vypnutie riadi HA

**Agent sám na beh systému nesiahne** — meria a hlási, nič viac. Jeho lokálny
limit už nie je autorita.

Vypnutie po vyčerpaní času robí **Home Assistant**, existujúcou akciou
`shutdown` (rovnaký kanál ako tlačidlo v Telegram menu), a to raz za deň.
Predtým dá agent hlasové aj textové varovanie a minútu na uloženie práce.
Keď PC Simonka zapne znova, už doňho nikto nesiaha — chodia len upozornenia
rodičom.

### Varovania dieťaťu

Aby sa vedela rozhodnúť, musí vedieť, koľko jej zostáva. Agent preto
upozorňuje cez už existujúce mechanizmy (`speak` pre hlas, `msg` pre text):

| Zostatok | Čo agent urobí |
|---|---|
| 30 min | text |
| 15 min | text + hlas |
| 5 min | text + hlas |
| 1 min | text + hlas („čas sa minul, dohraj to") |
| 0 | text + hlas — a **nič viac**, PC beží ďalej |

Každý stupeň sa za deň ohlási len raz a **medzi dvoma varovaniami musia
uplynúť aspoň dve minúty**. To druhé je oprava z prevádzky: strop pre PC
posiela Home Assistant a je to rozpočet mínus čas na tablete, takže keď
dieťa medzitým hrá na tablete, strop skokovo klesne. Bez odstupu odznelo
„zostáva 5 minút" a o dvadsať sekúnd „posledná minúta". Preskočené stupne
sa teraz ticho odpíšu; nula sa povie vždy.

### Čo sa stane po vyčerpaní času

`Simona čas: vypnúť PC po vyčerpaní času` pošle cez `pc_cmd`:

1. `speak` — „Simonka, čas na dnes sa minul. Počítač sa o minútu vypne…"
2. `msg` — to isté textom,
3. minúta pauzy,
4. `shutdown` s `delay: 10`.

Potom už do PC nikto nesiaha. Keď ho zapne znova a odsedí pri ňom **viac ako
3 minúty** (agentove minúty od okamihu vypnutia, nie súvislé sedenie), pošle
`Simona čas: PC po vyčerpaní času` upozornenie do Telegramu a na TV. Kým pri
ňom sedí, pripomenie sa najviac raz za pol hodinu.

Preto agent hlási (v hlásení aj v ticku) aj `active` — bez neho by HA vedel
len to, že PC je zapnutý, nie že pri ňom naozaj niekto je.

Minúty nad rámec rozpočtu sa počítajú ďalej, takže v prehľade (`/cas`) je
vidieť, o koľko bol limit prekročený.

## Odolnosť voči výpadku HA

Agent si posledný prijatý strop pamätá, takže vie varovať aj keď Home
Assistant nebeží. Po obnovení spojenia HA prevezme `used` z agenta, takže sa
nič nestratí.

Opačný smer musel byť dorobený: keď agent príde o `state.json` (strata
napájania), naštartuje s `usedSeconds = 0` a HA by ten prepad slepo prevzal.
Stalo sa to dvakrát — 28. 8. a 6. 9. 2026, druhý raz to znamenalo pokles
154 → 0 minút. Do verzie 1.0.0 vrátane bol zápis `Set-Content` + `Move-Item`
bez vynúteného zápisu na disk, takže po tvrdom reštarte ostal
neparsovateľný súbor.

Od verzie 1.1.0 sú proti tomu tri opatrenia:

- **Durabilný zápis.** `FileStream` + `Flush($true)`, potom `Move-Item` a až po
  overenom zápise kópia do `state.json.bak`. Poškodený súbor sa neprepisuje,
  ale odkladá ako `state.json.bad-<čas>`, aby zostal dôkaz.
- **Tvrdé načítanie.** Prázdny alebo biely súbor, chýbajúce povinné polia a
  nezmyselné `usedSeconds` (nad 200 000 s) sa odmietnu a skúsi sa `.bak`.
- **`needs_seed`.** Keď ani záloha nepomôže, agent to prizná (v hlásení aj
  v ticku) a HA mu má v `used_min` vrátiť dnešnú spotrebu. Strana HA ešte
  **čaká** — viď [`used_min`](#akcia-tick--záložná-cesta) vyššie.

Na strane HA je poistka nezávislá od agenta: `input_number.simona_pc_pouzite`
je **v rámci dňa monotónny** — pokles sa ignoruje (okrem prvých desiatich
minút po polnoci, keď agent deň resetuje skôr než HA). Hlásenie navyše
zamietne skok nahor, ktorý sa od posledného kontaktu nedal stihnúť
(`counter.simona_pc_skok_zamietnuty`).

## Stav: hotové a overené

Zmeny sú v agentovi nasadené (`patch-agent.ps1`, idempotentný, so zálohou
`PcAgent.ps1.bak-*` a kontrolou syntaxe pred zápisom). Overené naživo:

```
tick 60  ->  {"used":7,"active":false,"allowed":60,"ok":true}
```

a Home Assistant tých 7 minút prevzal a o toľko znížil limit tabletu zo 60 na
53 minút. (Toto overenie prebehlo ešte v čase, keď tablet riadil Family Link;
ten bol 4. 10. 2026 zo systému odstránený.) Dnes tablet riadi **TimeLimit**:
Home Assistant mu cez most posiela denný cieľ
`sensor.simona_tablet_cielovy_limit` = rozpočet − minúty z PC a PC dostáva
strop rozpočet − minúty z tabletu (od verzie 1.2.0 akciou `limit_set` po
hlásení agenta, keď sa strop zmení; v `tick` už len ako záloha). Agentovi je
jedno, odkiaľ minúty tabletu pochádzajú — verzia 1.2.1 oproti 1.2.0 len
prepisuje dva komentáre, ktoré ešte spomínali starý zdroj; správanie je
rovnaké.

Ako to v agentovi vyzerá teraz:

- `Invoke-Tick` už neblokuje podľa limitu — `$blockNow = [bool]$s.manualBlock`,
  takže blok ostáva len na výslovný pokyn rodiča (`/pc_block` z Telegramu).
- Čas sa meria ďalej aj nad rámec limitu, nech je vidieť, o koľko bol
  prekročený.
- `Invoke-Warnings` upozorní pri 30 / 15 / 5 / 1 / 0 minútach — notifikácia aj
  nahlas, každý stupeň raz za deň. Keď rodič pridá čas, varovania sa spustia
  odznova (`warnedStep` sa vráti na 9999).
- Texty sú vo `warnmsg.txt` (UTF-8, formát `minúty|text`) — v `.ps1` bez BOM by
  PowerShell 5.1 diakritiku pokazil, rovnaký trik ako pri `blockmsg.txt`.
- `warnedStep` pribudol do `state.json`, takže reštart PC varovania
  nevynuluje.

### Ostáva otestovať pri skutočnom používaní

Varovania sa ohlásia len keď pri PC naozaj niekto je (`LastActive`), takže sa
nedali overiť na diaľku pri nečinnom počítači. Otestuje sa to samo pri prvom
reálnom používaní, alebo zámerne: `/cas_set` na hodnotu tesne nad spotrebou,
potom pohnúť myšou.
