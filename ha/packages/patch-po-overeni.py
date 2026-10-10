#!/usr/bin/env python3
"""Opravy v simona_cas.yaml po overeni systemu bez Family Link (4. 10. 2026).

1. Polnoc: medzi 00:00 a 00:05 HA neposiela tabletu ciel. PC je v noci
   vacsinou vypnute, input_number.simona_pc_pouzite tak do resetu o 00:06
   drzi vcerajsie minuty a ciel (R - PC) by na novy den mohol byt prisnejsi,
   krajne 0. Most vcerajsi ciel a pravidlo HA po polnoci zahodi sam, takze
   do 00:06 ide tablet podla zachrannej siete appky (60 / 180 min). Prvy ciel
   noveho dna ide hned po resete (zmena ciela) a pre istotu o 00:06:30.
2. Restart add-onu TimeLimit (watchdog, rebuild) spravi na chvilu celu
   retaz minut tabletu nedostupnou; numeric_state triggery by po navrate
   vystrelili znova a rodicom by prisla druha sprava "minul sa cas". Prechod
   z unknown/unavailable sa preto za prekrocenie neberie.
3. V upozorneniach rodicom PC minuty zapocitane (sensor.simona_pc_zapocitane)
   - rovnako ako tablet a ako /cas; surove minuty nesedeli v rezime bez
   limitu. (Sprava o vypnuti PC ostava, zmeni ju az patch-prezencia.py.)

Idempotentne. Pouzitie: python3 patch-po-overeni.py simona_cas.yaml
"""
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
done = []


def swap(name, old, new):
    global s
    n = s.count(old)
    if n == 1:
        s = s.replace(old, new)
        done.append(name)
        return
    assert n == 0 and new in s, f"{name}: vzor sedi {n}x"


swap("polnoc-komentar", """  # vypnutie PC o polnoci). Do 00:06 plati vcerajsi rozpocet - minuty noveho
  # dna su vtedy takmer nulove, takze to je nanajvys o chvilu volnejsie.
""", """  # vypnutie PC o polnoci). Do 00:06 HA tabletu ciel neposiela (viz
  # simona_cas_sync_tabletu_timelimit) a tablet ide podla zachrannej siete
  # appky.
""")

swap("sync-polnoc", """  # Ciel plati len na den, v ktory prisiel - vcerajsi ciel aj pravidlo HA
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
        value_template: "{{ has_value('sensor.simona_tablet_cielovy_limit') }}"
""", """  # Ciel plati len na den, v ktory prisiel - vcerajsi ciel aj pravidlo HA
  # most po polnoci zahodi sam.
  #
  # Od 00:00 do 00:05 sa neposiela nic: PC je v noci vacsinou vypnute a do
  # resetu o 00:06 drzi vcerajsie minuty, ciel na novy den by tak mohol byt
  # prisnejsi (krajne 0). Tablet ide medzitym podla zachrannej siete appky;
  # prvy ciel noveho dna ide hned po resete (zmena ciela), poistne o 00:06:30.
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
      - trigger: time
        at: "00:06:30"
    conditions:
      - condition: template
        value_template: "{{ not (now().hour == 0 and now().minute < 6) }}"
      - condition: template
        value_template: "{{ has_value('sensor.simona_tablet_cielovy_limit') }}"
""")

swap("varovania-restart", """    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: state
        entity_id: input_boolean.simona_bez_limitu
        state: "off"
    actions:
      - variables:
          sprava: >-
            {% set t = states('sensor.simona_tablet_pouzite') | int(0) %}
            {% set p = states('input_number.simona_pc_pouzite') | int(0) %}
""", """    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: state
        entity_id: input_boolean.simona_bez_limitu
        state: "off"
      # navrat z nedostupnosti (restart add-onu TimeLimit) nie je prekrocenie
      - condition: template
        value_template: >-
          {{ trigger.from_state is not none
             and trigger.from_state.state not in ['unknown', 'unavailable'] }}
    actions:
      - variables:
          sprava: >-
            {% set t = states('sensor.simona_tablet_pouzite') | int(0) %}
            {% set p = states('sensor.simona_pc_zapocitane') | int(0) %}
""")

swap("vypnutie-restart", """      - condition: numeric_state
        entity_id: sensor.simona_cas_zostava
        below: 1
      # Ked PC nebezi, nie je co vypinat - vypne sa az ked ho zapne.
""", """      - condition: numeric_state
        entity_id: sensor.simona_cas_zostava
        below: 1
      # navrat zostatku z nedostupnosti (restart add-onu TimeLimit) nie je
      # "cas sa prave minul"
      - condition: template
        value_template: >-
          {{ trigger.platform != 'numeric_state'
             or (trigger.from_state is not none
                 and trigger.from_state.state not in ['unknown', 'unavailable']) }}
      # Ked PC nebezi, nie je co vypinat - vypne sa az ked ho zapne.
""")

open(p, "w", encoding="utf-8").write(s)
print(p, "hotovo:", ", ".join(done) if done else "nic (uz bolo aplikovane)")
