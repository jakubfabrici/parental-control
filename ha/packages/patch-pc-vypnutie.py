#!/usr/bin/env python3
"""PC sa po vycerpani casu vypne; potom uz len upozornenia.

Zmena zadania: po limite sa pocitac VYPNE (raz). Ked ho Simonka znova
zapne a pouziva ho viac ako 3 minuty, nezasahujeme - chodi len upozornenie
na TV a Jakubovi do Telegramu.

Pri tej prilezitosti dve opravy:

1. Evidencia zapisov do Family Link sa presuva z nasich dvoch automatizacii
   na jednu, ktora pocuva event call_service. Do FL totiz pisu aj STARSIE
   automatizacie z povodneho setupu (/pridat_30, /pridat_60, vikendovy
   rezim) - ich zapisy by nova simona_cas_fl_zmena povazovala za zmenu od
   rodica a prepisala by nimi tyzdenny rozvrh.

2. Skrtenie opakovanych upozorneni sa odkazovalo na
   automation.simona_cas_pc_po_limite, lenze alias sa sluguje na
   automation.simona_cas_pc_po_vycerpani_casu - entita v podmienke
   neexistovala, as_timestamp(None, 0) = 0 a podmienka bola VZDY splnena.
   Cas posledneho upozornenia je teraz v input_datetime.

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


# --- 1. helpery ------------------------------------------------------------
# Snimka patri do input_number, ktory konci tesne pred input_text -
# NIE pred input_datetime, medzi nimi je este blok input_text.
swap("helper-snap-vypnutie", """  simona_snap_pc:
    name: Simona snímka PC
    min: -1
    max: 1440
    step: 1
    mode: box
    unit_of_measurement: min
    icon: mdi:camera-timer

input_text:""", """  simona_snap_pc:
    name: Simona snímka PC
    min: -1
    max: 1440
    step: 1
    mode: box
    unit_of_measurement: min
    icon: mdi:camera-timer

  # Kolko minut mal agent nameranych vo chvili, ked sme PC po limite vypli.
  # -1 = dnes sme este nevypinali. Od tejto hodnoty sa rataju tie 3 minuty,
  # po ktorych zacneme upozornovat.
  simona_pc_snap_vypnutie:
    name: Simona snímka pri vypnutí PC
    min: -1
    max: 1440
    step: 1
    mode: box
    unit_of_measurement: min
    icon: mdi:power-off

input_text:""")

swap("helper-upozornenie", """input_datetime:
  simona_pc_kontakt:
    name: Simona PC posledný kontakt
    has_date: true
    has_time: true""", """input_datetime:
  simona_pc_kontakt:
    name: Simona PC posledný kontakt
    has_date: true
    has_time: true

  # Kedy naposledy islo upozornenie "sedi pri PC po limite". Drzime to v
  # helperi, nie cez last_triggered automatizacie - ten odkaz sa uz raz
  # ticho rozbil premenovanim.
  simona_pc_upozornenie:
    name: Simona PC posledné upozornenie
    has_date: true
    has_time: true""")


# --- 2. evidencia zapisov do FL na jednom mieste ---------------------------
# Povodne to robili nase dve automatizacie samy. Lenze do FL pisu aj starsie
# automatizacie z povodneho setupu - tie by sme inak povazovali za rodica.
zapis_blok = """      - action: input_text.set_value
        target:
          entity_id: input_text.simona_fl_zapisane
        data:
          value: >-
            {{ ([ ciel | string ] + (states('input_text.simona_fl_zapisane')
                 .split(',') | map('int', 0) | select | map('string') | list))[:5] | join(',') }}
"""
if s.count(zapis_blok) == 2:
    s = s.replace(zapis_blok, "")
    done.append("zrusene-inline-evidencie")

swap("evidencia-zapisov", """  # -- Prevzatie zmeny z Family Link ------------------------------------------""", """  # -- Evidencia toho, co sme do Family Link zapisali --------------------------
  # Pocuvame priamo volanie sluzby, nie jednotlive automatizacie: do FL pisu
  # aj STARSIE automatizacie z povodneho setupu (tlacidla /pridat_30,
  # /pridat_60, vikendovy rezim v automations.yaml). Keby sme evidovali len
  # vlastne zapisy, ich zmeny by simona_cas_fl_zmena povazovala za zmenu od
  # rodica a prepisala by nimi tyzdenny rozvrh.
  - id: simona_cas_fl_evidencia
    alias: "Simona čas: evidencia zápisov do Family Link"
    mode: queued
    max: 10
    triggers:
      - trigger: event
        event_type: call_service
        event_data:
          domain: familylink
          service: set_daily_limit
    actions:
      - action: input_text.set_value
        target:
          entity_id: input_text.simona_fl_zapisane
        data:
          value: >-
            {% set nova = trigger.event.data.service_data.daily_minutes | int(0) %}
            {{ ([ nova | string ] + (states('input_text.simona_fl_zapisane')
                 .split(',') | map('int', 0) | select | map('string') | list))[:5] | join(',') }}

  # -- Prevzatie zmeny z Family Link ------------------------------------------""")


# --- 3. polnocny reset nuluje aj snimku vypnutia ---------------------------
# Vzor "snap_tablet + snap_pc" je v subore dvakrat (polnocny reset a koniec
# rezimu bez limitu). Kotvime sa preto o predchadzajuci blok, ktory je len
# v polnocnom resete - snimku vypnutia nuluje len on.
swap("reset-snap-vypnutie", """            - input_number.simona_offset_pc
        data:
          value: 0
      - action: input_number.set_value
        target:
          entity_id:
            - input_number.simona_snap_tablet
            - input_number.simona_snap_pc
        data:
          value: -1""", """            - input_number.simona_offset_pc
        data:
          value: 0
      - action: input_number.set_value
        target:
          entity_id:
            - input_number.simona_snap_tablet
            - input_number.simona_snap_pc
            - input_number.simona_pc_snap_vypnutie
        data:
          value: -1""")


# --- 4. vypnutie PC po limite + prepis upozornenia -------------------------
swap("vypnutie-a-upozornenie", """  # -- PC pouzity po vycerpani casu -------------------------------------------
  # PC sa zamerne NIJAKO neblokuje - Simonka sa ma rozhodnut sama. Ked si po
  # vycerpanom case sadne k PC, len o tom dame vediet: prekrytie na TV a
  # sprava Jakubovi do Telegramu. Aby to pri dlhsom sedeni nespamovalo,
  # opakuje sa najviac raz za pol hodinu.
  - id: simona_cas_pc_po_limite
    alias: "Simona čas: PC po vyčerpaní času"
    mode: single
    max_exceeded: silent
    triggers:
      # zapla PC (agent sa ohlasil po tom, co bol dlho ticho)
      - trigger: state
        entity_id: binary_sensor.simona_pc_online
        from: "off"
        to: "on"
      # zacala pri nom realne robit
      - trigger: state
        entity_id: input_boolean.simona_pc_pouziva_sa
        from: "off"
        to: "on"
      # sedi pri nom dalej - pripomenieme sa
      - trigger: state
        entity_id: input_boolean.simona_pc_pouziva_sa
        to: "on"
        for: "00:30:00"
    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: state
        entity_id: input_boolean.simona_bez_limitu
        state: "off"
      - condition: numeric_state
        entity_id: sensor.simona_cas_zostava
        below: 1
      - condition: template
        value_template: >-
          {{ (as_timestamp(now())
              - as_timestamp(state_attr('automation.simona_cas_pc_po_limite', 'last_triggered'), 0)) > 1800 }}
    actions:
      - variables:
          text: >-
            Simonka je pri PC, hoci má na dnes vyčerpaný čas
            (tablet {{ states('sensor.simona_tablet_pouzite') | int(0) }} +
            PC {{ states('input_number.simona_pc_pouzite') | int(0) }} z
            {{ states('sensor.simona_rozpocet_celkom') | int(0) }} min).
      # Posielame vzdy. Ked je TV vypnuta, volanie zlyha a pokracuje sa
      # dalej na Telegram - preto continue_on_error.
      - action: notify.tvoverlaynotify
        continue_on_error: true
        data:
          title: "🖥 Simonka pri PC"
          message: "{{ text }}"
          data:
            appTitle: Rodičovský dohľad
            color: "#e8a33d"
            seconds: 30
      - action: telegram_bot.send_message
        continue_on_error: true
        data:
          chat_id: 5756450012
          parse_mode: html
          message: "🖥 {{ text }}\"""", """  # -- Vypnutie PC po vycerpani casu ------------------------------------------
  # Po limite sa pocitac RAZ vypne. Nie hned a nie potichu: najprv hlasove a
  # textove varovanie a minuta na ulozenie rozrobeneho.
  #
  # Vypina sa raz za den. Ked ho potom Simonka znova zapne, uz do toho
  # nesiahame - vtedy chodia len upozornenia (automatizacia nizsie). Ked
  # rodic prida cas a ten sa znova minu, vypne sa znova (snimku vynuluje
  # simona_cas_pc_obnova_vypnutia).
  - id: simona_cas_pc_vypnutie_po_limite
    alias: "Simona čas: vypnúť PC po vyčerpaní času"
    mode: single
    max_exceeded: silent
    triggers:
      # cas sa prave minul
      - trigger: numeric_state
        entity_id: sensor.simona_cas_zostava
        below: 1
      # alebo bol uz minuty a ona PC prave zapla
      - trigger: state
        entity_id: binary_sensor.simona_pc_online
        from: "off"
        to: "on"
      - trigger: state
        entity_id: input_boolean.simona_pc_pouziva_sa
        from: "off"
        to: "on"
    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: state
        entity_id: input_boolean.simona_bez_limitu
        state: "off"
      - condition: numeric_state
        entity_id: sensor.simona_cas_zostava
        below: 1
      # Ked PC nebezi, nie je co vypinat - vypne sa az ked ho zapne.
      - condition: state
        entity_id: binary_sensor.simona_pc_online
        state: "on"
      # -1 = dnes sme este nevypinali.
      - condition: numeric_state
        entity_id: input_number.simona_pc_snap_vypnutie
        below: 0
    actions:
      - action: rest_command.pc_cmd
        continue_on_error: true
        data:
          action: speak
          args: Simonka, čas na dnes sa minul. Počítač sa o minútu vypne, ulož si prácu.
      - action: rest_command.pc_cmd
        continue_on_error: true
        data:
          action: msg
          args: Čas na dnes sa minul - počítač sa o minútu vypne.
      - delay: "00:01:00"
      # Snimka az tesne pred vypnutim, nech sa tie 3 minuty po opatovnom
      # zapnuti rataju od skutocneho konca.
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_pc_snap_vypnutie
        data:
          value: "{{ states('input_number.simona_pc_pouzite') | int(0) }}"
      - action: rest_command.pc_cmd
        continue_on_error: true
        data:
          action: shutdown
          delay: 10
      - action: telegram_bot.send_message
        continue_on_error: true
        data:
          chat_id: 5756450012
          parse_mode: html
          message: >-
            🖥 Simonke sa minul čas, počítač som vypol
            (tablet {{ states('sensor.simona_tablet_pouzite') | int(0) }} +
            PC {{ states('input_number.simona_pc_pouzite') | int(0) }} z
            {{ states('sensor.simona_rozpocet_celkom') | int(0) }} min).

  # -- Novy cas rusi vypnutie -------------------------------------------------
  # Ked rodic prida cas, zacina sa odznova: az ked sa minie aj ten, PC sa
  # zase raz vypne.
  - id: simona_cas_pc_obnova_vypnutia
    alias: "Simona čas: nový čas ruší vypnutie PC"
    mode: single
    triggers:
      - trigger: numeric_state
        entity_id: sensor.simona_cas_zostava
        above: 0
    conditions:
      - condition: numeric_state
        entity_id: input_number.simona_pc_snap_vypnutie
        above: -1
    actions:
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_pc_snap_vypnutie
        data:
          value: -1

  # -- PC pouzity po tom, co sme ho vypli -------------------------------------
  # Uz do neho nesiahame. Ked ho zapne a odsedi pri nom viac ako 3 minuty,
  # chodi len upozornenie - na TV a Jakubovi do Telegramu.
  - id: simona_cas_pc_po_limite
    alias: "Simona čas: PC po vyčerpaní času"
    mode: single
    max_exceeded: silent
    triggers:
      # Agent hlasi kazdu minutu, ale hodnota sa zmeni len ked pri PC naozaj
      # pracuje - necinnost sa neraáta.
      - trigger: state
        entity_id: input_number.simona_pc_pouzite
    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: state
        entity_id: input_boolean.simona_bez_limitu
        state: "off"
      - condition: numeric_state
        entity_id: sensor.simona_cas_zostava
        below: 1
      - condition: state
        entity_id: input_boolean.simona_pc_pouziva_sa
        state: "on"
      # Az ked uz raz po limite vypnuty bol ...
      - condition: numeric_state
        entity_id: input_number.simona_pc_snap_vypnutie
        above: -1
      # ... a od vtedy pri nom odsedela viac ako 3 minuty.
      - condition: template
        value_template: >-
          {{ (states('input_number.simona_pc_pouzite') | int(0))
             - (states('input_number.simona_pc_snap_vypnutie') | int(0)) > 3 }}
      # Kym pri nom sedi, pripomenieme sa najviac raz za pol hodinu.
      # POZOR: predtym tu bol odkaz na automation.simona_cas_pc_po_limite,
      # lenze alias sa sluguje na automation.simona_cas_pc_po_vycerpani_casu.
      # Entita neexistovala, as_timestamp(None, 0) = 0 a podmienka bola vzdy
      # splnena - skrtenie teda nikdy nefungovalo. Preto vlastny helper.
      - condition: template
        value_template: >-
          {{ (as_timestamp(now())
              - as_timestamp(states('input_datetime.simona_pc_upozornenie'), 0)) > 1800 }}
    actions:
      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.simona_pc_upozornenie
        data:
          datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
      # Posielame vzdy. Ked je TV vypnuta, volanie zlyha a pokracuje sa
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
          message: "Simonka si zapla počítač napriek tomu, že už ho nemá používať!!! Choď to vyriešiť!!!\"""")


# --- 5. hlavicka -----------------------------------------------------------
swap("hlavicka-3", """# PC sa NIJAKO neblokuje - to je zamer, nie chybajuca funkcia. Simonka sa ma
# vediet zastavit sama; ked si po vycerpanom case sadne k PC, len o tom dame
# vediet (prekrytie na TV + Telegram Jakubovi).""", """# Po vycerpani casu sa PC RAZ vypne - s hlasovym varovanim a minutou na
# ulozenie rozrobeneho. Ked ho potom zapne znova, uz do neho nesiahame:
# ked pri nom odsedi viac ako 3 minuty, ide len upozornenie na TV a
# Jakubovi do Telegramu.""")


open(p, "w", encoding="utf-8").write(s)
print("OK:", ", ".join(done) if done else "uz bolo aplikovane")
