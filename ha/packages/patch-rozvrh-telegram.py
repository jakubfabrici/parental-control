#!/usr/bin/env python3
"""Prehlad v Telegrame ukazuje aj tyzdenny rozvrh.

Prave tu si Jakub vsimol, ze rozpocet nesedi s Family Linkom (tvrdilo to
61 min namiesto 180). Odteraz je v prehlade vidiet, co dava rozvrh a ci
bol dnesok rucne upraveny - rozdiel je tak vidno hned.

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


swap("premenna-rozvrh", """            {% set pc_on = is_state('binary_sensor.simona_pc_online', 'on') %}""", """            {% set pc_on = is_state('binary_sensor.simona_pc_online', 'on') %}
            {% set rozvrh = states('sensor.simona_rozvrh_dnes') | int(0) %}
            {% set den = state_attr('sensor.simona_rozvrh_dnes', 'den') %}""")

# "rozvrh {{ rozpocet }}" bolo zavadzajuce - rozpocet uz nie je rozvrh,
# je to dnesna hodnota, ktoru mohol rodic rucne zmenit.
swap("zaklad-namiesto-rozvrhu", """{% if bonus > 0 %} (rozvrh {{ rozpocet }} + bonus {{ bonus }}){% endif %}""", """{% if bonus > 0 %} (základ {{ rozpocet }} + bonus {{ bonus }}){% endif %}""")

swap("riadok-rozvrhu", """            {{ '\\n' }}<i>Strop tabletu {{ states('sensor.simona_tablet_cielovy_limit') | int(0) }} min · PC povolené {{ states('sensor.simona_pc_povolene') | int(0) }} min</i>""", """            {{ '\\n' }}<i>Rozvrh na dnes ({{ den }}): {{ rozvrh }} min{% if rozpocet != rozvrh %} · dnes ručne upravené na {{ rozpocet }} min{% endif %}</i>
            {{ '\\n' }}<i>Strop tabletu {{ states('sensor.simona_tablet_cielovy_limit') | int(0) }} min · PC povolené {{ states('sensor.simona_pc_povolene') | int(0) }} min</i>""")

open(p, "w", encoding="utf-8").write(s)
print("OK:", ", ".join(done) if done else "uz bolo aplikovane")
