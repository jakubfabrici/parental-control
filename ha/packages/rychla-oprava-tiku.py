#!/usr/bin/env python3
# Rychla oprava tiku z PC (3 zmeny, vsetky len v HA):
#  1) timeout 8 -> 20 s: agent request dostane, ale pod zatazou odpoveda
#     neskoro a HA ju po 8 s zahodi. V agent.log je to vidiet ako
#     "handle chyba: ... nonexistent network connection".
#  2) backoff podla veku kontaktu: po strate kontaktu sa este 10 minut
#     skusa kazdu minutu, nie raz za 5 minut.
#  3) spotreba je v ramci dna monotonna: ked agent stratil state.json
#     (13. 9. 2026 dvakrat), HA uz ten prepad na 0 nepreberie.
#
# Nasadene 13. 9. 2026 pocas incidentu "agent sa nehlasi 20 minut".
import sys

p = '/config/packages/simona_cas.yaml'
s = open(p, encoding='utf-8').read()
done = []


def swap(name, old, new):
    global s
    if new in s:
        return
    assert s.count(old) == 1, '%s: vzor sedi %dx' % (name, s.count(old))
    s = s.replace(old, new)
    done.append(name)


swap('timeout', """    content_type: "application/json"
    timeout: 8""", """    content_type: "application/json"
    # 20 s, nie 8: agent request dostane, ale pod zatazou odpoveda neskoro
    # a HA ju zahodi. Tretina periody tiku je bezpecna (mode: single).
    timeout: 20""")

swap('backoff', """          {{ is_state('binary_sensor.simona_pc_online', 'on') or now().minute % 5 == 0 }}""",
     """          {% set vek = as_timestamp(now())
                       - as_timestamp(states('input_datetime.simona_pc_kontakt'), 0) %}
          {{ vek < 600 or now().minute % 5 == 0 }}""")

swap('monotonnost', """          value: "{{ [ pc.content.used | int(0), 1440 ] | min }}\"""",
     """          # V ramci dna monotonne: pokles znamena, ze agent stratil stav
          # (state.json po tvrdom vypnuti), nie ze sa cas odsedel spat.
          # Vynimka su prve minuty po polnoci - agent resetuje o 00:00,
          # HA az o 00:06.
          value: >-
            {% set nove  = pc.content.used | int(0) %}
            {% set stare = states('input_number.simona_pc_pouzite') | int(0) %}
            {% if now().hour == 0 and now().minute < 10 %}
            {{ [ nove, 1440 ] | min }}
            {% else %}
            {{ [ [ nove, stare ] | max, 1440 ] | min }}
            {% endif %}""")

open(p, 'w', encoding='utf-8').write(s)
print('zmenene:', ', '.join(done) if done else 'uz bolo opravene')
