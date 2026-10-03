# Automatická aktualizácia PC agenta z OMV

Agent na Simonkinom PC (`D:\Users\kuko\remote-control\windows-remote-control\`)
sa **po každom zapnutí sám skontroluje a prípadne aktualizuje** z OMV servera.
Zdroj pravdy je tento repozitár (`agent/windows-remote-control/`), verzie sa
publikujú na `http://192.168.1.185/pc-agent/`.

```
repo  ──release.sh──►  OMV /var/www/pc-agent/            PC (po zapnutí)
                        ├─ current/manifest.json  ◄──── Update-PcAgent.ps1
                        ├─ current/manifest.sig            1. porovná verziu
                        └─ releases/<verzia>/…    ◄────    2. stiahne, overí SHA-256 + HMAC
                                                            3. skontroluje syntax, zálohuje, vymení
                                                            4. spustí PcAgent.ps1 (ten istý proces)
```

## Prečo takto

- **Žiadny nový proces na OMV ani na PC.** Na OMV to obsluhuje existujúci nginx
  (drop-in `/etc/nginx/openmediavault-webgui.d/pc-agent.conf`, podporovaný
  spôsob rozšírenia OMV web GUI). Na PC je updater zároveň launcher — po
  kontrole spustí agenta v tom istom PowerShell procese, takže na slabom
  Core2 Duo nepribudne žiadny rezidentný proces.
- **Podpísané vydania.** Updater beží s právami admina, preto nesmie vykonať
  nič, čo mu niekto podstrčí. Manifest je podpísaný HMAC-SHA256 kľúčom
  `/root/.pc-agent-update.key` (len root na OMV) a ten istý kľúč je v
  `config.json` na PC ako `UpdateKey`. Každý súbor má v manifeste SHA-256.
  Bez kľúča sa aktualizácie odmietajú. Vydania sú mimo SMB zdieľania
  (`/var/www/pc-agent`, zapisuje len root cez SSH).
- **Bezpečné zlyhanie.** OMV nedostupné, zlý hash, zlý podpis, syntaktická
  chyba → aktualizácia sa zahodí a beží doterajšia verzia. Keď nová verzia
  3× po sebe skončí do 60 s od štartu, označí sa ako zlá a vráti sa
  predchádzajúca (zálohy posledných 2 verzií v `D:\ProgramData\PcControl\update\releases\`).
- **Lokálne súbory sa nikdy neprepisujú:** `config.json` (token, kľúč),
  `agent.log`, `state.json`. Nie sú v manifeste a updater ich cesty odmieta.

## Vydanie novej verzie

1. Uprav súbory v `agent/windows-remote-control/`, zvýš `VERSION` (napr. `1.1.0`).
2. `agent/release.sh` — nahrá adresár na OMV a spustí `pc-agent-publish`,
   ktorý vytvorí `releases/<verzia>/`, manifest, podpis a atomicky prepne
   `current/`. Predpoklad: SSH kľúč na `root@192.168.1.185`.
3. PC si verziu stiahne pri najbližšom zapnutí. Okamžite: reštart úlohy
   `HA-PcAgent` (Telegram `/pc_update`, resp. `Restart-ScheduledTask`).

`release.sh 1.1.0` zapíše VERSION aj vydá naraz. Publikovať sa dá aj staršia
verzia — klient ju „aktualizuje" späť (rollback zo servera).

## Na PC

- Scheduled task `HA-PcAgent` spúšťa `ha-agent\Update-PcAgent.ps1` (nie
  `PcAgent.ps1` priamo).
- `config.json` má navyše `UpdateUrl` a `UpdateKey` (vzor: `config.example.json`).
- Stav updatera: `D:\ProgramData\PcControl\update\installed.json`
  (verzia, predchádzajúca, počet rýchlych ukončení), `bad-versions.txt`.
- Diagnostika bez zásahu: `powershell -File Update-PcAgent.ps1 -CheckOnly`
  vypíše `{installed, remote, update}` a nič nemení.
- Log: `agent.log`, riadky s `[UPD]`.

## Jednorazová príprava OMV

`agent/omv/install-omv.sh` (ako root na OMV): vytvorí `/var/www/pc-agent`,
nainštaluje `pc-agent-publish` do `/usr/local/bin`, nginx drop-in, vygeneruje
kľúč a reloadne nginx. Idempotentné. Lokácia je `location ^~ /pc-agent/` —
`^~` je nutné, inak by OMV webgui regex pre statické prípony (`.json`)
odpoveď prevzal a vracal 200/text/html aj pre neexistujúce súbory.

## Stav: OMV pripravené, kanál overený

- OMV: `/var/www/pc-agent/` (mimo SMB), nginx drop-in nasadený, kľúč
  `/root/.pc-agent-update.key` vygenerovaný, `pc-agent-publish` v `/usr/local/bin`.
- Publikovaná verzia **1.0.0** = presne dnešný agent na PC + `Update-PcAgent.ps1`.
- Overené na PC v izolovanom adresári (`-UpdateDir`, bez dotyku bežiaceho agenta):
  - 0.0.0 → 1.0.0: 20 súborov, SHA-256 aj HMAC v poriadku, **2 s**;
    `-CheckOnly` potom hlási `{"installed":"1.0.0","remote":"1.0.0","update":false}`,
  - zlý `UpdateKey` → „podpis manifestu nesedí", nič sa nenainštalovalo,
  - chýbajúci `UpdateKey` → „nepodpísané aktualizácie odmietam",
  - nedostupné OMV → po 5 s timeoute „bezi verzia …", agent by sa spustil normálne.
- **Na PC ešte nie je zapnuté:** treba prepnúť akciu úlohy `HA-PcAgent` na
  `Update-PcAgent.ps1`, doplniť `UpdateUrl`/`UpdateKey` do `config.json` a
  položiť `VERSION` = 1.0.0. Urobí sa spolu s nasadením opraveného agenta
  (výsledok výskumu), nech prvá skutočná aktualizácia rovno nesie opravu.
