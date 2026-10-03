#!/usr/bin/env python3
"""Obratenie smeru: agent na PC hlasi sam, HA sa uz nepyta kazdu minutu.

Preco (dva incidenty za tri dni, cely rozbor je v docs/VYSKUM-PREZENCIA.md):

  Doterajsi model bol dopyt: HA sa kazdu minutu spytala agenta a cakala na
  odpoved. Na Core2 Duo z roku 2008, kde hra v prehliadaci vytazi obe jadra,
  agent obcas neodpovie vcas - a HA zahodi aj to, co uz agent zmeral. Cim
  slabsi stroj, tym viac zahodenych merani. Timeout sa da predlzovat donekonecna
  a stale to bude pretekanie s planovacom Windowsu.

  Po obrateni smeru ziadne preteky nie su. Agent posle, co nameral, ked to
  stihne - o sekundu alebo o polminuty neskor, na hodnote to nic nemeni.
  Zmeskany beh uz nie je strata dat, len oneskorenie.

Co tento patch pridava:

  P1  automatizacia "hlasenie z PC" na webhook. Robi presne to, co robil tick:
      zapise kontakt, znacku vstupu, spotrebu (monotonne a s hornou poistkou)
      a surovu vzorku agenta. Rozdiel je len v tom, kto beh spusti.
  P2  odpoved smerom k PC: agent v hlaseni posiela aj strop, na ktory si mysli,
      ze plati. Ked sa lisi od sensor.simona_pc_povolene, HA mu posle novy
      (rest_command limit_set). V ustalenom stave sa teda neposiela nic.
  P3  stary tick ostava ako zachranna siet, ale spusti sa az ked hlasenie
      nechodi viac nez 150 s. Kym agent hlasi, HA sa nepyta vobec.

  Webhook je local_only (len z domacej siete) a jeho id je v secrets.yaml
  na oboch stranach - v repozitari nie je a nesmie byt.

Spustenie:  python3 patch-push.py simona_cas.yaml
Je to idempotentne.
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


# --- P3: tick sa zapne az ked hlasenie nechodi ------------------------------
swap(
    "tick-ako-zachranna-siet",
    """      # Ked PC nebezi, skusame ho len raz za pat minut - inak by kazda
      # minuta vypnuteho PC pridala do logu jednu chybu spojenia.
      - condition: template
        value_template: >-
          {% set vek = as_timestamp(now())
                       - as_timestamp(states('input_datetime.simona_pc_kontakt'), 0) %}
          {{ vek < 600 or now().minute % 5 == 0 }}""",
    """      # ZACHRANNA SIET, nie hlavna cesta. Od verzie agenta 1.2.0 hlasi
      # agent sam (automatizacia simona_cas_pc_hlasenie nizsie) a tato vetva
      # sa spusti az vtedy, ked hlasenie nechodi viac nez 150 s - teda ked je
      # agent stary, zle nastaveny alebo mrtvy.
      #
      # Ked PC nebezi, skusame ho len raz za pat minut - inak by kazda
      # minuta vypnuteho PC pridala do logu jednu chybu spojenia.
      - condition: template
        value_template: >-
          {% set vek = as_timestamp(now())
                       - as_timestamp(states('input_datetime.simona_pc_kontakt'), 0) %}
          {{ vek > 150 and (vek < 600 or now().minute % 5 == 0) }}""",
)

# --- P1 + P2: hlasenie z PC ------------------------------------------------
swap(
    "automatizacia-hlasenie",
    """  # -- Vecerne upratanie ------------------------------------------------------""",
    """  # -- Hlasenie z PC (agent 1.2.0 a novsi) ------------------------------------
  # Obrateny smer: agent posiela sam, HA nic nezahadzuje. Telo hlasenia:
  #   {"used": 18, "idle_sec": 3, "age_sec": 0, "active": true,
  #    "allowed": 105, "version": "1.2.0", "needs_seed": false, "lag_max": 0}
  #
  # Vsetky zabrany su rovnake ako pri tiku - data z PC su nedoveryhodne v
  # oboch smeroch a webhook je navyse otvoreny komukolvek v LAN, kto pozna
  # jeho id. Preto: spotreba len monotonne a len do stropu, ktory sa dal
  # stihnut; znacka vstupu len z pasma platnych hodnot.
  - id: simona_cas_pc_hlasenie
    alias: "Simona čas: hlásenie z PC"
    mode: queued
    max: 5
    triggers:
      - trigger: webhook
        webhook_id: !secret simona_pc_webhook
        allowed_methods:
          - POST
        local_only: true
    conditions:
      - condition: state
        entity_id: input_boolean.simona_zdielany_cas
        state: "on"
      - condition: template
        value_template: "{{ trigger.json is defined and trigger.json.used is defined }}"
    actions:
      - variables:
          novy: >-
            {{ trigger.json.idle_sec is defined and trigger.json.age_sec is defined }}
          idle_ok: >-
            {{ (trigger.json.idle_sec | default(-1) | int(-1)) >= 0
               and (trigger.json.idle_sec | default(99999) | int(99999)) < 60
               and (trigger.json.age_sec | default(99999) | int(99999)) < 90 }}
          nove:  "{{ trigger.json.used | int(-1) }}"
          stare: "{{ states('input_number.simona_pc_pouzite') | int(0) }}"
          pred:  "{{ states('input_number.simona_pc_pouzite') | int(-1) }}"
          rast: "{{ pred >= 0 and (nove | int) > pred }}"
          sedi_teraz: "{{ idle_ok or ((not novy) and rast) }}"
          kontakt_ts: "{{ state_attr('input_datetime.simona_pc_kontakt', 'timestamp') | float(0) }}"
          odstup: >-
            {{ [ (now().timestamp() - kontakt_ts) | int, 0 ] | max if kontakt_ts > 0 else 86400 }}
          # Hlasenie chodi kazdych 30 s, takze +2 minuty rezervy staci aj na
          # jedno vynechane. Druhy strop je "kolko minut dnes vobec ubehlo".
          strop_skok: "{{ (odstup | int // 60) + 2 }}"
          strop_dnes: "{{ ((now() - today_at('00:00')).total_seconds() / 60) | int }}"
          povolene: "{{ [ (stare | int) + (strop_skok | int), strop_dnes | int ] | min }}"
          hodnoverne: >-
            {{ (nove | int) >= 0
               and ( (nove | int) <= (stare | int) or (nove | int) <= (povolene | int) ) }}
          strop_ha: "{{ states('sensor.simona_pc_povolene') | int(-1) }}"
          strop_agenta: "{{ trigger.json.allowed | default(-1) | int(-1) }}"

      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.simona_pc_kontakt
        data:
          datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"

      # Znacka vstupu PRED spotrebou - automatizacia po limite sa spusta na
      # zmenu spotreby a musi vidiet uz novu znacku.
      - if:
          - condition: template
            value_template: "{{ sedi_teraz }}"
        then:
          - action: input_datetime.set_datetime
            target:
              entity_id: input_datetime.simona_pc_vstup
            data:
              datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
      - if:
          - condition: template
            value_template: "{{ novy and not idle_ok }}"
        then:
          - action: input_datetime.set_datetime
            target:
              entity_id: input_datetime.simona_pc_vstup
            data:
              datetime: "{{ (now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S') }}"

      - action: "input_boolean.turn_{{ 'on' if trigger.json.active | default(false) else 'off' }}"
        target:
          entity_id: input_boolean.simona_pc_pouziva_sa

      - choose:
          - conditions:
              - condition: template
                value_template: "{{ hodnoverne }}"
            sequence:
              - action: input_number.set_value
                target:
                  entity_id: input_number.simona_pc_pouzite
                data:
                  value: >-
                    {% if now().hour == 0 and now().minute < 10 %}
                    {{ [ nove | int, 1440 ] | min }}
                    {% else %}
                    {{ [ [ nove | int, stare | int ] | max, 1440 ] | min }}
                    {% endif %}
              - if:
                  - condition: numeric_state
                    entity_id: counter.simona_pc_skok_zamietnuty
                    above: 0
                then:
                  - action: counter.reset
                    target:
                      entity_id: counter.simona_pc_skok_zamietnuty
        default:
          - action: counter.increment
            target:
              entity_id: counter.simona_pc_skok_zamietnuty
          - action: system_log.write
            data:
              level: warning
              logger: simona_cas
              message: >-
                PC hlasenie: zamietnuty skok pouzite {{ stare }} -> {{ nove }}
                (odstup {{ odstup }} s, povolene max {{ povolene }})

      # Odpoved smerom k PC. Posiela sa LEN ked sa strop naozaj lisi, takze v
      # ustalenom stave po sieti nechodi nic. Ked to zlyha, nic sa nedeje -
      # agent si podrzi posledny znamy strop a my mu ho posleme o 30 s znova.
      - if:
          - condition: template
            value_template: "{{ strop_ha >= 0 and strop_agenta != strop_ha }}"
        then:
          - action: rest_command.pc_cmd
            continue_on_error: true
            data:
              action: limit_set
              args: "{{ strop_ha }}"

      - action: input_number.set_value
        target:
          entity_id: input_number.simona_pc_lag_max
        data:
          value: >-
            {{ [ [ states('input_number.simona_pc_lag_max') | int(0),
                   trigger.json.lag_max | default(0) | int(0) ] | max, 3600 ] | min }}

  # -- Vecerne upratanie ------------------------------------------------------""",
)

open(p, "w", encoding="utf-8").write(s)
print("hotovo:", ", ".join(done) if done else "uz bolo zaplatane")
