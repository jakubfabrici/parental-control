#!/usr/bin/env python3
"""Tyzdenny rozvrh rozpoctu v Home Assistante.

Preco vobec: polnocny reset bral rozpocet zo sensor.iplay_50_daily_limit,
lenze do toho senzora sa cez den zapisuje NAS VLASTNY override (integracia
cita len appliedTimeLimits, teda hodnotu platnu na dnes). Rano sme tak
precitali vcerajsi zvysok a rozpocet sa den po dni zmensoval:
180 -> 75 -> 61.

Tyzdenny rozvrh sa z Family Link vycitat neda - integracia ho nikde
nespristupnuje (parse_daily_limit_schedule v schedules.py sa nevola).
Preto ho drzime v HA ako sedem helperov a Family Link uz len plnime.

Idempotentne: opakovane spustenie nic nezmeni.
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


# --- 1. sedem helperov rozvrhu ---------------------------------------------
swap("helpery-rozvrhu", """input_number:
  simona_rozpocet_dnes:""", """input_number:
  # Tyzdenny rozvrh: kolko minut ma dieta na jednotlivy den. Je to KOPIA
  # rozvrhu z Family Link - ten sa cez integraciu vycitat neda (coordinator
  # cita len appliedTimeLimits, teda hodnotu platnu na dnes, do ktorej sme
  # sami zapisali override). Ked sa rozvrh vo Family Link zmeni, treba ho
  # prepisat aj tu.
  #
  # Hodnoty sa NEsetuju cez 'initial' - to by ich prepisalo pri kazdom
  # restarte HA a rucna zmena by neprezila. Nastavuju sa raz sluzbou
  # input_number.set_value a dalej si ich HA pamata.
  simona_rozvrh_po:
    name: Simona rozvrh pondelok
    min: 0
    max: 1440
    step: 5
    mode: box
    unit_of_measurement: min
    icon: mdi:calendar-clock

  simona_rozvrh_ut:
    name: Simona rozvrh utorok
    min: 0
    max: 1440
    step: 5
    mode: box
    unit_of_measurement: min
    icon: mdi:calendar-clock

  simona_rozvrh_st:
    name: Simona rozvrh streda
    min: 0
    max: 1440
    step: 5
    mode: box
    unit_of_measurement: min
    icon: mdi:calendar-clock

  simona_rozvrh_stv:
    name: Simona rozvrh štvrtok
    min: 0
    max: 1440
    step: 5
    mode: box
    unit_of_measurement: min
    icon: mdi:calendar-clock

  simona_rozvrh_pi:
    name: Simona rozvrh piatok
    min: 0
    max: 1440
    step: 5
    mode: box
    unit_of_measurement: min
    icon: mdi:calendar-clock

  simona_rozvrh_so:
    name: Simona rozvrh sobota
    min: 0
    max: 1440
    step: 5
    mode: box
    unit_of_measurement: min
    icon: mdi:calendar-weekend

  simona_rozvrh_ne:
    name: Simona rozvrh nedeľa
    min: 0
    max: 1440
    step: 5
    mode: box
    unit_of_measurement: min
    icon: mdi:calendar-weekend

  simona_rozpocet_dnes:""")


# --- 2. senzor "kolko ma byt dnes / zajtra" ---------------------------------
swap("senzor-rozvrhu", """      # Celkovy dostupny cas na dnes. Bonus pridany priamo v aplikacii Family""", """      # Kolko minut ma rozvrh na dnesny (a zajtrajsi) den. now().weekday()
      # vracia 0 = pondelok ... 6 = nedela.
      - name: Simona rozvrh dnes
        unique_id: simona_rozvrh_dnes
        unit_of_measurement: min
        device_class: duration
        icon: mdi:calendar-clock
        state: >-
          {% set dni = ['po','ut','st','stv','pi','so','ne'] %}
          {{ states('input_number.simona_rozvrh_' ~ dni[now().weekday()]) | int(0) }}
        attributes:
          den: >-
            {{ ['pondelok','utorok','streda','štvrtok','piatok','sobota','nedeľa'][now().weekday()] }}
          zajtra: >-
            {% set dni = ['po','ut','st','stv','pi','so','ne'] %}
            {{ states('input_number.simona_rozvrh_' ~ dni[(now().weekday() + 1) % 7]) | int(0) }}

      # Celkovy dostupny cas na dnes. Bonus pridany priamo v aplikacii Family""")


# --- 3. polnocny reset berie rozpocet z rozvrhu, nie z Family Link ----------
swap("polnocny-reset", """  # -- Polnocny start dna -----------------------------------------------------
  # Rozpocet na dnes berieme z rozvrhu Family Link: sensor.iplay_50_daily_limit
  # po polnoci uz ukazuje hodnotu pre novy den. PC pocitadlo nulujeme.
  - id: simona_cas_polnocny_reset
    alias: "Simona čas: polnočný reset rozpočtu"
    mode: single
    triggers:
      - trigger: time
        at: "00:05:00"
    actions:
      - action: homeassistant.update_entity
        target:
          entity_id:
            - sensor.iplay_50_daily_limit
            - sensor.iplay_50_screen_time_remaining
      - delay: "00:00:20"
      - action: input_number.set_value""", """  # -- Polnocny start dna -----------------------------------------------------
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
        target:
          entity_id:
            - sensor.iplay_50_daily_limit
            - sensor.iplay_50_screen_time_remaining
      - delay: "00:00:20"
      - action: input_number.set_value""")

swap("reset-z-rozvrhu", """      # Rozpocet prepiseme len ked ma Family Link platnu hodnotu; inak
      # nechame vcerajsiu a radsej na to upozornime.
      - if:
          - condition: template
            value_template: >-
              {{ has_value('sensor.iplay_50_daily_limit')
                 and (states('sensor.iplay_50_daily_limit') | int(0)) > 0 }}
        then:
          - action: input_number.set_value
            target:
              entity_id: input_number.simona_rozpocet_dnes
            data:
              value: "{{ states('sensor.iplay_50_daily_limit') | int }}"
        else:
          - action: telegram_bot.send_message
            data:
              chat_id: 5756450012
              parse_mode: html
              message: >-
                ⚠️ Family Link nevrátil denný limit, rozpočet ostal na
                {{ states('input_number.simona_rozpocet_dnes') | int }} min z včera.""", """      # Rozpocet na novy den podla rozvrhu. Je to lokalna hodnota, takze
      # vzdy existuje - nic tu nemoze zlyhat na nedostupnom Google API.
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_rozpocet_dnes
        data:
          value: "{{ states('sensor.simona_rozvrh_dnes') | int(0) }}\"""")


# --- 4. vecerne upratanie vracia hodnotu rozvrhu, nie rozpocet --------------
swap("vecerne-upratanie", """  # -- Vecerne upratanie ------------------------------------------------------
  # Override vratime na povodnu hodnotu rozvrhu, nech po nas v Google
  # nezostane nic, co by ovplyvnilo dalsie dni.
  - id: simona_cas_vecerne_upratanie
    alias: "Simona čas: vrátiť limit podľa rozvrhu"
    mode: single
    triggers:
      - trigger: time
        at: "23:57:00"
    conditions:
      - condition: template
        value_template: >-
          {{ has_value('sensor.iplay_50_daily_limit')
             and (states('sensor.iplay_50_daily_limit') | int(-1))
                 != (states('input_number.simona_rozpocet_dnes') | int(-2)) }}
    actions:
      - action: familylink.set_daily_limit
        data:
          entity_id: switch.iplay_50
          daily_minutes: "{{ states('input_number.simona_rozpocet_dnes') | int }}\"""", """  # -- Vecerne upratanie ------------------------------------------------------
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
      - condition: template
        value_template: >-
          {{ has_value('sensor.iplay_50_daily_limit')
             and (states('sensor.iplay_50_daily_limit') | int(-1))
                 != (states('sensor.simona_rozvrh_dnes') | int(-2)) }}
    actions:
      - action: familylink.set_daily_limit
        data:
          entity_id: switch.iplay_50
          daily_minutes: "{{ states('sensor.simona_rozvrh_dnes') | int }}\"""")


# --- 5. hlavicka suboru ----------------------------------------------------
swap("hlavicka", """# Rozvrh zostava vo Family Link. Zapis limitu ide cez endpoint
# timeLimitOverrides:batchCreate, teda je to override na DNESNY den -
# tyzdenny rozvrh sa nemeni. Pre istotu ho o 23:57 vraciame na povodnu
# hodnotu, aby po nas nezostal ziadny override.""", """# Rozvrh je v HA (input_number.simona_rozvrh_po ... _ne) ako kopia rozvrhu
# z Family Link - ten sa cez integraciu vycitat NEDA, coordinator sprístupnuje
# len appliedTimeLimits (hodnotu platnu na dnes, vratane nasho override).
# Citat rozpocet odtial bola chyba: kazde rano sme precitali vlastny vcerajsi
# zvysok a rozpocet sa scvrkaval. Zapis limitu ide cez endpoint
# timeLimitOverrides:batchCreate, teda je to override na DNESNY den -
# tyzdenny rozvrh v Google sa nemeni. O 23:57 ho vraciame na hodnotu rozvrhu,
# aby po nas nezostal ziadny override.""")


open(p, "w", encoding="utf-8").write(s)
print("OK:", ", ".join(done) if done else "uz bolo aplikovane")
