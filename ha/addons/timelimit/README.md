# TimeLimit Server – add-on pre Home Assistant

Self-hostovaný server pre [TimeLimit](https://timelimit.io) (open-source
rodičovský dohľad pre Android) bežiaci priamo v Home Assistante ako lokálny
add-on. Nahrádza samostatný LXC 123 na `pve`, ktorý sa predtým zrušil.

**Stav:** server beží, rodina je založená (rodič `timelimit@fabrici.xyz`,
dieťa Simonka, zariadenie iPlay 50) a **most do HA je prihlásený** – entity
v HA sú živé. Zdieľaný rozpočet (`simona_cas.yaml`) zatiaľ stále beží nad
Family Linkom; prepnutie na TimeLimit je ďalší krok (viď nižšie).

## Kde to beží

| | |
|---|---|
| Add-on | `local_timelimit` (TimeLimit Server), súbory v `/addons/timelimit/` na HA |
| API verejne | **`https://timelimit.fabrici.xyz`** — cez Caddy (LXC 116), bez VPN; toto zadávaš v appke ako vlastný server |
| API na LAN | `http://192.168.1.102:8080` — overenie: `curl .../time` vráti `{"ms":…}` |
| Maily | `http://192.168.1.102:8025` (Mailpit) — **len LAN/VPN**, von sa nevystavuje |
| Databáza | add-on **MariaDB** (`core-mariadb`), databáza a používateľ `timelimit` |
| Dáta | `/data/mailpit.db` v add-one; všetko ostatné je v MariaDB |

Add-on je jeden kontajner s tromi procesmi: TimeLimit server (node), Mailpit
(statická Go binárka prekopírovaná z jeho image) a most do HA (`bridge/bridge.js`). Mailpit tam je preto, že
TimeLimit posiela rodičovi prihlasovacie kódy mailom — bez SMTP by sa nedalo
ani zaregistrovať. Server posiela na `127.0.0.1:1025`, kód si prečítaš na
porte 8025 a von z domu nič nechodí.

Keď ktorýkoľvek z troch procesov spadne, `run.sh` zhodí aj ostatné a kontajner
skončí — Supervisor (watchdog na `/time`) ho reštartuje.

### Prečo nie ingress pre Mailpit

Mailpit má v HTML absolútne cesty (`/dist/app.js`, `data-webroot="/"`) a
Supervisor pri ingresse prefix odstrihne, takže by sa assety nenačítali.
`MP_WEBROOT` by zas rozbil priamy prístup na porte 8025. Ostáva teda port.

## Verejný prístup a kto sa smie prihlásiť

Appka na telefóne musí server dosiahnuť aj mimo domu, preto je
`timelimit.fabrici.xyz` v Caddy (LXC 116, `/etc/caddy/Caddyfile`) ako
**verejný** host bez `gate`, reverse proxy na `192.168.1.102:8080`. Wildcard
certifikát `*.fabrici.xyz` aj DNS už existovali, pridal sa len `handle` blok.
Overené zvonku (z cloudu): `GET /time` → 200, Let's Encrypt.

Aby si na verejnom serveri nikto cudzí nič nezaložil, server posiela
prihlasovacie kódy **len adresám z whitelistu** (`mail_whitelist` v options →
`MAIL_WHITELIST`). Položka bez `@` je doména, s `@` celá adresa. Nastavené je
`fabrici.xyz`, takže v appke zadaj **ľubovoľnú adresu @fabrici.xyz** — maily
aj tak končia v Mailpite, nikam sa nedoručujú. Cudzia adresa dostane
`{"mailAddressNotWhitelisted":true}` a mail sa nepošle. Ďalšie adresy
(napr. gmail) dopíš do options.

`disable_signup` ostáva vypnuté, kým rodina nevznikne — zapnuté by
zablokovalo aj tvoju prvú registráciu. Po založení rodiny ho zapni.

Overený celý tok cez verejnú URL: `send-mail-login-code-v2` → kód v Mailpite →
`sign-in-by-mail-code` vráti `mailAuthToken`; zlý kód vráti 403.

Mailpit (kódy) sa von nevystavuje. Kód si prečítaš doma alebo cez headscale
VPN; registrácia je jednorazová vec.

## Most do Home Assistantu

Server nemá REST API pre tretie strany, má sync protokol pre svoju appku.
Most (`bridge/bridge.js`, node, jediná závislosť `mqtt`) sa doň zapája ako
**ďalšie rodičovské zariadenie** „Home Assistant":

1. pri štarte s nastaveným `parent_mail` si vyžiada prihlasovací kód
   (`/auth/send-mail-login-code-v2`), **prečíta si ho sám z Mailpitu**
   (beží v tom istom kontajneri), prihlási sa (`/auth/sign-in-by-mail-code`)
   a pripojí sa do rodiny (`/parent/sign-in-into-family`);
2. server mu dá trvalý `deviceAuthToken` a zariadenie má
   `isUserKeptSignedIn: true`, takže rodičovské akcie posiela s
   `integrity: "device"` — **bez rodičovského hesla a bez HMAC**;
3. každých `sync_interval` sekúnd ťahá `/sync/pull-status` (inkrementálne,
   podľa verzií) a drží si kópiu rodiny v `/data/bridge.json`;
4. cez **MQTT discovery** (Mosquitto add-on, prihlásenie od Supervisora)
   vytvára entity v HA a prekladá príkazy na akcie do `/sync/push-actions`.

Ak rodina pre `parent_mail` ešte neexistuje (409), most to skúša každý
interval znova a `sensor.timelimit_most` ukazuje „čaká na rodinu". Zmena
`parent_mail` alebo odstránenie zariadenia v appke (401) spustí nové
prihlásenie. Rate limit servera: 2 kódy za 5 minút a 6 za deň na adresu
(v pamäti, reštart add-onu ho nuluje).

Poradové čísla akcií musia ostať pod 2^31 (`Devices.nextSequenceNumber` je
`int(11)`): most počíta od 0 a čítač drží v stave spolu s tokenom.

### Entity v HA

Zariadenie **TimeLimit** (most): `sensor.timelimit_most` (stav + atribúty),
`button.timelimit_synchronizovat`, `sensor.timelimit_zariadenie_<názov>`
(kto je na zariadení prihlásený).

Zariadenie **TimeLimit – <dieťa>** pre každé dieťa:

| Entita | Význam |
|---|---|
| `sensor.…_pouzite_dnes` | minúty dnes (súčet vrcholových kategórií; v atribútoch rozpis) |
| `sensor.…_zostava_dnes`, `sensor.…_limit_dnes` | podľa pravidiel na dnes (minimum zo všetkých) |
| `switch.…_zablokovane` | dočasné zablokovanie všetkých kategórií dieťaťa (`UPDATE_CATEGORY_TEMPORARILY_BLOCKED`) |
| `switch.…_bez_limitu` | režim bez limitu do konca dňa (`SET_USER_DISABLE_LIMITS_UNTIL`) |
| `number.…_extra_cas_dnes` | extra čas na dnes pre vrcholové kategórie (`SET_CATEGORY_EXTRA_TIME`) |
| `number.…_strop_na_dnes` | strop na dnes — vlastné pravidlo HA (viď nižšie) |
| `…_<kategória>_…` | to isté per kategória (použité, zablokované, extra, strop) |

Generický príkaz na `timelimit/cmd` (JSON): `sync`, `block`/`unblock`
(`child`/`category`, `minutes`), `add_time`, `set_extra`, `set_limit`,
`no_limits` (`on`, `minutes`), `add_child`, `add_category`, `enroll`, `raw`
(`actions: [{type, …}]` – únikový východ na ľubovoľnú rodičovskú akciu).
Chyby idú na `timelimit/bridge/error` a do logu add-onu.

### Strop na dnes a pravidlá appky

Appka má svoj týždenný rozvrh ako pravidlá (často jedno na každý deň alebo
masku dní). Most ich **nikdy nemení** — pre strop má vlastné pravidlo len s
dnešným dňom, ktorého id si pamätá (`haRules` v stave). Platí minimum zo
všetkých pravidiel, takže HA vie strop len stlačiť nižšie; zvýšiť sa dá
extra časom. Presne tak dnes funguje aj override do Family Link. Hodnota
≥ 1440 pravidlo HA zmaže; po polnoci ho most zmaže sám, aby o týždeň
neplatilo znova.

Pozor na sémantiku pravidiel TimeLimit: `perDay` = limit platí pre každý
deň masky zvlášť; **bez `perDay` je to spoločný rozpočet pre všetky dni
masky** (napr. 360 min na celý týždeň). Most to pri výpočte „zostáva dnes"
zohľadňuje (odráta spotrebu ostatných dní masky v tomto týždni).

### Overené na skutočnej rodine

Extra čas 5 → 0, zablokovanie a odblokovanie, bez limitu zap/vyp, strop na
dnes — všetko sa do pár sekúnd prejavilo v HA aj v databáze servera.

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

1. **Tablet prepnúť na Simonku.** V rodine je iPlay 50 prihlásený ako
   rodič Jakub (`sensor.timelimit_zariadenie_iplay_50`); kým tam nie je
   používateľ Simonka, appka na tablete nič nevynucuje.
2. Zapnúť `disable_signup` v options add-onu (rodina už existuje).
3. **Prepnúť `simona_cas.yaml` z Family Linku na TimeLimit** — náhrady
   jedna k jednej: `sensor.iplay_50_…used_minutes` →
   `sensor.timelimit_simonka_pouzite_dnes`; `familylink.set_daily_limit`
   (override na dnes) → `number.timelimit_simonka_strop_na_dnes`; bonus →
   `number.timelimit_simonka_extra_cas_dnes`; zamknutie tabletu →
   `switch.timelimit_simonka_zablokovane`; režim bez limitu →
   `switch.timelimit_simonka_bez_limitu`. Odpadá celá ozvena vlastných
   zápisov (`simona_fl_zapisane`) aj pauza 00:00–00:10, lebo rozvrh je
   v appke a HA píše len do vlastného pravidla.
4. Až keď to beží paralelne a sedí, vypnúť HAFamilyLink.

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
