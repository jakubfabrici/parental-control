# TimeLimit Server – add-on pre Home Assistant

Self-hostovaný server pre [TimeLimit](https://timelimit.io) (open-source
rodičovský dohľad pre Android) bežiaci priamo v Home Assistante ako lokálny
add-on. Nahrádza samostatný LXC 123 na `pve`, ktorý sa predtým zrušil.

**Stav (2026-10-04):** server beží, rodina je založená (rodič
`timelimit@fabrici.xyz`, dieťa Simonka, zariadenie iPlay 50 s prihlásenou
Simonkou), **most do HA je prihlásený** a **tablet riadi už len
TimeLimit** — zdieľaný denný rozpočet tablet + PC z `simona_cas.yaml` beží
nad týmto add-onom (strop na PC vynucuje agent na Windows).

*História:* predtým tablet riadil Google Family Link cez HACS integráciu
HAFamilyLink. Tá prestala fungovať 2026-09-27 o 10:28 — reštart HA prvý raz
načítal verziu 2.2.1, ktorú HACS stiahol 2026-09-25; odvtedy boli všetky jej
entity nedostupné a auth server vracal 403. 2026-10-04 bola z Home
Assistantu odstránená celá — integrácia s config entry a entitami, add-on
Google Family Link Auth aj s jeho repozitárom, záznam v HACS, uložené
cookies aj história v recorderi. Čo ostáva na strane Googlu, je v časti
[Čo ďalej](#čo-ďalej).

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
Ten je viazaný na server v1.17.0 a mení sa len vtedy, keď server
aktualizuješ ty. Most (`bridge/bridge.js`, node, jediná závislosť `mqtt`) sa
doň zapája ako **ďalšie rodičovské zariadenie** „Home Assistant":

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
| `sensor.…_vzdy_povolene_aplikacie`, `select.…`, `text.…` | vždy povolené aplikácie (viď nižšie) |

Generický príkaz na `timelimit/cmd` (JSON): `sync`, `block`/`unblock`
(`child`/`category`, `minutes`), `add_time`, `set_extra`, `set_limit`,
`no_limits` (`on`, `minutes`), `add_child`, `add_category`, `enroll`, `raw`
(`actions: [{type, …}]` – únikový východ na ľubovoľnú rodičovskú akciu),
`allow_app` / `disallow_app` (`child`, `package`).
Chyby idú na `timelimit/bridge/error` a do logu add-onu.

### Vždy povolené aplikácie

„Vždy povolené" je kategória v appke bez časových pravidiel (option
`always_allowed_category`, predvolene `Allowed Apps`). Pridať aplikáciu =
presunúť jej balík do tejto kategórie (`ADD_CATEGORY_APPS` balík zároveň
odoberie z ostatných kategórií dieťaťa). Odobrať = balík z kategórie
vyradiť; nezaradený padne do predvolenej kategórie dieťaťa
(`categoryForNotAssignedApps`). Keby predvolená nebola nastavená a dieťa
malo len jednu ďalšiu kategóriu, most ho presunie do nej, aby ho appka
nezačala úplne blokovať.

**Nastavenie u Simonky (od 2026-10-03):**

| Kategória | Čo v nej je | Pravidlá |
|---|---|---|
| Allowed Apps | vybrané aplikácie + `.dummy.system_image` (= všetky nezaradené **systémové** aplikácie) | žiadne – povolené stále |
| Ostatné aplikácie | predvolená pre všetko nezaradené, teda nesystémové aplikácie | 60 min denne po–pia, 180 min denne so–ne (`perDay`) |

Kategóriu „Allowed games" Jakub v appke zrušil; jej aplikácie sú teraz
nezaradené a padajú do Ostatných aplikácií.

Zoznam nainštalovaných aplikácií posiela tablet na server **šifrovane**
(`EncryptedAppLists`), most ho prečítať nevie. Vidí len balíky už
priradené do kategórií, preto sú v HA tri entity:
`select.…_pridat_medzi_vzdy_povolene` (balíky z ostatných kategórií),
`select.…_odobrat_z_vzdy_povolenych` a `text.…_pridat_balik_medzi_vzdy_povolene`
na úplne nový balík menom. Zoznamy sú v atribútoch
`sensor.…_vzdy_povolene_aplikacie`. Overené tam aj späť na testovacom balíku.

### Zdieľaný čas s PC (cieľ na dnes)

Spoločný rozpočet tablet + PC z `ha/packages/simona_cas.yaml` beží nad
TimeLimit. Rozpočet na dnes R (`input_number.simona_rozpocet_dnes`) sa
o 00:06 naplní z týždenného rozvrhu v HA (`input_number.simona_rozvrh_po` …
`_ne`) — ten je jediný zdroj pravdy. HA berie minúty tabletu
z `sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes` (Allowed Apps sa
nerátajú) a mostu posiela na `timelimit/cmd` **cieľ na dnes** T =
`sensor.simona_tablet_cielovy_limit` (R − PC, plus minúty tabletu
nezapočítané v režime bez limitu) ako
`{"action":"set_total", "child":"Simonka", "category":"Ostatné aplikácie", "minutes":T}`.

Most cieľ drží v stave (aj cez reštart, platí len pre daný deň) a pri každej
synchronizácii ho premieta do TimeLimit:

- vlastné pravidlo HA = min(T, strop appky); keď T ≥ strop appky, pravidlo
  HA netreba,
- čo je nad strop appky, doplní **extra čas**, dorovnávaný na presný zvyšok
  `(T − použité) − max(0, cap − použité)`, takže appke zostáva T − použité.

Overené: rozpočet 180 / PC 32 → strop 148; +15 → 163; rozpočet 240 → limit
180 + extra 28 = 208; „Ukončiť čas" → 0; späť → 148. `clear_total`
(HA ho posiela, keď je zdieľaný čas vypnutý) pravidlo HA aj extra čas
uprace a platí len rozvrh appky (1 h / 3 h).

**Polnoc:** cieľ aj pravidlo HA platia len pre deň, na ktorý vznikli. Pri
prvej synchronizácii po polnoci most včerajší cieľ zahodí a pravidlo HA so
včerajším dňom zmaže; extra čas je v TimeLimit tiež len na konkrétny deň.
Kým HA nepošle prvý cieľ nového dňa (pri zmene alebo pri päťminútovom
opakovaní), beží tablet len na vlastných pravidlách appky (1 h / 3 h). Do
00:06, keď sa naplní nový rozpočet a vynulujú počítadlá, sa cieľ počíta ešte
zo včerajšieho rozpočtu (minúty nového dňa sú vtedy takmer nulové); prečo
nie o 00:00, je v hlavnom `README.md` (Polnoc). Tie isté pravidlá appky sú aj
**poistka**, keby HA nebežal — bez cieľa z HA platí len rozvrh appky.

**Baterka tabletu:** synchronizácia mosta (`sync_interval`, 15 s) beží len
medzi HA a serverom, tablet nebudí. Tablet zobudí až push zmeny — server mu
vtedy pošle „should sync" cez websocket. Preto sa sprísnenie stropu (PC
ujedá z rozpočtu) posiela po **5-minútových krokoch** a presne až v
posledných **15 minútach** tabletu; uvoľnenie (pridaný čas) ide hneď. Pri
sedení za PC to je ping každých ~5 minút namiesto každej minúty a tablet
spoločný rozpočet aj tak nikdy neprekročí.

Pri aktívnom cieli most prepisuje ručný strop a extra čas kategórie — čas sa
pridáva zvýšením spoločného rozpočtu (`script.simona_cas_pridaj`, Telegram
+30/+60 a `/cas_add`, dashboard).

### Aktuálnosť času tabletu v HA

Appka TimeLimit si spotrebovaný čas zapisuje každých 30 s, ale **odosiela ho
s najnižšou prioritou** — najskôr 10 minút po poslednej synchronizácii
(`SyncUtil`, priorita `VeryUnimportant`). A pri zhasnutej obrazovke sa
odpojí od servera (do ~1 s) a nesynchronizuje vôbec, kým sa obrazovka zase
nezapne. Bez zásahu by HA videl čas tabletu oneskorený až o 10 minút a
posledné minúty pred zhasnutím až do ďalšieho zapnutia.

Preto:

1. **Server** (doplnok `patches/ha-sync.js`, zapojený pri builde cez
   `patches/apply-ha-sync.js`): kým je zariadenie dieťaťa pripojené, pošle mu
   každých `tablet_sync_active` sekúnd (30 s) pokyn `should sync`
   (isImportant). Appka hneď odošle čakajúcu spotrebu — rovnako ako po každej
   zmene od rodiča. Do databázy sa nič nezapisuje. Keď tablet dve kolá nič
   nové neposlal, server ho žiada len raz za `tablet_sync_idle` (120 s).
2. **Most** ťahá zmeny zo servera každých `sync_interval` sekúnd (15 s).
3. **Tablet — raz ručne:** v appke TimeLimit *About → Error diagnose →
   Experimental flags → „Keep connected when the screen is off"* (potvrdí sa
   rodičovským prihlásením). Appka potom ostane pripojená aj pri zhasnutej
   obrazovke, takže sa do HA dostane aj spotreba tesne pred zhasnutím; server
   ju vtedy žiada riedko (raz za 2 minúty), čo baterku zaťaží len málo.

Výsledok: pri používaní je čas tabletu v HA oneskorený najviac o ~1 minútu
(30 s zápis + 30 s pokyn + 15 s most); po zhasnutí obrazovky (s prepínačom
z bodu 3) do ~1 minúty dorazí všetko okrem posledného nezapísaného úseku
kratšieho ako 30 s, ten príde pri ďalšom zapnutí. Bez prepínača chýba po
zhasnutí najviac ~1 minúta, kým sa obrazovka znova nezapne.

### Pravidlo „jedno aktuálne zariadenie"

TimeLimit povolí appky s limitom len na zariadení, ktoré má dieťa na serveri
ako aktuálne. 4. 10. 2026 sa lokálna kópia na tablete rozišla so serverom a
tablet zablokoval všetko s limitom („This device is not selected as current
device"); tlačidlo v appke to neopraví (server odpovie „assigned to other
device"). Simonka má jediné zariadenie a čas sa ráta na serveri, takže
pravidlo nič nechráni — most ho deťom drží uvoľnené
(`SET_RELAX_PRIMARY_DEVICE`, funkcia `ensureRelaxedPrimaryDevice`); pri plnej
verzii (`always_pro`) to appka berie ako „každé zariadenie je aktuálne".

### Strop na dnes a pravidlá appky

Appka má svoj týždenný rozvrh ako pravidlá (často jedno na každý deň alebo
masku dní). Most ich **nikdy nemení** — pre strop má vlastné pravidlo len s
dnešným dňom, ktorého id si pamätá (`haRules` v stave). Platí minimum zo
všetkých pravidiel, takže HA vie strop len stlačiť nižšie; zvýšiť sa dá
extra časom. Hodnota ≥ 1440 pravidlo HA zmaže; po polnoci ho most zmaže sám,
aby o týždeň neplatilo znova.

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

1. **Vypnúť obmedzenia Googlu na tablete** — urobí len rodič, mimo HA.
   V appke Family Link na rodičovskom telefóne pre iPlay 50 vypnúť denný
   limit (Daily limit), večierku (Downtime/Bedtime) a školský čas
   (School time) a tablet odomknúť — alebo ukončiť dohľad nad Simoninym
   Google účtom, ak to Google pri jej veku dovolí. Inak na tablete
   paralelne beží aj limit Googlu a platí prísnejší z oboch. To isté
   rozhodnutie sa týka Chromecastu HD a TV Philips (nie sú súčasťou tohto
   systému). Pomocná appka `com.google.android.apps.kids.familylinkhelper`
   ostáva v Allowed Apps zámerne, kým dohľad Googlu nezmizne.
2. Zapnúť `disable_signup` v options add-onu, ak ešte nie je (rodina už
   existuje).
3. Voliteľne: zrkadliť týždenný rozvrh z HA (`input_number.simona_rozvrh_*`)
   do vlastných pravidiel appky, aby poistka pri výpadku HA zodpovedala
   rozvrhu. Dnes sú v appke pevne 60 min po–pia a 180 min so–ne.
