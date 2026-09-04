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
- nečinnosť dlhšia než ~3 minúty sa neráta,
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

Každý stupeň sa za deň ohlási len raz.

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

## Zostáva overiť po zapnutí PC

1. Prečítať zdroják existujúceho agenta (`ssh winpc`) a zistiť, ako drží
   doterajší limit a ako sú spravené `speak` / `msg`.
2. Doplniť `tick`, meranie aktívneho času a varovania (bez akéhokoľvek zásahu do behu PC).
3. Otestovať: umelo znížiť rozpočet (`/cas_set`) a overiť varovania aj upozornenie na TV a v Telegrame.
4. Overiť, že sa počítadlo po polnoci naozaj vynuluje.
