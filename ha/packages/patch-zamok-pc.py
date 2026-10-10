#!/usr/bin/env python3
"""Uplny zamok (simona_zamok.yaml) musi vidiet zapnute PC aj pri pozastavenom
zdielanom case.

Hlasenie agenta (webhook, kazdych 30 s) zastavovala hned prva podmienka
simona_cas_pc_hlasenie "zdielany cas zapnuty". Teraz kazde hlasenie najprv
zapise input_datetime.simona_zamok_pc_ozvanie (z neho binary_sensor
.simona_zamok_pc_zapnute, na neho reaguje simona_zamok_pc_zapnute) a az
potom sa pri pozastavenom zdielani zastavi. Zvysok - kontakt, spotreba,
vstup - bezi ako doteraz len pri zapnutom zdielani;
input_datetime.simona_pc_kontakt sa pri pauze zamerne nemeni, inak by po
obnoveni zdielania prisny strop rastu spotreby (odstup od kontaktu) zahodil
skutocny narast ako nehodnoverny.

Dalej:
- hlasenie zapise aj start Windows (input_datetime.simona_pc_start z
  uptime_sec, agent 1.2.2+; starsi agent -> 1970) - zamok podla neho
  rozozna nove zapnutie PC od zruseneho vypnutia;
- vypnutie po vycerpani casu, upozornenie "PC po limite" a "PC sa prestal
  hlasit" sa pocas zamku nespustaju - PC vypina zamok (a ticho po jeho
  vypnuti nie je zamrznuty agent).

Idempotentne. Pouzitie: python3 patch-zamok-pc.py simona_cas.yaml
"""
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
done = []


def swap(name, old, new, applied=None):
    """applied: znacka, ze zmena uz je v subore (ked ju neskorsia zmena
    upravila a `new` uz doslovne nesedi)."""
    global s
    if new in s or (applied and applied in s):
        return
    n = s.count(old)
    assert n == 1, f"{name}: vzor sedi {n}x"
    s = s.replace(old, new)
    done.append(name)


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
      - condition: template
        value_template: "{{ trigger.json is defined and trigger.json.used is defined }}"
    actions:
      # Kazde hlasenie, aj pri pozastavenom zdielani - podla neho uplny zamok
      # (simona_zamok.yaml) vidi zapnute PC. Kontakt sa pri pauze nezapisuje
      # (skreslil by odstup nizsie).
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
""", applied="entity_id: input_datetime.simona_zamok_pc_ozvanie")

swap("hlasenie-start", """      # Kazde hlasenie, aj pri pozastavenom zdielani - podla neho uplny zamok
      # (simona_zamok.yaml) vidi zapnute PC. Kontakt sa pri pauze nezapisuje
      # (skreslil by odstup nizsie).
      - action: input_datetime.set_datetime
""", """      # Start Windows (agent 1.2.2+ posiela uptime_sec, inak 1970) - PRED
      # ozvanim, na ktore reaguje uplny zamok.
      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.simona_pc_start
        data:
          timestamp: >-
            {% set up = trigger.json.uptime_sec | default(-1) | int(-1) %}
            {{ (as_timestamp(now()) - up) | int if up >= 0 else 0 }}
      # Kazde hlasenie, aj pri pozastavenom zdielani - podla neho uplny zamok
      # (simona_zamok.yaml) vidi zapnute PC. Kontakt sa pri pauze nezapisuje
      # (skreslil by odstup nizsie).
      - action: input_datetime.set_datetime
""")

swap("po-limite-vypnutie-zamok", """      # navrat zostatku z nedostupnosti (restart add-onu TimeLimit) nie je
      # "cas sa prave minul"
""", """      # Uplny zamok vypina PC sam (simona_zamok.yaml) - nemiesat sa do toho
      # a neminat dennu snimku vypnutia.
      - condition: state
        entity_id: input_boolean.simona_uplny_zamok
        state: "off"
      # navrat zostatku z nedostupnosti (restart add-onu TimeLimit) nie je
      # "cas sa prave minul"
""")

swap("po-limite-vypnutie-zamok-delay", """      - delay: "00:01:00"
      # Snimka az tesne pred vypnutim, nech sa tie 3 minuty po opatovnom
""", """      - delay: "00:01:00"
      # zamok zapnuty pocas tej minuty - PC vypina on, snimka ostava -1
      - condition: state
        entity_id: input_boolean.simona_uplny_zamok
        state: "off"
      # Snimka az tesne pred vypnutim, nech sa tie 3 minuty po opatovnom
""")

swap("po-limite-upozornenie-zamok", """      # Az ked uz raz po limite vypnuty bol ...
""", """      # pocas uplneho zamku PC vypina zamok a rodicom pise sam
      - condition: state
        entity_id: input_boolean.simona_uplny_zamok
        state: "off"
      # Az ked uz raz po limite vypnuty bol ...
""")

swap("ticho-zamok", """      # Ked sa cas nerata, mlciaci agent nic nestoji.
""", """      # Ticho po vypnuti uplnym zamkom nie je zamrznuty agent.
      - condition: template
        value_template: >-
          {{ is_state('input_boolean.simona_uplny_zamok', 'off')
             and (as_timestamp(states('input_datetime.simona_pc_kontakt'), 0)
                  - as_timestamp(states('input_datetime.simona_zamok_pc_vypnutie'), 0)) | abs > 300 }}
      # Ked sa cas nerata, mlciaci agent nic nestoji.
""")

open(p, "w", encoding="utf-8").write(s)
print(p, "hotovo:", ", ".join(done) if done else "nic (uz bolo aplikovane)")
