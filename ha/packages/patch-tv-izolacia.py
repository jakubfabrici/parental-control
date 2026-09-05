#!/usr/bin/env python3
"""Chyba TV notifikacie nesmie zhodit zvysok automatizacie.

Zistene z trace: pri vypnutej TV skonci notify.tvoverlaynotify chybou
"All connection attempts failed" a beh automatizacie sa ZASTAVI - hoci ma
akcia continue_on_error: true. Ten totiz zachytava len HomeAssistantError;
notify tu prepusti surovu aiohttp chybu. Sprava do Telegramu, ktora bola
az za TV, tak nikdy neodisla. (rest_command sa spravuje spravne, overene
na tracoch simona_cas_pc_tick - tam beh pokracuje.)

Preto:
  - TV notifikacia ide cez samostatny skript, ktory sa spusta cez
    script.turn_on - to je "posli a zabudni", chyba zostane v nom,
  - a Telegram sa posiela ako PRVY, nech je dolezity kanal vybaveny
    skor, nez sa cokolvek moze pokazit.

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


# --- 1. skript, v ktorom chyba TV zostane zatvorena ------------------------
swap("skript-tv", """script:
  simona_cas_pridaj:""", """script:
  # Prekrytie na TV. Volat VZDY cez script.turn_on, nie priamo - vtedy bezi
  # ako samostatny beh a ked je TV vypnuta, chyba nezhodi volajuceho.
  # continue_on_error tu nestaci: notify prepusti surovu aiohttp chybu,
  # ktoru HA nezachytava.
  simona_tv_oznam:
    alias: "Simona: prekrytie na TV"
    icon: mdi:television
    mode: queued
    max: 5
    fields:
      sprava:
        name: Správa
        required: true
      titulok:
        name: Titulok
        required: false
    sequence:
      - action: notify.tvoverlaynotify
        continue_on_error: true
        data:
          title: "{{ titulok | default('🖥 Počítač', true) }}"
          message: "{{ sprava }}"
          data:
            appTitle: Rodičovský dohľad
            color: "#e8a33d"
            seconds: 30

  simona_cas_pridaj:""")


# --- 2. upozornenie: Telegram prvy, TV cez skript --------------------------
swap("po-limite-poradie", """      # Posielame vzdy. Ked je TV vypnuta, volanie zlyha a pokracuje sa
      # dalej na Telegram - preto continue_on_error.
      - action: notify.tvoverlaynotify
        continue_on_error: true
        data:
          title: "🖥 Počítač"
          message: "Simonka si zapla počítač napriek tomu, že už ho nemá používať!!! Choď to vyriešiť!!!"
          data:
            appTitle: Rodičovský dohľad
            color: "#e8a33d"
            seconds: 30
      - action: telegram_bot.send_message
        continue_on_error: true
        data:
          chat_id: 5756450012
          message: "Simonka si zapla počítač napriek tomu, že už ho nemá používať!!! Choď to vyriešiť!!!\"""", """      # Telegram ide PRVY - je to kanal, ktory musi dojst. Az potom TV,
      # a to cez script.turn_on, aby jej pripadna chyba zostala v skripte.
      - action: telegram_bot.send_message
        continue_on_error: true
        data:
          chat_id: 5756450012
          message: "Simonka si zapla počítač napriek tomu, že už ho nemá používať!!! Choď to vyriešiť!!!"
      - action: script.turn_on
        target:
          entity_id: script.simona_tv_oznam
        data:
          variables:
            sprava: "Simonka si zapla počítač napriek tomu, že už ho nemá používať!!! Choď to vyriešiť!!!\"""")


open(p, "w", encoding="utf-8").write(s)
print("OK:", ", ".join(done) if done else "uz bolo aplikovane")
