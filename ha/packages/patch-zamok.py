#!/usr/bin/env python3
"""Telegram /cas: stav a tlacidlo uplneho zamku (balik simona_zamok.yaml).

- v prehlade riadok "Uplny zamok", kym je input_boolean.simona_uplny_zamok
  zapnuty (vtedy sa neukazuje aj "Tablet je zablokovany" - je to to iste),
  s tym, ci si tablet zamok uz stiahol (atribut delivered zo senzora mosta);
- tlacidlo "Uplny zamok" / "Zrusit uplny zamok" (callback /pcz_*, obsluhuje
  automatizacia simona_zamok_telegram; zapnutie sa najprv opyta).

Idempotentne. Pouzitie: python3 patch-zamok.py simona_cas_telegram.yaml
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


swap("prehlad-zamok", """{% if is_state('switch.timelimit_simonka_zablokovane','on') %}
            {{ '\\n' }}🔒 <b>Tablet je zablokovaný</b> (TimeLimit){% endif %}
""", """{% if is_state('input_boolean.simona_uplny_zamok','on') %}
            {{ '\\n' }}🔐 <b>Úplný zámok</b> — {{ 'tablet je zamknutý' if state_attr('binary_sensor.timelimit_simonka_uplny_zamok','delivered') == true else 'tablet sa zamkne, keď sa pripojí' }}, počítač sa pri zapnutí hneď vypne{% elif is_state('switch.timelimit_simonka_zablokovane','on') %}
            {{ '\\n' }}🔒 <b>Tablet je zablokovaný</b> (TimeLimit){% endif %}
""")

swap("tlacidlo-zamok", """            - "⛔ Ukončiť čas teraz:/pct_stop"
            - "⬅ Menu:/pcm_main"
""", """            - "⛔ Ukončiť čas teraz:/pct_stop"
            - "{{ '🔓 Zrušiť úplný zámok:/pcz_odomkni' if is_state('input_boolean.simona_uplny_zamok','on') else '🔐 Úplný zámok:/pcz_zamok' }}"
            - "⬅ Menu:/pcm_main"
""")

open(p, "w", encoding="utf-8").write(s)
print(p, "hotovo:", ", ".join(done) if done else "nic (uz bolo aplikovane)")
