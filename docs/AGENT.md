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

## Vynucovanie a varovania

Podľa zadania: najprv upozorniť hlasom aj textom, až po poslednom upozornení
**uspať počítač**. Použiť už existujúce mechanizmy agenta (`speak` pre TTS,
`msg` pre notifikáciu, `sleep` pre uspanie):

| Zostatok | Čo agent urobí |
|---|---|
| 30 min | text |
| 15 min | text + hlas |
| 5 min | text + hlas |
| 1 min | text + hlas („posledná minúta, ulož si to") |
| 0 | uspanie počítača (`sleep`) |

Uspanie je zvolené zámerne namiesto odhlásenia: rozrobená práca zostáva v
pamäti, takže sa nič nestratí. Preto musí posledné varovanie prísť dosť
zavčasu, aby si stihla uložiť, čo robí.

### Po prebudení

Uspaním sa nič nekončí — dieťa vie PC zobudiť tlačidlom, takže agent musí po
prebudení stav prehodnotiť:

- **čas medzitým pribudol** (rodič dal `/cas_add`, alebo je nový deň) →
  pokračuje sa normálne, meranie beží ďalej;
- **čas stále nie je** → agent to oznámi hlasom aj textom, dá **jednu minútu
  odklad** (nech sa dá uložiť rozrobené) a uspí znova.

Ten odklad je dôležitý, inak by sa PC uspával v slučke hneď po každom
prebudení. Minúty počas odkladu sa už do spotreby nerátajú.

## Odolnosť voči výpadku HA

Agent si posledný prijatý strop pamätá. Keď HA prestane volať:

- strop platí ďalej a agent vynucuje podľa neho — dieťa teda nezíska
  neobmedzený čas vypnutím Home Assistanta,
- po obnovení spojenia HA prevezme `used` z agenta, takže sa nič nestratí.

## Zostáva overiť po zapnutí PC

1. Prečítať zdroják existujúceho agenta (`ssh winpc`) a zistiť, ako drží
   doterajší limit a ako sú spravené `speak` / `msg`.
2. Doplniť `tick`, meranie a vynucovanie.
3. Otestovať: umelo znížiť rozpočet (`/cas_set`) a overiť varovania i zámok.
4. Overiť, že sa počítadlo po polnoci naozaj vynuluje.
