#!/usr/bin/env python3
"""Uplny zamok (simona_zamok.yaml) musi vidiet zapnute PC aj pri pozastavenom
zdielanom case.

Hlasenie agenta (webhook, kazdych 30 s) zastavovala hned prva podmienka
simona_cas_pc_hlasenie "zdielany cas zapnuty". Teraz hlasenie prejde aj
vtedy, ked je zapnuty zamok, a ako prve zapise
input_datetime.simona_zamok_pc_ozvanie (na to reaguje simona_zamok_pc_zapnute).
Zvysok - kontakt, spotreba, vstup - bezi ako doteraz len pri zapnutom
zdielani; input_datetime.simona_pc_kontakt sa pri pauze zamerne nemeni,
inak by po obnoveni zdielania prisny strop rastu spotreby (odstup od
kontaktu) zahodil skutocny narast ako nehodnoverny.

Idempotentne. Pouzitie: python3 patch-zamok-pc.py simona_cas.yaml
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


swap("hlasenie-zamok", """        local_only: true
    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: template
        value_template: "{{ trigger.json is defined and trigger.json.used is defined }}"
    actions:
      - variables:
          novy: >-
""", """        local_only: true
    conditions:
      - condition: or
        conditions:
          - condition: state
            entity_id: input_boolean.simona_zdielany_cas
            state: "on"
          - condition: state
            entity_id: input_boolean.simona_uplny_zamok
            state: "on"
      - condition: template
        value_template: "{{ trigger.json is defined and trigger.json.used is defined }}"
    actions:
      # Uplny zamok (simona_zamok.yaml) vidi zapnute PC aj pri pozastavenom
      # zdielani - kontakt sa vtedy nezapisuje (skreslil by odstup nizsie).
      - if:
          - condition: state
            entity_id: input_boolean.simona_uplny_zamok
            state: "on"
        then:
          - action: input_datetime.set_datetime
            target:
              entity_id: input_datetime.simona_zamok_pc_ozvanie
            data:
              datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - variables:
          novy: >-
""")

open(p, "w", encoding="utf-8").write(s)
print(p, "hotovo:", ", ".join(done) if done else "nic (uz bolo aplikovane)")
