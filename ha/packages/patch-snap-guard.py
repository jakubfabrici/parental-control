#!/usr/bin/env python3
"""Poistka proti falosnemu ukonceniu rezimu "bez limitu".

Co sa stalo v prevadzke: pri reload_all sa input_boolean obnovil ako "on"
a hned presiel na "off". Automatizacia ukoncenia to vzala ako skutocne
vypnutie rezimu, ale snimka bola medzitym vynulovana - a tak sa vsetkych
59 nameranych minut odpisalo ako nezapocitanych.

Riesenie: snimka ma teraz min -1 a hodnota -1 znamena "rezim nebezi".
Ukoncenie pripocita offset LEN ked je snimka >= 0, a hned ju vrati na -1.
Reload tak nema co odpisat.
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


# --- snimky smu byt -1 = "rezim nebezi" ------------------------------------
swap("snap-tablet-min", """  simona_snap_tablet:
    name: Simona snímka tablet
    min: 0""", """  simona_snap_tablet:
    name: Simona snímka tablet
    min: -1""")

swap("snap-pc-min", """  simona_snap_pc:
    name: Simona snímka PC
    min: 0""", """  simona_snap_pc:
    name: Simona snímka PC
    min: -1""")

# --- ukoncenie: len ked snimka naozaj existuje -----------------------------
swap("koniec-podmienka", """      - trigger: state
        entity_id: input_boolean.simona_bez_limitu
        from: "on"
        to: "off"
    actions:
      - action: input_number.set_value""", """      - trigger: state
        entity_id: input_boolean.simona_bez_limitu
        from: "on"
        to: "off"
    conditions:
      # Snimka -1 znamena, ze rezim nebezal. Pri reload_all sa prepinac
      # obnovi ako "on" a hned prepne na "off" - bez tejto podmienky by
      # sme vtedy odpisali celu dnesnu spotrebu ako nezapocitanu.
      - condition: numeric_state
        entity_id: input_number.simona_snap_pc
        above: -1
    actions:
      - action: input_number.set_value""")

# --- ukoncenie snimky vratime na -1 ----------------------------------------
swap("koniec-reset-snimok", """            {% set raw = states('input_number.simona_pc_pouzite') | int(0) %}
            {% set snap = states('input_number.simona_snap_pc') | int(0) %}
            {{ [ (states('input_number.simona_offset_pc') | int(0)) + [ raw - snap, 0 ] | max, 1440 ] | min }}""",
     """            {% set raw = states('input_number.simona_pc_pouzite') | int(0) %}
            {% set snap = states('input_number.simona_snap_pc') | int(0) %}
            {{ [ (states('input_number.simona_offset_pc') | int(0)) + [ raw - snap, 0 ] | max, 1440 ] | min }}
      # Snimky spat na -1, nech dalsi reload nema co odpisat.
      - action: input_number.set_value
        target:
          entity_id:
            - input_number.simona_snap_tablet
            - input_number.simona_snap_pc
        data:
          value: -1""")

# --- polnocny reset: snimky na -1, nie na 0 --------------------------------
swap("polnoc", """          entity_id:
            - input_number.simona_pc_pouzite
            - input_number.simona_offset_tablet
            - input_number.simona_offset_pc
            - input_number.simona_snap_tablet
            - input_number.simona_snap_pc
        data:
          value: 0""", """          entity_id:
            - input_number.simona_pc_pouzite
            - input_number.simona_offset_tablet
            - input_number.simona_offset_pc
        data:
          value: 0
      - action: input_number.set_value
        target:
          entity_id:
            - input_number.simona_snap_tablet
            - input_number.simona_snap_pc
        data:
          value: -1""")

# --- senzory: pri -1 sa zmrazit neda, brat namerane ------------------------
swap("tablet-senzor", """          {% if is_state('input_boolean.simona_bez_limitu', 'on') %}
          {{ [ (states('input_number.simona_snap_tablet') | int(0)) - off, 0 ] | max }}
          {% else %}
          {{ [ raw - off, 0 ] | max }}
          {% endif %}""", """          {% set snap = states('input_number.simona_snap_tablet') | int(-1) %}
          {% if is_state('input_boolean.simona_bez_limitu', 'on') and snap >= 0 %}
          {{ [ snap - off, 0 ] | max }}
          {% else %}
          {{ [ raw - off, 0 ] | max }}
          {% endif %}""")

swap("pc-senzor", """          {% if is_state('input_boolean.simona_bez_limitu', 'on') %}
          {{ [ (states('input_number.simona_snap_pc') | int(0)) - off, 0 ] | max }}
          {% else %}
          {{ [ raw - off, 0 ] | max }}
          {% endif %}""", """          {% set snap = states('input_number.simona_snap_pc') | int(-1) %}
          {% if is_state('input_boolean.simona_bez_limitu', 'on') and snap >= 0 %}
          {{ [ snap - off, 0 ] | max }}
          {% else %}
          {{ [ raw - off, 0 ] | max }}
          {% endif %}""")

open(p, "w", encoding="utf-8").write(s)
print("upravene:", ", ".join(done) if done else "(nic, uz bolo)")
