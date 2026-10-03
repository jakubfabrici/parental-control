#!/usr/bin/env python3
# Dva strazcovia, ktori dnes chybali:
#  1) ked PC zmizne zo siete, zhasne sa "pouziva sa" (doteraz ostalo svietit
#     aj hodiny po vypnuti - 6. 9. od 10:02 do 13:58);
#  2) ked sa agent 10 minut neozve, pride sprava do Telegramu. Dnes 13. 9.
#     bol PC zapnuty od 14:03 a HA o nom nevedel do 14:25 - vsimol si to
#     az Jakub.
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


swap('helper-ticho', """  simona_pc_upozornenie:
    name: Simona PC posledné upozornenie
    has_date: true
    has_time: true
""", """  simona_pc_upozornenie:
    name: Simona PC posledné upozornenie
    has_date: true
    has_time: true

  # Kedy naposledy islo upozornenie "PC sa nehlasi" - vlastne skrtenie, nie
  # last_triggered (ten sa uz raz ticho rozbil premenovanim).
  simona_pc_ticho:
    name: Simona PC posledné upozornenie na ticho
    has_date: true
    has_time: true
""")

swap('strazcovia', """  # -- Upozornenia rodicom ----------------------------------------------------
  - id: simona_cas_varovania""", """  # -- PC zmizol zo siete -----------------------------------------------------
  # Bez tohto ostava priznak "pouziva sa" zapnuty aj hodiny po vypnuti PC
  # (6. 9. od 10:02 do 13:58 UTC, zhaslo to az rucne). Ziadne nove cislo:
  # je to tych istych 300 s zo senzora "PC online".
  - id: simona_cas_pc_offline_zhasni
    alias: "Simona čas: PC offline → zhasnúť používa sa"
    mode: single
    triggers:
      - trigger: state
        entity_id: binary_sensor.simona_pc_online
        to: "off"
    actions:
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.simona_pc_pouziva_sa

  # -- PC sa prestal hlasit ---------------------------------------------------
  # Prah 10 minut stavu offline = 15 minut uplneho ticha (senzor ma vlastnu
  # 300 s hysterezu). Bezne medzery medzi tikmi su 1-3 minuty, cely restart
  # po vypadku napajania trval 5 minut ticha. 13. 9. bol PC zapnuty od 14:03
  # a prvy tik dosiel az 14:25 - tato sprava by bola prisla o 14:15.
  #
  # from: "on" je zamerne: celodenne vypnuty PC sedi na "off" a ziadny
  # prechod nevyrobi, takze nechodi nic.
  - id: simona_cas_pc_ticho
    alias: "Simona čas: PC sa prestal hlásiť"
    mode: single
    max_exceeded: silent
    triggers:
      - trigger: state
        entity_id: binary_sensor.simona_pc_online
        from: "on"
        to: "off"
        for: "00:10:00"
    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      # Ked sa cas nerata, mlciaci agent nic nestoji.
      - condition: state
        entity_id: input_boolean.simona_bez_limitu
        state: "off"
      # Dnes sa aspon raz ozval - inak by sprava chodila aj po restarte HA.
      - condition: template
        value_template: >-
          {{ states('input_datetime.simona_pc_kontakt')[:10] == now().strftime('%Y-%m-%d') }}
      - condition: time
        after: "07:00:00"
        before: "21:00:00"
      # Najviac jedna sprava za hodinu.
      - condition: template
        value_template: >-
          {{ (as_timestamp(now())
              - as_timestamp(states('input_datetime.simona_pc_ticho'), 0)) > 3600 }}
    actions:
      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.simona_pc_ticho
        data:
          datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
      - variables:
          ticho: >-
            {{ ((as_timestamp(now())
                 - as_timestamp(states('input_datetime.simona_pc_kontakt'), 0)) / 60) | round(0) }}
      - action: telegram_bot.send_message
        continue_on_error: true
        data:
          chat_id: 5756450012
          parse_mode: html
          message: >-
            ⚠️ <b>Simonkin počítač sa nehlási {{ ticho }} min.</b>
            Posledný kontakt {{ states('input_datetime.simona_pc_kontakt')[11:16] }},
            napočítaných {{ states('input_number.simona_pc_pouzite') | int(0) }} min.
            Buď ho vypla, alebo zamrzol agent (úloha HA-PcAgent na PC). Prehľad: /cas

  # -- Upozornenia rodicom ----------------------------------------------------
  - id: simona_cas_varovania""")

open(p, 'w', encoding='utf-8').write(s)
print('zmenene:', ', '.join(done) if done else 'uz bolo opravene')
