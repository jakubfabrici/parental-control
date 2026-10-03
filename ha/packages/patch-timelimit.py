#!/usr/bin/env python3
"""Zdielany cas: tablet z TimeLimit namiesto Family Link (prepinatelne).

Family Link integracia (neoficialne API Googlu) od 2026-10-02 13:34 nefunguje
(auth server vracia 403) a vsetky jej entity su unavailable. Fail-safe vtedy
nerobi nic, lenze sensor.simona_pc_povolene je tiez unavailable a tik na PC
z neho cez int(0) posiela strop 0 - tablet sa neratal vobec a PC dostaval nulu.

Tablet teraz moze ist cez TimeLimit (add-on + most do HA, viď
ha/addons/timelimit/). Zdroj vybera input_select.simona_tablet_zdroj:

  TimeLimit    minuty = sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes
               (kategoria s limitom; Allowed Apps sa nerataju, rovnako ako
               "vzdy povolene" vo Family Link). Strop = cielovy cas na dnes,
               ktory most premieta do vlastneho pravidla HA a extra casu
               (mqtt timelimit/cmd set_total). Bonus FL sa nepripocitava.
  Family Link  presne ako doteraz.

Pri TimeLimit sa nepouziva ozvena zapisov, prebratie zmeny z FL ani vecerne
vratenie overridu - rozvrh je v appke a HA pise len do vlastneho pravidla.

Idempotentne.
"""
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
done = []


def swap(name, old, new, count=1):
    global s
    if new in s:
        return
    assert s.count(old) == count, f"{name}: vzor sedi {s.count(old)}x, cakal som {count}x"
    s = s.replace(old, new)
    done.append(name)


ZDROJ_TL = "is_state('input_select.simona_tablet_zdroj', 'TimeLimit')"
ZDROJ_FL = "is_state('input_select.simona_tablet_zdroj', 'Family Link')"
RAW_FL = "state_attr('sensor.iplay_50_screen_time_remaining', 'used_minutes') | int(0)"

# --- 1. prepinac zdroja ------------------------------------------------------
swap("input_select", "input_boolean:\n", """# Odkial berieme minuty a kam piseme strop tabletu. Prva moznost je
# predvolena pri prvom vytvoreni; potom si HA pamata poslednu volbu.
input_select:
  simona_tablet_zdroj:
    name: Simona tablet – zdroj
    icon: mdi:tablet-cellphone
    options:
      - TimeLimit
      - Family Link

input_boolean:
""")

# --- 2. surove minuty tabletu podla zdroja ------------------------------------
# najprv vsetky citania surovych minut FL (pouzite state + atribut, snimka a offset
# pri rezime bez limitu) -> spolocny senzor
swap("surove minuty", RAW_FL, "states('sensor.simona_tablet_namerane') | int(0)", count=4)

swap("namerane senzor", """      - name: Simona tablet použité
        unique_id: simona_tablet_pouzite""", """      # Surove minuty tabletu dnes zo zvoleneho zdroja (pred odpocitanim
      # nezapocitanych). Pri TimeLimit len kategoria s limitom - Allowed Apps
      # su povolene stale a do spolocneho casu sa nerataju.
      - name: Simona tablet namerané
        unique_id: simona_tablet_namerane
        unit_of_measurement: min
        device_class: duration
        state_class: measurement
        icon: mdi:tablet
        availability: >-
          {% if """ + ZDROJ_TL + """ %}
          {{ has_value('sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes') }}
          {% else %}
          {{ has_value('sensor.iplay_50_screen_time_remaining') }}
          {% endif %}
        state: >-
          {% if """ + ZDROJ_TL + """ %}
          {{ states('sensor.timelimit_simonka_ostatne_aplikacie_pouzite_dnes') | int(0) }}
          {% else %}
          {{ """ + RAW_FL + """ }}
          {% endif %}
        attributes:
          zdroj: "{{ states('input_select.simona_tablet_zdroj') }}"

      - name: Simona tablet použité
        unique_id: simona_tablet_pouzite""")

swap("pouzite availability", "        availability: \"{{ has_value('sensor.iplay_50_screen_time_remaining') }}\"\n",
     "        availability: \"{{ has_value('sensor.simona_tablet_namerane') }}\"\n")

# --- 3. bonus Family Link len pri zdroji Family Link --------------------------
swap("bonus", "             + (states('sensor.iplay_50_active_bonus') | int(0)) }}",
     "             + ((states('sensor.iplay_50_active_bonus') | int(0)) if " + ZDROJ_FL + " else 0) }}")

# --- 4. Family Link automatizacie len pri zdroji Family Link ------------------
FL_COND = """      - condition: state
        entity_id: input_select.simona_tablet_zdroj
        state: Family Link
"""
swap("fl_zmena len FL", """    triggers:
      - trigger: state
        entity_id: sensor.iplay_50_daily_limit
    conditions:
""", """    triggers:
      - trigger: state
        entity_id: sensor.iplay_50_daily_limit
    conditions:
""" + FL_COND)

swap("sync len FL", """      - trigger: time_pattern
        minutes: "/5"
    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: template
        value_template: "{{ has_value('sensor.simona_tablet_cielovy_limit') }}"
      - condition: template
        value_template: "{{ has_value('sensor.iplay_50_daily_limit') }}"
""", """      - trigger: time_pattern
        minutes: "/5"
    conditions:
""" + FL_COND + """      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: template
        value_template: "{{ has_value('sensor.simona_tablet_cielovy_limit') }}"
      - condition: template
        value_template: "{{ has_value('sensor.iplay_50_daily_limit') }}"
""")

swap("vecerne len FL", """        at: "23:57:00"
    conditions:
""", """        at: "23:57:00"
    conditions:
""" + FL_COND)

swap("update_entity tolerantne", """      - action: homeassistant.update_entity
        target:
          entity_id:
            - sensor.iplay_50_daily_limit""", """      - action: homeassistant.update_entity
        continue_on_error: true
        target:
          entity_id:
            - sensor.iplay_50_daily_limit""")

# --- 5. TimeLimit: cielovy cas na dnes cez most -------------------------------
swap("sync TimeLimit", "  # -- Prepocet stropu pre tablet --------------------------------------------\n",
"""  # -- Strop tabletu cez TimeLimit --------------------------------------------
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
        value_template: "{{ has_value('sensor.simona_tablet_cielovy_limit') }}"
    actions:
      - action: mqtt.publish
        data:
          topic: timelimit/cmd
          payload: >-
            {% if is_state('input_boolean.simona_zdielany_cas', 'on') %}
            {{ {'action': 'set_total', 'child': 'Simonka', 'category': 'Ostatné aplikácie',
                'minutes': states('sensor.simona_tablet_cielovy_limit') | int(0)} | to_json }}
            {% else %}
            {{ {'action': 'clear_total', 'child': 'Simonka', 'category': 'Ostatné aplikácie'} | to_json }}
            {% endif %}

  # Pri prepnuti spat na Family Link cielovy cas v TimeLimit zrusime.
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
""")

open(p, "w", encoding="utf-8").write(s)
print("hotovo:", ", ".join(done) if done else "nic (uz bolo aplikovane)")
