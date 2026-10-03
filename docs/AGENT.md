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

Agent sa **neprepisuje**. Dopĺňa sa doň jedna nová akcia a vynucovanie; jeho
doterajší lokálny limit prestáva byť autoritou, lebo účet teraz vedie Home
Assistant.

## Nová akcia `tick`

Home Assistant ju volá každú minútu (keď je PC offline, raz za päť minút):

```json
{"token": "<token>", "action": "tick", "args": "<povolené minúty na dnes>", "used_min": 154}
```

Odpoveď musí obsahovať aspoň `used`:

```json
{"used": 42, "active": true, "allowed": 120, "idle_sec": 12, "age_sec": 3,
 "needs_seed": false, "lag_max": 0, "version": "1.1.0"}
```

| Pole | Význam |
|---|---|
| `used` | Minúty **skutočne odsedené dnes pri PC**. Toto je jediné číslo, ktoré HA preberá. |
| `active` | Surová vzorka agenta: bol vstup mladší než 60 s v okamihu posledného merania? Od verzie 1.1.0 je to naozaj **len diagnostika** — prezenciu si HA odvodzuje sám z `idle`/`age`. |
| `allowed` | Echo prijatého stropu (nepovinné, na kontrolu). |
| `idle_sec` | Sekundy od posledného dotyku myši alebo klávesnice v okamihu merania. |
| `age_sec` | Koľko sekúnd staré je to meranie. HA z dvojice počíta čas posledného vstupu: `teraz − idle_sec − age_sec`. Obe polia chýbajú, kým agent nemá platnú snímku (napr. hneď po štarte) — vtedy si HA nechá predošlú značku. |
| `needs_seed` | `true` = agent prišiel o svoj stav a čaká, kým mu HA v `used_min` vráti dnešnú spotrebu. |
| `lag_max` | Najväčšie meškanie tiku **za dnešok**, v sekundách; 0 je normál. Denné maximum zámerne: práve tik s veľkým meškaním najčastejšie padne na timeout, takže hodnota „od posledného ticku“ by sa stratila. Nuluje sa pri zmene dňa, HA si drží `max(vlastná hodnota, hlásená)`. |
| `version` | Verzia agenta zo súboru `VERSION` — kontrola po aktualizácii z OMV. |

**`used_min` je pole POŽIADAVKY, nie odpovede.** Sú to minúty, ktoré si o
dnešku pamätá Home Assistant (`input_number.simona_pc_pouzite`, surová hodnota
pred prepisom). Agent ich prevezme **len keď mu vlastný stav chýba**
(`needs_seed`), prevezme ich **raz**, len do 10 minút od svojho štartu, len
smerom nahor a najviac po hodnotu „koľko minút dnes vôbec ubehlo". Tá istá
horná zábrana beží aj na strane HA. `-1` znamená „HA hodnotu nemá".

`args` je strop pre celý dnešný deň, nie zostatok. Agent teda vynucuje pri
`used >= allowed`.

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
  po polnoci sa nuluje. HA si ho o 00:05 nuluje tiež, takže obe strany
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

Preto agent hlási v ticku aj `active` — bez neho by HA vedel len to, že PC je
zapnutý, nie že pri ňom naozaj niekto je.

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
- **`needs_seed`.** Keď ani záloha nepomôže, agent to v ticku prizná a HA mu
  v `used_min` vráti dnešnú spotrebu.

Na strane HA je poistka nezávislá od agenta: `input_number.simona_pc_pouzite`
je **v rámci dňa monotónny** — pokles sa ignoruje (okrem prvých desiatich
minút po polnoci, keď agent deň resetuje skôr než HA).

## Stav: hotové a overené

Zmeny sú v agentovi nasadené (`patch-agent.ps1`, idempotentný, so zálohou
`PcAgent.ps1.bak-*` a kontrolou syntaxe pred zápisom). Overené naživo:

```
tick 60  ->  {"used":7,"active":false,"allowed":60,"ok":true}
```

a Home Assistant tých 7 minút prevzal a znížil limit tabletu vo Family Link
zo 60 na 53 minút.

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
