#!/usr/bin/env python3
"""Prevziat zmenu denneho limitu z Family Link - ale len tu cudziu.

Zadanie: "vycitaj si rozvrh na den z Family Linku vzdy ked sa zmeni
sensor.iplay_50_daily_limit".

Pasca: familylink.set_daily_limit si po zapise hned vyziada refresh
koordinatora (__init__.py:677), takze KAZDY nas zapis sa do toho senzora
vrati spat. Pri 30-sekundovom pollingu by slepe preberanie znamenalo, ze
si kazdu minutu precitame vlastny odpocet - presne degradacia 180 -> 75
-> 61, len namiesto raz denne kazdych 30 sekund.

Riesenie: pametame si poslednych 5 hodnot, ktore sme do FL zapisali
(input_text.simona_fl_zapisane), a preberame len zmenu, ktora sa ani
jednej z nich nerovna - teda tu, ktoru urobil rodic v aplikacii.

Idempotentne.
"""
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
done = []


def swap(name, old, new):
    global s
    if new in s:
        return
    assert s.count(old) == 1, f"{name}: vzor sedi {s.count(old)}x"
    s = s.replace(old, new)
    done.append(name)


# --- 1. pamat nasich zapisov -----------------------------------------------
swap("input-text", """input_datetime:
  simona_pc_kontakt:""", """input_text:
  # Poslednych 5 hodnot, ktore sme zapisali do Family Link, oddelenych
  # ciarkou. Sluzi na rozoznanie vlastnej ozveny od skutocnej zmeny v
  # aplikacii - viac pri automatizacii simona_cas_fl_zmena.
  simona_fl_zapisane:
    name: Simona posledné zápisy do Family Link
    max: 40
    icon: mdi:pencil-outline

input_datetime:
  simona_pc_kontakt:""")


# --- 2. sync si zapisuje, co poslal ----------------------------------------
swap("sync-zapamataj", """    actions:
      - action: familylink.set_daily_limit
        data:
          entity_id: switch.iplay_50
          daily_minutes: "{{ states('sensor.simona_tablet_cielovy_limit') | int }}\"""", """    actions:
      - variables:
          ciel: "{{ states('sensor.simona_tablet_cielovy_limit') | int }}"
      - action: familylink.set_daily_limit
        data:
          entity_id: switch.iplay_50
          daily_minutes: "{{ ciel }}"
      - action: input_text.set_value
        target:
          entity_id: input_text.simona_fl_zapisane
        data:
          value: >-
            {{ ([ ciel | string ] + (states('input_text.simona_fl_zapisane')
                 .split(',') | map('int', 0) | select | map('string') | list))[:5] | join(',') }}""")

# Medzi 00:00 a 00:10 do FL nesiahame: prave vtedy sa v nom objavi rozvrh
# na novy den a nas zapis by ho prepisal skor, nez si ho stihneme precitat.
swap("sync-polnocne-okno", """      - condition: template
        value_template: >-
          {{ (states('sensor.simona_tablet_cielovy_limit') | int(-1))
             != (states('sensor.iplay_50_daily_limit') | int(-2)) }}""", """      - condition: template
        value_template: >-
          {{ (states('sensor.simona_tablet_cielovy_limit') | int(-1))
             != (states('sensor.iplay_50_daily_limit') | int(-2)) }}
      # Tesne po polnoci sa vo Family Link objavi rozvrh na novy den. Keby
      # sme don v tej chvili zapisali, prepiseme si ho skor, nez si ho
      # stihneme precitat - a rozvrh z aplikacie by sa k nam nikdy nedostal.
      - condition: template
        value_template: "{{ not (now().hour == 0 and now().minute < 10) }}\"""")


# --- 3. vecerne upratanie si tiez zapisuje ---------------------------------
swap("upratanie-zapamataj", """    actions:
      - action: familylink.set_daily_limit
        data:
          entity_id: switch.iplay_50
          daily_minutes: "{{ states('sensor.simona_rozvrh_dnes') | int }}\"""", """    actions:
      - variables:
          ciel: "{{ states('sensor.simona_rozvrh_dnes') | int }}"
      - action: familylink.set_daily_limit
        data:
          entity_id: switch.iplay_50
          daily_minutes: "{{ ciel }}"
      - action: input_text.set_value
        target:
          entity_id: input_text.simona_fl_zapisane
        data:
          value: >-
            {{ ([ ciel | string ] + (states('input_text.simona_fl_zapisane')
                 .split(',') | map('int', 0) | select | map('string') | list))[:5] | join(',') }}""")


# --- 4. dlhsi odstup po polnoci --------------------------------------------
# Aby mal koordinator cas priniest hodnotu na novy den skor, nez z rozvrhu
# nastavime rozpocet (a tym rozhybeme zapis do FL).
swap("dlhsi-delay", """            - sensor.iplay_50_screen_time_remaining
      - delay: "00:00:20\"""", """            - sensor.iplay_50_screen_time_remaining
      # Minuta, nie 20 sekund: koordinator ma interval 30 s a my potrebujeme,
      # aby stihol priniest hodnotu na NOVY den. Ak sa lisi od rozvrhu,
      # medzitym ju prevezme automatizacia simona_cas_fl_zmena.
      - delay: "00:01:00\"""")


# --- 5. samotne prevzatie cudzej zmeny -------------------------------------
swap("automatizacia-fl-zmena", """  # -- Rezim "bez limitu" ----------------------------------------------------""", """  # -- Prevzatie zmeny z Family Link ------------------------------------------
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

  # -- Rezim "bez limitu" ----------------------------------------------------""")


# --- 6. hlavicka -----------------------------------------------------------
swap("hlavicka-2", """# Citat rozpocet odtial bola chyba: kazde rano sme precitali vlastny vcerajsi
# zvysok a rozpocet sa scvrkaval. Zapis limitu ide cez endpoint""", """# Citat rozpocet odtial bola chyba: kazde rano sme precitali vlastny vcerajsi
# zvysok a rozpocet sa scvrkaval. Ked sa vsak limit vo FL zmeni tak, ze to
# nesposobil nas zapis, je to skutocna zmena od rodica - tu prevezmeme
# (simona_cas_fl_zmena) a prepiseme nou aj kopiu rozvrhu.
# Zapis limitu ide cez endpoint""")


open(p, "w", encoding="utf-8").write(s)
print("OK:", ", ".join(done) if done else "uz bolo aplikovane")
