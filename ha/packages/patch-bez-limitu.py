#!/usr/bin/env python3
"""Prida rezim "bez limitu" do simona_cas.yaml.

Kym je zapnuty, cas sa NERATA. Nestaci prestat vynucovat - Family Link aj
agent meraju dalej, tak si pri zapnuti odlozime snapshot a pri vypnuti
rozdiel pripocitame do offsetu. Zapocitana spotreba tak po vypnuti
pokracuje presne tam, kde prestala.

Spusta sa rovnako lokalne aj na HA, aby oba subory zostali identicke.
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


# --- 1. prepinac + pocitadla ------------------------------------------------
swap("helpery", """  # Hlasi agent v kazdom ticku: sedi teraz niekto realne pri PC?
  simona_pc_pouziva_sa:
    name: Simona PC sa používa
    icon: mdi:account-clock
""", """  # Hlasi agent v kazdom ticku: sedi teraz niekto realne pri PC?
  simona_pc_pouziva_sa:
    name: Simona PC sa používa
    icon: mdi:account-clock

  # Rezim "bez limitu": cas sa neratá ani na jednom zariadeni.
  simona_bez_limitu:
    name: Simona bez limitu
    icon: mdi:infinity
""")

swap("pocitadla", """input_datetime:
  simona_pc_kontakt:""", """  # Minuty, ktore sa nezapocitavaju - narastu vzdy o to, co pribudlo
  # pocas rezimu "bez limitu".
  simona_offset_tablet:
    name: Simona nezapočítané minúty tablet
    min: 0
    max: 1440
    step: 1
    mode: box
    unit_of_measurement: min
    icon: mdi:tablet-cancel

  simona_offset_pc:
    name: Simona nezapočítané minúty PC
    min: 0
    max: 1440
    step: 1
    mode: box
    unit_of_measurement: min
    icon: mdi:monitor-off

  # Stav v okamihu zapnutia rezimu, aby sme po vypnuti vedeli, kolko
  # minut medzitym pribudlo.
  simona_snap_tablet:
    name: Simona snímka tablet
    min: 0
    max: 1440
    step: 1
    mode: box
    unit_of_measurement: min
    icon: mdi:camera-timer

  simona_snap_pc:
    name: Simona snímka PC
    min: 0
    max: 1440
    step: 1
    mode: box
    unit_of_measurement: min
    icon: mdi:camera-timer

input_datetime:
  simona_pc_kontakt:""")

# --- 2. zapocitana spotreba tabletu ----------------------------------------
swap("tablet", """        availability: "{{ has_value('sensor.iplay_50_screen_time_remaining') }}"
        state: >-
          {{ state_attr('sensor.iplay_50_screen_time_remaining', 'used_minutes') | int(0) }}""",
     """        availability: "{{ has_value('sensor.iplay_50_screen_time_remaining') }}"
        state: >-
          {% set raw = state_attr('sensor.iplay_50_screen_time_remaining', 'used_minutes') | int(0) %}
          {% set off = states('input_number.simona_offset_tablet') | int(0) %}
          {% if is_state('input_boolean.simona_bez_limitu', 'on') %}
          {{ [ (states('input_number.simona_snap_tablet') | int(0)) - off, 0 ] | max }}
          {% else %}
          {{ [ raw - off, 0 ] | max }}
          {% endif %}
        attributes:
          namerane: "{{ state_attr('sensor.iplay_50_screen_time_remaining', 'used_minutes') | int(0) }}"
          nezapocitane: "{{ states('input_number.simona_offset_tablet') | int(0) }}\"""")

# --- 3. zapocitana spotreba PC ---------------------------------------------
swap("pc-zapocitane", """      - name: Simona čas použitý""", """      # To iste pre PC: agent hlasi namerane minuty, my z nich odpocitame
      # tie, ktore padli do rezimu "bez limitu".
      - name: Simona PC započítané
        unique_id: simona_pc_zapocitane
        unit_of_measurement: min
        device_class: duration
        state_class: measurement
        icon: mdi:desktop-tower-monitor
        state: >-
          {% set raw = states('input_number.simona_pc_pouzite') | int(0) %}
          {% set off = states('input_number.simona_offset_pc') | int(0) %}
          {% if is_state('input_boolean.simona_bez_limitu', 'on') %}
          {{ [ (states('input_number.simona_snap_pc') | int(0)) - off, 0 ] | max }}
          {% else %}
          {{ [ raw - off, 0 ] | max }}
          {% endif %}
        attributes:
          namerane: "{{ states('input_number.simona_pc_pouzite') | int(0) }}"
          nezapocitane: "{{ states('input_number.simona_offset_pc') | int(0) }}"

      - name: Simona čas použitý""")

swap("spolu", """        state: >-
          {{ (states('sensor.simona_tablet_pouzite') | int(0))
             + (states('input_number.simona_pc_pouzite') | int(0)) }}
        attributes:
          tablet: "{{ states('sensor.simona_tablet_pouzite') | int(0) }}"
          pc: "{{ states('input_number.simona_pc_pouzite') | int(0) }}\"""",
     """        state: >-
          {{ (states('sensor.simona_tablet_pouzite') | int(0))
             + (states('sensor.simona_pc_zapocitane') | int(0)) }}
        attributes:
          tablet: "{{ states('sensor.simona_tablet_pouzite') | int(0) }}"
          pc: "{{ states('sensor.simona_pc_zapocitane') | int(0) }}\"""")

# --- 4. stropy ------------------------------------------------------------
# Family Link porovnava limit proti SVOJIM nameranym minutam, nie proti
# nasim zapocitanym - preto sa offset musi k stropu pripocitat.
swap("strop-tabletu", """        state: >-
          {{ [ [ (states('input_number.simona_rozpocet_dnes') | int(0))
                 - (states('input_number.simona_pc_pouzite') | int(0)), 0 ] | max, 1440 ] | min }}""",
     """        state: >-
          {% if is_state('input_boolean.simona_bez_limitu', 'on') %}
          1440
          {% else %}
          {{ [ [ (states('input_number.simona_offset_tablet') | int(0))
                 + (states('input_number.simona_rozpocet_dnes') | int(0))
                 - (states('sensor.simona_pc_zapocitane') | int(0)), 0 ] | max, 1440 ] | min }}
          {% endif %}""")

swap("strop-pc", """        state: >-
          {{ [ [ (states('sensor.simona_rozpocet_celkom') | int(0))
                 - (states('sensor.simona_tablet_pouzite') | int(0)), 0 ] | max, 1440 ] | min }}""",
     """        state: >-
          {% if is_state('input_boolean.simona_bez_limitu', 'on') %}
          1440
          {% else %}
          {{ [ [ (states('input_number.simona_offset_pc') | int(0))
                 + (states('sensor.simona_rozpocet_celkom') | int(0))
                 - (states('sensor.simona_tablet_pouzite') | int(0)), 0 ] | max, 1440 ] | min }}
          {% endif %}""")

# --- 5. zapnutie a vypnutie rezimu ----------------------------------------
swap("automatizacie", """  # -- Prepocet stropu pre tablet --------------------------------------------""",
     """  # -- Rezim "bez limitu" ----------------------------------------------------
  # Pri zapnuti si odlozime, kde obe strany prave su. Merat nikomu
  # nezakazeme (ani sa neda), len si zapamatame, odkial dalej neratat.
  - id: simona_bez_limitu_zapnutie
    alias: "Simona čas: začiatok režimu bez limitu"
    mode: single
    triggers:
      - trigger: state
        entity_id: input_boolean.simona_bez_limitu
        from: "off"
        to: "on"
    actions:
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_snap_tablet
        data:
          value: >-
            {{ state_attr('sensor.iplay_50_screen_time_remaining', 'used_minutes') | int(0) }}
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_snap_pc
        data:
          value: "{{ states('input_number.simona_pc_pouzite') | int(0) }}"

  # Pri vypnuti pripocitame do offsetu vsetko, co medzitym pribudlo -
  # zapocitana spotreba tak pokracuje presne tam, kde prestala.
  - id: simona_bez_limitu_vypnutie
    alias: "Simona čas: koniec režimu bez limitu"
    mode: single
    triggers:
      - trigger: state
        entity_id: input_boolean.simona_bez_limitu
        from: "on"
        to: "off"
    actions:
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_offset_tablet
        data:
          value: >-
            {% set raw = state_attr('sensor.iplay_50_screen_time_remaining', 'used_minutes') | int(0) %}
            {% set snap = states('input_number.simona_snap_tablet') | int(0) %}
            {{ [ (states('input_number.simona_offset_tablet') | int(0)) + [ raw - snap, 0 ] | max, 1440 ] | min }}
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_offset_pc
        data:
          value: >-
            {% set raw = states('input_number.simona_pc_pouzite') | int(0) %}
            {% set snap = states('input_number.simona_snap_pc') | int(0) %}
            {{ [ (states('input_number.simona_offset_pc') | int(0)) + [ raw - snap, 0 ] | max, 1440 ] | min }}

  # -- Prepocet stropu pre tablet --------------------------------------------""")

# --- 6. polnocny reset zahrna aj offsety ----------------------------------
swap("polnocny-reset", """      - action: input_number.set_value
        target:
          entity_id: input_number.simona_pc_pouzite
        data:
          value: 0""", """      - action: input_number.set_value
        target:
          entity_id:
            - input_number.simona_pc_pouzite
            - input_number.simona_offset_tablet
            - input_number.simona_offset_pc
            - input_number.simona_snap_tablet
            - input_number.simona_snap_pc
        data:
          value: 0""")

# --- 7. pocas rezimu ziadne varovania ani hlasenia ------------------------
swap("varovania", """    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
    actions:
      - variables:
          sprava: >-""", """    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: state
        entity_id: input_boolean.simona_bez_limitu
        state: "off"
    actions:
      - variables:
          sprava: >-""")

swap("pc-po-limite", """      - condition: numeric_state
        entity_id: sensor.simona_cas_zostava
        below: 1""", """      - condition: state
        entity_id: input_boolean.simona_bez_limitu
        state: "off"
      - condition: numeric_state
        entity_id: sensor.simona_cas_zostava
        below: 1""")

open(p, "w", encoding="utf-8").write(s)
print("upravene:", ", ".join(done) if done else "(nic, uz bolo)")
