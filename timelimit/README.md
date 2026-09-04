# TimeLimit.io — vlastný server

Self-hostovaná náhrada Google Family Link. Cieľom je prestať závisieť na
neoficiálnom API Googlu, na ktorom dnes stojí zdieľanie času s PC.

**Stav: server beží, appka zatiaľ nikde nie je nasadená.** Simonkin tablet
ostáva na Family Linku, kým sa TimeLimit neoverí na náhradnom zariadení.

## Kde to beží

| | |
|---|---|
| Kontajner | LXC **123** `timelimit` na `pve`, Debian 12, 2 GB RAM, 8 GB disk |
| Adresa | `192.168.1.249` |
| API | `http://192.168.1.249:8080` — overenie: `curl .../time` vráti `{"ms":…}` |
| Maily | `http://192.168.1.249:8025` (Mailpit) |
| Súbory | `/opt/timelimit/` — compose, `.env` (heslá, `chmod 600`), `patches/`, `database/` |

Mailpit tam je preto, že TimeLimit posiela rodičovi prihlasovacie kódy mailom.
Bez SMTP by sa nedalo ani zaregistrovať; takto kód jednoducho prečítaš vo
webovom rozhraní na porte 8025 a von z domu nič nechodí.

`ALWAYS_PRO=yes` — na vlastnom serveri sú prémiové funkcie odomknuté.

## Dve chyby v oficiálnom image, ktoré bolo treba obísť

Image `ghcr.io/michaelsp/timelimit-server/timelimit` sám od seba **nenabehne**.
Stálo to väčšinu času nasadenia, tak nech je to zapísané:

1. **`latest` je rozbitý.** Spadne hneď pri štarte na
   `SyntaxError: Named export 'InternalServerError' not found` — ESM/CommonJS
   konflikt v `http-errors`. Preto je verzia pinnutá na **`v1.17.0`**.

2. **`DATABASE_URL` sa ignoruje.** Dokumentovaný `docker-compose.yaml` v repe
   projektu ju používa, ale v1.17.0 číta samostatné `DB_DRIVER`, `DB_HOST`,
   `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`. Bez `DB_DRIVER` ticho spadne na
   `sqlite://test.db` a potom padá na chýbajúce tabuľky — vyzerá to ako problém
   s databázou, pritom sa na ňu vôbec nepripája.

3. **Migrácie sa nikdy nespustia** (`patches/umzug.js`). Sú dva dôvody naraz:
   glob hľadá `src/…/*.ts`, kým v image sú skompilované `build/…/*.js`; a keď
   sa už nájdu, sú písané pre umzug v2 (`up(queryInterface, sequelize)`), zatiaľ
   čo v image je umzug 3.3.1, ktorý volá `up({ context })`. Opravený súbor sa do
   kontajnera len primountuje, image ostáva nedotknutý.

Po oprave prejde všetkých 100 migrácií, vznikne 24 tabuliek a log končí `ready`.

## Čo ďalej

1. **Test na náhradnom zariadení** (starý telefón, *nie* Simonkin tablet):
   nainštalovať [TimeLimit z F-Droidu](https://f-droid.org/en/packages/io.timelimit.android.aosp.direct/),
   pri nastavení zvoliť vlastný server `http://192.168.1.249:8080`, založiť
   rodinu, prihlasovací kód prečítať v Mailpite.
2. Overiť, či limity a blokovanie fungujú tak, ako treba.
3. Až potom riešiť napojenie na zdieľaný rozpočet v HA.

## Napojenie na Home Assistant (zatiaľ neurobené)

Server nemá REST API pre tretie strany, má sync protokol pre svoju appku.
Použiteľné endpointy:

| Endpoint | Na čo |
|---|---|
| `POST /sync/pull-status` | čítanie stavu vrátane spotrebovaného času |
| `POST /sync/push-actions` | zápis zmien (limity, bonus) |
| `POST /auth/…`, `/sign-in-by-mail-code` | prihlásenie |
| `GET /time` | kontrola dostupnosti |

Napojenie teda bude podobné reverzné inžinierstvo ako dnešná Family Link
integrácia — s tým zásadným rozdielom, že protokol sa mení až vtedy, keď server
aktualizuješ ty.
