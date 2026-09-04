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
{"token": "<token>", "action": "tick", "args": "<povolené minúty na dnes>"}
```

Odpoveď musí obsahovať aspoň `used`:

```json
{"used": 42, "active": true, "allowed": 120, "text": "42/120 min"}
```

| Pole | Význam |
|---|---|
| `used` | Minúty **skutočne odsedené dnes pri PC**. Toto je jediné číslo, ktoré HA preberá. |
| `active` | Či práve teraz niekto pri PC reálne je (nepovinné, na diagnostiku). |
| `allowed` | Echo prijatého stropu (nepovinné, na kontrolu). |

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

## Žiadne vynucovanie na PC

**PC sa neblokuje, neuspáva ani neodhlasuje.** Zámerom je, aby sa Simonka
vedela zastaviť sama — nie aby jej v tom bránil počítač. Agent teda nikdy
nesiahne na beh systému; jediné, čo robí, je že **meria a hlási**.

Vynucovanie zostáva len na tablete, kde ho robí sám Family Link.

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

Nič na PC. Zareaguje Home Assistant, a to len upozornením rodičom
(automatizácia `Simona čas: PC po vyčerpaní času`):

- **prekrytie na TV** cez `notify.tvoverlaynotify`,
- **správa Jakubovi** do Telegramu.

Spúšťa sa, keď po vyčerpanom čase PC nabehne alebo pri ňom začne pracovať, a
kým pri ňom sedí, pripomenie sa najviac raz za pol hodinu. Preto agent hlási
v ticku aj `active` — bez neho by HA vedel len to, že PC je zapnutý, nie že
pri ňom naozaj niekto je.

Minúty nad rámec rozpočtu sa počítajú ďalej, takže v prehľade (`/cas`) je
vidieť, o koľko bol limit prekročený.

## Odolnosť voči výpadku HA

Agent si posledný prijatý strop pamätá, takže vie varovať aj keď Home
Assistant nebeží. Po obnovení spojenia HA prevezme `used` z agenta, takže sa
nič nestratí.

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
