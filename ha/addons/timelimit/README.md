# TimeLimit Server – add-on pre Home Assistant

Self-hostovaný server pre [TimeLimit](https://timelimit.io) (open-source
rodičovský dohľad pre Android) bežiaci priamo v Home Assistante ako lokálny
add-on. Nahrádza samostatný LXC 123 na `pve`, ktorý sa predtým zrušil.

**Stav: server beží, appka zatiaľ nikde nie je nasadená.** Simonkin tablet
ostáva na Family Linku, kým sa TimeLimit neoverí na náhradnom zariadení.

## Kde to beží

| | |
|---|---|
| Add-on | `local_timelimit` (TimeLimit Server), súbory v `/addons/timelimit/` na HA |
| API | `http://192.168.1.102:8080` — overenie: `curl .../time` vráti `{"ms":…}` |
| Maily | `http://192.168.1.102:8025` (Mailpit) |
| Databáza | add-on **MariaDB** (`core-mariadb`), databáza a používateľ `timelimit` |
| Dáta | `/data/mailpit.db` v add-one; všetko ostatné je v MariaDB |

Add-on je jeden kontajner s dvoma procesmi: TimeLimit server (node) a Mailpit
(statická Go binárka prekopírovaná z jeho image). Mailpit tam je preto, že
TimeLimit posiela rodičovi prihlasovacie kódy mailom — bez SMTP by sa nedalo
ani zaregistrovať. Server posiela na `127.0.0.1:1025`, kód si prečítaš na
porte 8025 a von z domu nič nechodí.

Keď ktorýkoľvek z dvoch procesov spadne, `run.sh` zhodí aj druhý a kontajner
skončí — Supervisor (watchdog na `/time`) ho reštartuje.

### Prečo nie ingress pre Mailpit

Mailpit má v HTML absolútne cesty (`/dist/app.js`, `data-webroot="/"`) a
Supervisor pri ingresse prefix odstrihne, takže by sa assety nenačítali.
`MP_WEBROOT` by zas rozbil priamy prístup na porte 8025. Ostáva teda port.

## Databáza

Používa sa existujúci add-on MariaDB (ten, kde má HA recorder). V jeho
options je pridané:

```yaml
databases: [homeassistant, timelimit]
logins:    [{username: timelimit, password: <heslo>}, …]
rights:    [{username: timelimit, database: timelimit}, …]
```

Databáza aj používateľ boli vytvorení hneď cez `mariadb` v kontajneri, aby sa
MariaDB nemusel reštartovať (recorder by na chvíľu vypadol). Options zaručujú,
že po reštarte MariaDB ostane všetko tak, ako je. **Rovnaké heslo** je v
options add-onu TimeLimit (`db_password`); žije len na HA, do gitu nepatrí.

## Tri chyby v oficiálnom image, ktoré sa obchádzajú

Image `ghcr.io/michaelsp/timelimit-server/timelimit` sám od seba
**nenabehne**:

1. **`latest` je rozbitý.** Spadne pri štarte na
   `SyntaxError: Named export 'InternalServerError' not found` — ESM/CommonJS
   konflikt v `http-errors`. Preto je verzia pinnutá na **`v1.17.0`**.
2. **`DATABASE_URL` sa ignoruje.** v1.17.0 číta samostatné `DB_DRIVER`,
   `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`. Bez `DB_DRIVER` ticho
   spadne na `sqlite://test.db`. `run.sh` ich skladá z options add-onu.
3. **Migrácie sa nikdy nespustia** (`patches/umzug.js`): glob hľadá
   `src/…/*.ts`, kým v image sú skompilované `build/…/*.js`; a sú písané pre
   umzug v2, zatiaľ čo v image je umzug 3.3.1. Opravený súbor sa v Dockerfile
   prekopíruje cez pôvodný.

Po oprave prejde všetkých 100 migrácií, vznikne 24 tabuliek a log končí
`ready`. Overené aj odoslanie kódu: `POST /auth/send-mail-login-code-v2`
vráti `mailLoginToken` a mail „Sign in at TimeLimit" sa objaví v Mailpite.

## Správa add-onu

```sh
ha apps logs local_timelimit          # log
ha apps restart local_timelimit
ha store reload && ha apps rebuild local_timelimit   # po zmene Dockerfile/run.sh
```

Po zmene súborov v `/addons/timelimit/` zvýš `version` v `config.yaml` —
Supervisor rebuilduje len pri zmene verzie (alebo ručne `ha apps rebuild`).
Kópia v repe a na HA majú mať rovnaký md5.

## Čo ďalej

1. **Test na náhradnom zariadení** (starý telefón, *nie* Simonkin tablet):
   nainštalovať [TimeLimit z F-Droidu](https://f-droid.org/en/packages/io.timelimit.android.aosp.direct/),
   pri nastavení zvoliť vlastný server `http://192.168.1.102:8080`, založiť
   rodinu, prihlasovací kód prečítať v Mailpite.
2. Po založení rodiny zapnúť `disable_signup`, nech si na serveri nikto cudzí
   nič nezaloží.
3. Ak má appka fungovať aj mimo domu: pridať `timelimit.fabrici.xyz` do Caddy
   (LXC 116) smerujúce na `192.168.1.102:8080`, alebo ísť cez headscale VPN.
4. Overiť, či limity a blokovanie fungujú tak, ako treba — až potom riešiť
   napojenie na zdieľaný rozpočet v HA.

## Napojenie na Home Assistant (zatiaľ neurobené)

Server nemá REST API pre tretie strany, má sync protokol pre svoju appku.
Použiteľné endpointy:

| Endpoint | Na čo |
|---|---|
| `POST /sync/pull-status` | čítanie stavu vrátane spotrebovaného času |
| `POST /sync/push-actions` | zápis zmien (limity, bonus) |
| `POST /auth/send-mail-login-code-v2`, `/auth/sign-in-by-mail-code` | prihlásenie |
| `GET /time` | kontrola dostupnosti |

Napojenie teda bude podobné reverzné inžinierstvo ako dnešná Family Link
integrácia — s tým zásadným rozdielom, že protokol sa mení až vtedy, keď server
aktualizuješ ty.
