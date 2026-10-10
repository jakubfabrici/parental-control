#!/usr/bin/env python3
"""Zdielany cas bez Family Link: tablet uz len cez TimeLimit.

Family Link integracia (HACS noiwid/HAFamilyLink) nefunguje od 2026-09-27
10:28 CEST, ked HA po restarte prvy raz nacital verziu 2.2.1 (auth server
Googlu vracia 403, vsetky entity unavailable, config entry v setup_retry).
Tablet od 2026-10-03 riadi TimeLimit (patch-timelimit.py) a 2026-10-04 sa
Family Link z HA odstranuje uplne. Tento patch z balikov vyhodi vsetko, co
na nom este viselo:

  simona_cas.yaml
    - input_select.simona_tablet_zdroj (TimeLimit je jediny zdroj)
    - input_text.simona_fl_zapisane (ozvena zapisov do FL)
    - sensor.simona_tablet_namerane cita len TimeLimit
    - sensor.simona_rozpocet_celkom = rozpocet na dnes (bonus FL uz nie je;
      extra cas TimeLimit sa NEpripocitava - ten si most nastavuje sam ako
      sucast ciela, zapocital by sa dvakrat)
    - polnocny reset bez obnovovania senzorov FL a bez minutoveho cakania
      na koordinator FL; ostava o 00:06 ako doteraz (agent PC resetuje
      o 00:00 a okna "minute < 10" pri spotrebe PC s tym ratali)
    - automatizacie prec: evidencia zapisov do FL, prevzatie zmeny z FL,
      uvolnenie stropu pri prepnuti na FL, zosuladenie limitu cez FL,
      vecerne vratenie overridu o 23:57
    - strop cez TimeLimit bez podmienky na zdroj
    - komentare

  simona_cas_telegram.yaml
    - /cas: bez bonusu FL; zamknutie tabletu podla TimeLimit
      (switch.timelimit_simonka_zablokovane)

Na zivom HA treba po nasadeni:
  - reload input_select, input_text, template, automation, script
  - z registra entit odstranit 5 automatizacii, ktore z YAML zmizli
    (automation.* s unique_id simona_cas_fl_evidencia, simona_cas_fl_zmena,
    simona_cas_timelimit_uvolnit, simona_cas_sync_tabletu,
    simona_cas_vecerne_upratanie) - reload ich v registri necha ako
    "nedostupne"

Idempotentne. Pouzitie:
  python3 patch-bez-familylink.py simona_cas.yaml simona_cas_telegram.yaml
"""
import sys

done = []


def swap(name, old, new):
    """Nahradi presne jeden vyskyt. Ked uz vzor nie je a nova verzia je
    vnutri (alebo sa len mazalo), preskoci."""
    global s
    n = s.count(old)
    if n == 1:
        s = s.replace(old, new)
        done.append(name)
        return
    assert n == 0 and (not new or new in s), f"{name}: vzor sedi {n}x"


# =========================================================== simona_cas.yaml
p = sys.argv[1]
s = open(p, encoding="utf-8").read()

swap("hlavicka", """# Simona: ZDIELANY CASOVY ROZPOCET  (tablet iPlay_50 + PC 192.168.1.104)
#
# Myslienka: jeden vecer casu na den pre obe zariadenia dokopy.
#   R      = celkovy rozpocet na dnes (min), preberany z rozvrhu Family Link
#   tablet = skutocne minuty na tablete (Family Link ich uz rata sam)
#   pc     = skutocne minuty na PC (hlasi agent na porte 8799)
#
# HA obom stranam priebezne posuva ich strop:
#   FL denny limit tabletu  :=  R - pc              -> Family Link zamkne tablet
#   povolene na PC          :=  R + bonus - tablet  -> agent uz len varuje
""", """# Simona: ZDIELANY CASOVY ROZPOCET  (tablet iPlay 50 + PC 192.168.1.104)
#
# Myslienka: jeden vecer casu na den pre obe zariadenia dokopy.
#   R      = celkovy rozpocet na dnes (min), o polnoci z tyzdenneho rozvrhu
#   tablet = skutocne minuty na tablete (TimeLimit, kategoria s limitom)
#   pc     = skutocne minuty na PC (hlasi agent na porte 8799)
#
# HA obom stranam priebezne posuva ich strop:
#   ciel tabletu na dnes  :=  R - pc      -> most TimeLimit, appka zamkne tablet
#   povolene na PC        :=  R - tablet  -> agent uz len varuje
""")

swap("hlavicka-rozvrh", """# Rozvrh je v HA (input_number.simona_rozvrh_po ... _ne) ako kopia rozvrhu
# z Family Link - ten sa cez integraciu vycitat NEDA, coordinator sprístupnuje
# len appliedTimeLimits (hodnotu platnu na dnes, vratane nasho override).
# Citat rozpocet odtial bola chyba: kazde rano sme precitali vlastny vcerajsi
# zvysok a rozpocet sa scvrkaval. Ked sa vsak limit vo FL zmeni tak, ze to
# nesposobil nas zapis, je to skutocna zmena od rodica - tu prevezmeme
# (simona_cas_fl_zmena) a prepiseme nou aj kopiu rozvrhu.
# Zapis limitu ide cez endpoint
# timeLimitOverrides:batchCreate, teda je to override na DNESNY den -
# tyzdenny rozvrh v Google sa nemeni. O 23:57 ho vraciame na hodnotu rozvrhu,
# aby po nas nezostal ziadny override.
#
# Fail-safe: ked Family Link data chybaju (unavailable), NEMENIME nic -
# radsej ziadny zasah nez omylom nastaveny limit 0.
""", """# Rozvrh je v HA (input_number.simona_rozvrh_po ... _ne) a je to jediny
# zdroj pravdy: o polnoci sa z neho naplni rozpocet na dnes. Vlastne pravidla
# kategorie "Ostatné aplikácie" v appke TimeLimit (60 min po-pia, 180 min
# so-ne) su len zachranna siet pre pripad, ze HA alebo most nebezi.
#
# Strop tabletu: HA posiela mostu TimeLimit "cielovy cas na dnes" (mqtt
# timelimit/cmd, set_total) a most ho premieta do vlastneho pravidla HA
# a extra casu - viď ha/addons/timelimit/README.md.
#
# Fail-safe: ked minuty tabletu chybaju (most alebo server TimeLimit nebezi),
# strop tabletu NEMENIME - radsej ziadny zasah nez omylom nastaveny limit 0.
""")

swap("input_select", """# Odkial berieme minuty a kam piseme strop tabletu. Prva moznost je
# predvolena pri prvom vytvoreni; potom si HA pamata poslednu volbu.
input_select:
  simona_tablet_zdroj:
    name: Simona tablet – zdroj
    icon: mdi:tablet-cellphone
    options:
      - TimeLimit
      - Family Link

""", "")

swap("rozvrh-komentar", """  # Tyzdenny rozvrh: kolko minut ma dieta na jednotlivy den. Je to KOPIA
  # rozvrhu z Family Link - ten sa cez integraciu vycitat neda (coordinator
  # cita len appliedTimeLimits, teda hodnotu platnu na dnes, do ktorej sme
  # sami zapisali override). Ked sa rozvrh vo Family Link zmeni, treba ho
  # prepisat aj tu.
""", """  # Tyzdenny rozvrh: kolko minut ma dieta na jednotlivy den. Je to jediny
  # zdroj pravdy o rozvrhu - o polnoci sa z neho naplni rozpocet na dnes.
  # Meni sa na dashboarde /simonka-cas (Týždenný rozvrh).
""")

swap("input_text", """input_text:
  # Poslednych 5 hodnot, ktore sme zapisali do Family Link, oddelenych
  # ciarkou. Sluzi na rozoznanie vlastnej ozveny od skutocnej zmeny v
  # aplikacii - viac pri automatizacii simona_cas_fl_zmena.
  simona_fl_zapisane:
    name: Simona posledné zápisy do Family Link
    max: 40
    icon: mdi:pencil-outline

""", "")

swap("tablet-namerane", """      # Skutocne minuty na tablete dnes. Family Link ich rata sam, my ich len
      # citame - su nezavisle od toho, ako prave posuvame denny limit.
      # Surove minuty tabletu dnes zo zvoleneho zdroja (pred odpocitanim
      # nezapocitanych). Pri TimeLimit len kategoria s limitom - Allowed Apps
      # su povolene stale a do spolocneho casu sa nerataju.
      - name: Simona tablet namerané
        unique_id: simona_tablet_namerane
        unit_of_measurement: min
        device_class: duration
        state_class: measurement
        icon: mdi:tablet
        availability: >-
          {% if is_state('input_select.simona_tablet_zdroj', 'TimeLimit') %}
          {{ has_value('sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes') }}
          {% else %}
          {{ has_value('sensor.iplay_50_screen_time_remaining') }}
          {% endif %}
        state: >-
          {% if is_state('input_select.simona_tablet_zdroj', 'TimeLimit') %}
          {{ states('sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes') | int(0) }}
          {% else %}
          {{ state_attr('sensor.iplay_50_screen_time_remaining', 'used_minutes') | int(0) }}
          {% endif %}
        attributes:
          zdroj: "{{ states('input_select.simona_tablet_zdroj') }}"
""", """      # Surove minuty tabletu dnes z TimeLimit (pred odpocitanim
      # nezapocitanych). Len kategoria s limitom - Allowed Apps su povolene
      # stale a do spolocneho casu sa nerataju. Appka ich rata sama, takze su
      # nezavisle od toho, ako prave posuvame strop tabletu.
      - name: Simona tablet namerané
        unique_id: simona_tablet_namerane
        unit_of_measurement: min
        device_class: duration
        state_class: measurement
        icon: mdi:tablet
        availability: "{{ has_value('sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes') }}"
        state: "{{ states('sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes') | int(0) }}"
""")

swap("rozpocet-celkom", """      # Celkovy dostupny cas na dnes. Bonus pridany priamo v aplikacii Family
      # Link sa pripocitava - rodic tym vedome zvacsil vecer.
      - name: Simona rozpočet celkom
        unique_id: simona_rozpocet_celkom
        unit_of_measurement: min
        device_class: duration
        icon: mdi:wallet-plus-outline
        state: >-
          {{ (states('input_number.simona_rozpocet_dnes') | int(0))
             + ((states('sensor.iplay_50_active_bonus') | int(0)) if is_state('input_select.simona_tablet_zdroj', 'Family Link') else 0) }}
""", """      # Celkovy dostupny cas na dnes. Pridany cas (Telegram, dashboard) sa
      # pripisuje priamo do rozpoctu na dnes, takze je to rovno R. Extra cas
      # v TimeLimit sa NEpripocitava - ten si most nastavuje sam ako sucast
      # ciela tabletu a zapocital by sa dvakrat.
      - name: Simona rozpočet celkom
        unique_id: simona_rozpocet_celkom
        unit_of_measurement: min
        device_class: duration
        icon: mdi:wallet-plus-outline
        state: "{{ states('input_number.simona_rozpocet_dnes') | int(0) }}"
""")

swap("cielovy-komentar", """      # Strop, ktory ma mat tablet vo Family Link. Bonus sem NEpatri - Family
      # Link si ho pripocitava k limitu sam, inak by sa zapocital dvakrat.
""", """      # Ciel tabletu na dnes, ktory HA posiela mostu TimeLimit (set_total):
      # rozpocet minus PC, plus minuty nezapocitane v rezime bez limitu (appka
      # ich vidi ako pouzite, preto ich treba vratit).
""")

swap("polnocny-reset", """  # -- Polnocny start dna -----------------------------------------------------
  # Rozpocet na dnes berieme z TYZDENNEHO ROZVRHU v HA (input_number.simona_
  # rozvrh_*), nie z Family Link.
  #
  # Predtym sa cital sensor.iplay_50_daily_limit - a to bola chyba: integracia
  # do neho dava hodnotu platnu na dnes, teda vratane override, ktory sme tam
  # cez den sami zapisali. Rano sme si tak precitali vlastny vcerajsi zvysok
  # a rozpocet sa den po dni scvrkaval (180 -> 75 -> 61). Tyzdenny rozvrh sa
  # z Family Link vycitat neda, preto je jeho kopia tu.
  - id: simona_cas_polnocny_reset
    alias: "Simona čas: polnočný reset rozpočtu"
    mode: single
    triggers:
      - trigger: time
        at: "00:05:00"
    actions:
      - action: homeassistant.update_entity
        continue_on_error: true
        target:
          entity_id:
            - sensor.iplay_50_daily_limit
            - sensor.iplay_50_screen_time_remaining
      # Minuta, nie 20 sekund: koordinator ma interval 30 s a my potrebujeme,
      # aby stihol priniest hodnotu na NOVY den. Ak sa lisi od rozvrhu,
      # medzitym ju prevezme automatizacia simona_cas_fl_zmena.
      - delay: "00:01:00"
      - action: input_number.set_value
""", """  # -- Polnocny start dna -----------------------------------------------------
  # Rozpocet na dnes berieme z TYZDENNEHO ROZVRHU v HA (input_number.simona_
  # rozvrh_*). Je to lokalna hodnota, takze vzdy existuje.
  #
  # Preco 00:06 a nie 00:00: agent na PC nuluje o 00:00 a most TimeLimit
  # ohlasi minuty noveho dna pri prvej synchronizacii po polnoci (raz za
  # minutu). O 00:06 su obe strany davno na novom dni, takze novy rozpocet
  # sa nikdy nestretne so vcerajsimi minutami (falosne "cas sa minul" a
  # vypnutie PC o polnoci). Do 00:06 plati vcerajsi rozpocet - minuty noveho
  # dna su vtedy takmer nulove, takze to je nanajvys o chvilu volnejsie.
  - id: simona_cas_polnocny_reset
    alias: "Simona čas: polnočný reset rozpočtu"
    mode: single
    triggers:
      - trigger: time
        at: "00:06:00"
    actions:
      - action: input_number.set_value
""")

swap("polnocny-reset-rozpocet", """      # Rozpocet na novy den podla rozvrhu. Je to lokalna hodnota, takze
      # vzdy existuje - nic tu nemoze zlyhat na nedostupnom Google API.
""", """      # Rozpocet na novy den podla rozvrhu.
""")

swap("fl-evidencia-a-zmena", """  # -- Evidencia toho, co sme do Family Link zapisali --------------------------
  # Pocuvame priamo volanie sluzby, nie jednotlive automatizacie: do FL pisu
  # aj STARSIE automatizacie z povodneho setupu (tlacidla /pridat_30,
  # /pridat_60, vikendovy rezim v automations.yaml). Keby sme evidovali len
  # vlastne zapisy, ich zmeny by simona_cas_fl_zmena povazovala za zmenu od
  # rodica a prepisala by nimi tyzdenny rozvrh.
  - id: simona_cas_fl_evidencia
    alias: "Simona čas: evidencia zápisov do Family Link"
    mode: queued
    max: 10
    triggers:
      - trigger: event
        event_type: call_service
        event_data:
          domain: familylink
          service: set_daily_limit
    actions:
      - action: input_text.set_value
        target:
          entity_id: input_text.simona_fl_zapisane
        data:
          value: >-
            {% set nova = trigger.event.data.service_data.daily_minutes | int(0) %}
            {{ ([ nova | string ] + (states('input_text.simona_fl_zapisane')
                 .split(',') | map('int', 0) | select | map('string') | list))[:5] | join(',') }}

  # -- Prevzatie zmeny z Family Link ------------------------------------------
  # Ked rodic zmeni denny limit priamo v aplikacii, chceme to vediet a
  # prevziat - Family Link je zdroj pravdy o rozvrhu.
  #
  # Lenze do toho isteho senzora pisme aj my: familylink.set_daily_limit si
  # po zapise vyziada refresh koordinatora, takze kazdy nas zapis sa nam o
  # par sekund vrati ako "zmena". Slepe preberanie by znamenalo, ze si
  # kazdu minutu precitame vlastny odpocet a rozpocet by sa scvrkaval -
  # to iste, co robil povodny polnocny reset, len 30x rychlejsie.
  #
  # Preto si poslednych 5 zapisanych hodnot pametame a preberame len zmenu,
  # ktora sa ani jednej z nich nerovna.
  - id: simona_cas_fl_zmena
    alias: "Simona čas: prevziať zmenu z Family Link"
    mode: single
    max_exceeded: silent
    triggers:
      - trigger: state
        entity_id: sensor.iplay_50_daily_limit
    conditions:
      - condition: state
        entity_id: input_select.simona_tablet_zdroj
        state: Family Link
      # Prechody cez unknown/unavailable (restart HA, vypadok Google) nie su
      # zmena rozvrhu.
      - condition: template
        value_template: >-
          {{ trigger.from_state is not none and trigger.to_state is not none
             and trigger.from_state.state not in ['unknown', 'unavailable']
             and trigger.to_state.state not in ['unknown', 'unavailable'] }}
      # Nula chodi aj z nocneho/skolskeho rezimu, nie je to rozvrh.
      - condition: template
        value_template: "{{ 0 < (trigger.to_state.state | int(0)) <= 1440 }}"
      # Kym je tablet rucne zamknuty, FL zmeny limitu neprijima a hlasi
      # neaktualne cisla.
      - condition: state
        entity_id: switch.iplay_50
        state: "on"
      # Jadro veci: nesmieme prevziat vlastnu ozvenu.
      - condition: template
        value_template: >-
          {{ (trigger.to_state.state | int(0)) | string
             not in states('input_text.simona_fl_zapisane').split(',') }}
      - condition: template
        value_template: >-
          {{ (trigger.to_state.state | int(0))
             != (states('sensor.simona_tablet_cielovy_limit') | int(-1)) }}
    actions:
      - variables:
          nova: "{{ trigger.to_state.state | int(0) }}"
          den: "{{ ['po','ut','st','stv','pi','so','ne'][now().weekday()] }}"
          den_nazov: >-
            {{ ['pondelok','utorok','stredu','štvrtok','piatok','sobotu','nedeľu'][now().weekday()] }}
          stary: "{{ states('sensor.simona_rozvrh_dnes') | int(0) }}"
      # Rozvrh na dnesny den aj rozpocet na dnes.
      - action: input_number.set_value
        target:
          entity_id: "input_number.simona_rozvrh_{{ den }}"
        data:
          value: "{{ nova }}"
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_rozpocet_dnes
        data:
          value: "{{ nova }}"
      - action: telegram_bot.send_message
        continue_on_error: true
        data:
          chat_id: 5756450012
          parse_mode: html
          message: >-
            📅 Family Link hlási denný limit <b>{{ nova }} min</b>{% if stary != nova %}
            (predtým {{ stary }}){% endif %}. Prevzal som to ako rozpočet na dnes
            aj ako rozvrh na {{ den_nazov }}.{% if stary != nova %}
            {{ '\\n' }}<i>Ak to malo platiť len dnes, oprav rozvrh na dashboarde.</i>{% endif %}

""", "")

swap("strop-timelimit", """  # -- Strop tabletu cez TimeLimit --------------------------------------------
  # HA posle mostu "cielovy cas na dnes" = sensor.simona_tablet_cielovy_limit.
  # Most ho drzi (aj cez restart) a pri kazdej synchronizacii premieta do
  # vlastneho pravidla HA (strop appky zvysit nevie) a extra casu (to, co je
  # nad strop appky). Posielame pri zmene a raz za 5 minut pre istotu.
  - id: simona_cas_sync_tabletu_timelimit
    alias: "Simona čas: strop tabletu cez TimeLimit"
    mode: single
    max_exceeded: silent
    triggers:
      - trigger: state
        entity_id:
          - sensor.simona_tablet_cielovy_limit
          - input_select.simona_tablet_zdroj
          - input_boolean.simona_zdielany_cas
      - trigger: time_pattern
        minutes: "/5"
    conditions:
      - condition: state
        entity_id: input_select.simona_tablet_zdroj
        state: TimeLimit
      - condition: template
""", """  # -- Strop tabletu cez TimeLimit --------------------------------------------
  # HA posle mostu "cielovy cas na dnes" = sensor.simona_tablet_cielovy_limit.
  # Most ho drzi (aj cez restart) a pri kazdej synchronizacii premieta do
  # vlastneho pravidla HA (strop appky zvysit nevie) a extra casu (to, co je
  # nad strop appky). Posielame pri zmene a raz za 5 minut pre istotu. Ked je
  # zdielany cas vypnuty, ciel zrusime (clear_total) a plati len rozvrh appky.
  # Ciel plati len na den, v ktory prisiel - vcerajsi ciel aj pravidlo HA
  # most po polnoci zahodi sam.
  - id: simona_cas_sync_tabletu_timelimit
    alias: "Simona čas: strop tabletu cez TimeLimit"
    mode: single
    max_exceeded: silent
    triggers:
      - trigger: state
        entity_id:
          - sensor.simona_tablet_cielovy_limit
          - input_boolean.simona_zdielany_cas
      - trigger: time_pattern
        minutes: "/5"
    conditions:
      - condition: template
""")

swap("uvolnit-a-sync-fl", """  # Pri prepnuti spat na Family Link cielovy cas v TimeLimit zrusime.
  - id: simona_cas_timelimit_uvolnit
    alias: "Simona čas: uvoľniť strop v TimeLimit"
    mode: single
    triggers:
      - trigger: state
        entity_id: input_select.simona_tablet_zdroj
        to: Family Link
    actions:
      - action: mqtt.publish
        data:
          topic: timelimit/cmd
          payload: >-
            {{ {'action': 'clear_total', 'child': 'Simonka', 'category': 'Ostatné aplikácie'} | to_json }}

  # -- Prepocet stropu pre tablet --------------------------------------------
  # Bezi po kazdej zmene spotreby. Google API volame len ked sa cielova
  # hodnota naozaj lisi od aktualnej, aby sme ho nebombardovali.
  - id: simona_cas_sync_tabletu
    alias: "Simona čas: zosúladiť limit tabletu"
    mode: single
    max_exceeded: silent
    triggers:
      - trigger: state
        entity_id:
          - sensor.simona_tablet_cielovy_limit
          - input_number.simona_pc_pouzite
          - input_number.simona_rozpocet_dnes
      - trigger: time_pattern
        minutes: "/5"
    conditions:
      - condition: state
        entity_id: input_select.simona_tablet_zdroj
        state: Family Link
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: template
        value_template: "{{ has_value('sensor.simona_tablet_cielovy_limit') }}"
      - condition: template
        value_template: "{{ has_value('sensor.iplay_50_daily_limit') }}"
      - condition: template
        value_template: >-
          {{ (states('sensor.simona_tablet_cielovy_limit') | int(-1))
             != (states('sensor.iplay_50_daily_limit') | int(-2)) }}
      # Tesne po polnoci sa vo Family Link objavi rozvrh na novy den. Keby
      # sme don v tej chvili zapisali, prepiseme si ho skor, nez si ho
      # stihneme precitat - a rozvrh z aplikacie by sa k nam nikdy nedostal.
      - condition: template
        value_template: "{{ not (now().hour == 0 and now().minute < 10) }}"
    actions:
      - variables:
          ciel: "{{ states('sensor.simona_tablet_cielovy_limit') | int }}"
      - action: familylink.set_daily_limit
        data:
          entity_id: switch.iplay_50
          daily_minutes: "{{ ciel }}"

""", "")

swap("vecerne-upratanie", """  # -- Vecerne upratanie ------------------------------------------------------
  # Override vratime na hodnotu z ROZVRHU (nie na rozpocet - ten mohol byt
  # cez den rucne zvyseny a to bola vynimka len na dnes), nech po nas v
  # Google nezostane nic, co by ovplyvnilo dalsie dni.
  - id: simona_cas_vecerne_upratanie
    alias: "Simona čas: vrátiť limit podľa rozvrhu"
    mode: single
    triggers:
      - trigger: time
        at: "23:57:00"
    conditions:
      - condition: state
        entity_id: input_select.simona_tablet_zdroj
        state: Family Link
      - condition: template
        value_template: >-
          {{ has_value('sensor.iplay_50_daily_limit')
             and (states('sensor.iplay_50_daily_limit') | int(-1))
                 != (states('sensor.simona_rozvrh_dnes') | int(-2)) }}
    actions:
      - variables:
          ciel: "{{ states('sensor.simona_rozvrh_dnes') | int }}"
      - action: familylink.set_daily_limit
        data:
          entity_id: switch.iplay_50
          daily_minutes: "{{ ciel }}"

""", "")

open(p, "w", encoding="utf-8").write(s)
print(p, "hotovo:", ", ".join(done) if done else "nic (uz bolo aplikovane)")

# ================================================== simona_cas_telegram.yaml
done = []
p = sys.argv[2]
s = open(p, encoding="utf-8").read()

swap("tg-bonus", """            {% set bonus = states('sensor.iplay_50_active_bonus') | int(0) %}
""", "")

swap("tg-rozpocet", """Rozpočet dnes: <b>{{ celkom }} min</b>{% if bonus > 0 %} (základ {{ rozpocet }} + bonus {{ bonus }}){% endif %}
""", """Rozpočet dnes: <b>{{ celkom }} min</b>
""")

swap("tg-zamknuty", """{% if is_state('switch.iplay_50','off') %}
            {{ '\\n' }}🔒 <b>Tablet zamknutý ručne</b> — kým to trvá, Family Link neprijme zmeny limitu{% endif %}
""", """{% if is_state('switch.timelimit_simonka_zablokovane','on') %}
            {{ '\\n' }}🔒 <b>Tablet je zablokovaný</b> (TimeLimit){% endif %}
""")

open(p, "w", encoding="utf-8").write(s)
print(p, "hotovo:", ", ".join(done) if done else "nic (uz bolo aplikovane)")
