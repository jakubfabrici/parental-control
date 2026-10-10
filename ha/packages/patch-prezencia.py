#!/usr/bin/env python3
"""Zvysok fazy 0: prezencia pri PC prestava byt zapamatana hodnota.

POZOR: cast fazy 0 uz NASADENA je (13. 9. 2026, pocas incidentu). Uz v
/config/packages/simona_cas.yaml su: timeout 20 s, backoff podla veku
kontaktu, monotonna spotreba, helper simona_pc_ticho a automatizacie
"PC offline -> zhasnut pouziva sa" a "PC sa prestal hlasit" (skripty
rychla-oprava-tiku.py a oprava-strazca.py). Tento patch dopina zvysok a
je naanchorovany na TENTO stav suboru.


Preco (cely rozbor je v docs/VYSKUM-PREZENCIA.md):

  input_boolean.simona_pc_pouziva_sa je odpoved posledneho USPESNEHO tiku.
  Ked tik zlyha (agent je jednovlaknovy a odpoveda az po praci, HA ma
  timeout 8 s), HA nema odkial vziat pravdu a necha staru hodnotu:
    - pri hrani ostane OFF     -> 6. 9. 2026 07:45-08:05 UTC, 19 minut
      Simona pri PC, HA o nich nevedela; zaplo to az Jakubovou rukou.
    - pri vypnutom PC ostane ON -> 6. 9. 2026 10:42-13:58 UTC, 3 h 16 min.

  Navyse je 'active' bodova vzorka (idle < 60 s prave v sekunde tiku), takze
  pri riedkom vstupe blika: 14:05-15:09 UTC = 12 epizod ON za 64 minut.

Co robi tento patch (VSETKO LEN V HOME ASSISTANTOVI, na PC sa nemeni nic):

  H1  binary_sensor.simona_pc_sedi - prezencia ako funkcia veku dvoch znaciek
      (kontakt < 150 s a vstup < 240 s). Nema ako zamrznut na ON.
  H2  tick zapisuje kontakt VZDY, vstup PRED spotrebou a spotrebu prijima len
      ked je hodnoverna. Prezencia ma fallback pre agenta 1.0.0 (rast poctu
      minut), takze senzor funguje aj pred vymenou agenta.
  H2b horna poistka na skok spotreby: za odstup medzi tikmi moze pribudnut
      najviac floor(odstup/60)+2 minut a nikdy viac, nez ubehlo od polnoci.
  H3  payload nesie used_min (seed pre agenta po strate state.json) a
      allowed uz nikdy nie je 0 pri nedostupnom strope.
  H4  timeout 8 -> 20 s (dolozene cakania vo fronte 12-16 s).
  H5  backoff podla veku kontaktu (< 600 s), nie podla odvodeneho senzora.
  H6  vypinanie po limite: hrana online odhlucnena, poistny time_pattern,
      msg -> notify (hovorilo 2x), a hlavne ACK: snimka sa zapise LEN ked
      agent vypnutie potvrdil. Neuspesny pokus sa eviduje zvlast, aby sa
      neopakoval kazdu minutu.
  H7  polnoc necha snimku bez_limitu platnu, ked rezim pokracuje cez polnoc.
  H8  vetva raw < snap pri ukonceni rezimu bez limitu.
  H9  nove helpery: simona_pc_vstup, simona_pc_ticho, simona_pc_vypnutie_pokus,
      simona_pc_latencia, simona_pc_lag_max, counter simona_pc_skok_zamietnuty.
  H10 automatizacie: "PC sa prestal hlasit" (Telegram po 10 min offline),
      "PC offline -> zhasnut pouziva sa", "PC hlasi nedoveryhodnu spotrebu".

  ZAMERNE TU NIE JE faza 0c: simona_cas_pc_po_limite ostava na povodnej
  podmienke input_boolean.simona_pc_pouziva_sa = on. Prepnut ju na vek
  input_datetime.simona_pc_vstup sa smie az POTOM, co agent 1.1.0 zacne
  posielat idle_sec/age_sec a co to potvrdi trasa tiku - inak by 3-minutove
  upozornenie po limite prestalo chodit uplne a bez chyby v logu.

Spustenie:  python3 patch-prezencia.py simona_cas.yaml
Je to idempotentne - druhe spustenie nic nezmeni.
"""
import sys

p = sys.argv[1]
s = open(p, encoding="utf-8").read()
done = []


def swap(name, old, new):
    """Nahradi presne jeden vyskyt; ked uz je nova verzia vnutri, preskoci."""
    global s
    if new in s:
        return
    assert s.count(old) == 1, f"{name}: vzor sedi {s.count(old)}x"
    s = s.replace(old, new)
    done.append(name)


# --- H9: nove input_number helpery -----------------------------------------
# (Kotva bez nasledujuceho "input_text:" - ten blok odstranila zaplata zo 4. 10. 2026.)
swap(
    "helpery-input-number",
    """    unit_of_measurement: min
    icon: mdi:power-off""",
    """    unit_of_measurement: min
    icon: mdi:power-off

  # -- Diagnostika tikov -----------------------------------------------------
  # Cas od spustenia triggera po navrat rest_command.pc_tick, v sekundach.
  # Zapisuje sa len nad 1 s: v necinnosti je median 0,02 s, pri hrani 0,51 s
  # (p95 3,7 s), takze 1 s presne oddeluje normal od anomalie. max 60 je 9x
  # nad pozorovanym maximom; sablona hodnotu orezava, takze presne 60 znamena
  # "mimo rozsahu". Orez je povinny - set_value mimo min/max zhodi beh.
  simona_pc_latencia:
    name: Simona PC latencia tiku
    min: 0
    max: 60
    step: 0.01
    mode: box
    unit_of_measurement: s
    icon: mdi:timer-outline

  # Najvacsie zmeskanie tiku agenta za dnesok (s). Hlasi ho agent 1.1.0 v poli
  # lag_max, HA berie maximum z oboch - tik s velkym meskanim casto padne na
  # timeout a po restarte agenta jeho vlastne maximum zacina od nuly.
  simona_pc_lag_max:
    name: Simona PC max meškanie tiku
    min: 0
    max: 3600
    step: 1
    mode: box
    unit_of_measurement: s
    icon: mdi:timer-alert-outline""",
)

# --- H9: nove input_datetime helpery (do EXISTUJUCEHO bloku) ---------------
swap(
    "helpery-input-datetime",
    """  simona_pc_ticho:
    name: Simona PC posledné upozornenie na ticho
    has_date: true
    has_time: true
""",
    """  simona_pc_ticho:
    name: Simona PC posledné upozornenie na ticho
    has_date: true
    has_time: true

  # Kedy sa naposledy dotkla mysi alebo klavesnice. Agent 1.1.0 posle idle_sec
  # a age_sec a HA z nich vyrata cas vstupu; pri starsom agentovi sa znacka
  # posuva vtedy, ked pribudne napocitana minuta (jediny dokaz pritomnosti,
  # ktory stary agent dava). Toto je jediny zdroj prezencie.
  simona_pc_vstup:
    name: Simona PC posledný vstup
    has_date: true
    has_time: true

  # Kedy sme na PC POSLALI prikaz na vypnutie - bez ohladu na to, ci ho PC
  # potvrdil. Skrti opakovane pokusy. 1970-01-01 znamena "dnes sme neskusali".
  # Vedome oddelene od simona_pc_snap_vypnutie: ta odteraz znamena vylucne
  # "PC naozaj zhaslo a od tychto minut ratame tie 3 minuty".
  simona_pc_vypnutie_pokus:
    name: Simona PC posledný pokus o vypnutie
    has_date: true
    has_time: true
""",
)

# --- H9: counter na zamietnute skoky ---------------------------------------
swap(
    "counter",
    """input_datetime:
  simona_pc_kontakt:""",
    """# Kolko po sebe iducich tikov hlasilo spotrebu, ktora sa nedala stihnut.
# Prvy hodnoverny tik ho vynuluje; po treťom ide sprava do Telegramu.
counter:
  simona_pc_skok_zamietnuty:
    name: Simona PC zamietnuté skoky
    initial: 0
    step: 1
    icon: mdi:shield-alert-outline

input_datetime:
  simona_pc_kontakt:""",
)

# --- H1: odvodena prezencia -------------------------------------------------
swap(
    "senzor-sedi",
    """  - binary_sensor:
      - name: Simona PC online
        unique_id: simona_pc_online
        device_class: connectivity
        icon: mdi:desktop-classic
        state: >-
          {{ (as_timestamp(now()) - as_timestamp(states('input_datetime.simona_pc_kontakt'), 0)) < 300 }}
""",
    """  - binary_sensor:
      - name: Simona PC online
        unique_id: simona_pc_online
        device_class: connectivity
        icon: mdi:desktop-classic
        state: >-
          {{ (as_timestamp(now()) - as_timestamp(states('input_datetime.simona_pc_kontakt'), 0)) < 300 }}

      # Sedi prave pri pocitaci? NIE je to ulozeny priznak od agenta, ale
      # funkcia veku dvoch znaciek - preto nema ako zamrznut na ON, ked PC
      # zmizne. Ked tiky prestanu chodit, senzor sam zhasne.
      #
      # 150 s na kontakt = tolerancia prave jedneho strateneho tiku (pri
      #   perióde 60 s je obnova po jednom vypadku o T+120 s, po dvoch az o
      #   T+180 s). Zamerne menej nez 300 s okno senzora "PC online", nech
      #   nikdy nevznikne stav "sedi pri PC, ktory sa nehlasi".
      # 240 s od vstupu = najdlhsia medzera medzi napocitanymi minutami vnutri
      #   suvisleho hrania bola 179,9 s (6. 9. 2026, dva pripady tesne pod
      #   180 s). Prah 180 by tam padal nahodne podla latencie tiku, 240 ich
      #   pokryva s rezervou. Nie je to zmena pravidla "viac ako 3 minuty" -
      #   to vynucuje samostatna podmienka pouzite - snap_vypnutie > 3.
      # Horna hranica oneskorenia po odchode: 240 s + 60 s granularita
      # prepoctu sablony = najviac 5 minut.
      - name: Simona PC sedí
        unique_id: simona_pc_sedi
        device_class: occupancy
        icon: mdi:account-clock
        state: >-
          {% set t = as_timestamp(now()) %}
          {% set k = as_timestamp(states('input_datetime.simona_pc_kontakt'), 0) %}
          {% set v = as_timestamp(states('input_datetime.simona_pc_vstup'), 0) %}
          {{ (t - k) < 150 and (t - v) < 240 }}
        attributes:
          vek_kontaktu_s: >-
            {{ (as_timestamp(now())
                - as_timestamp(states('input_datetime.simona_pc_kontakt'), 0)) | round(0) }}
          od_vstupu_s: >-
            {{ (as_timestamp(now())
                - as_timestamp(states('input_datetime.simona_pc_vstup'), 0)) | round(0) }}
""",
)

# --- H3 + H4: timeout a payload --------------------------------------------
swap(
    "rest-command",
    """  pc_tick:
    url: "http://192.168.1.104:8799/cmd"
    method: POST
    content_type: "application/json"
    # 20 s, nie 8: agent request dostane, ale pod zatazou odpoveda neskoro
    # a HA ju zahodi. Tretina periody tiku je bezpecna (mode: single).
    timeout: 20
    payload: >-
      {"token":"{{ pc_token }}","action":"tick","args":"{{ allowed }}"}""",
    """  pc_tick:
    url: "http://192.168.1.104:8799/cmd"
    method: POST
    content_type: "application/json"
    # 20 s, nie 8. Timeout nie je pricina vypadkov, len prah: v agent.log su
    # dolozene cakania requestu vo fronte 12-14 s. Horna hranica je perioda
    # tiku (60 s, mode: single), takze tretina periody je bezpecna.
    # Precedens: pc_cmd ma timeout 25 s.
    timeout: 20
    # used_min = surova hodnota input_number.simona_pc_pouzite. Agent si ju
    # vezme LEN vtedy, ked sam o svojej spotrebe nic nevie (stratil
    # state.json pri vypadku napajania - stalo sa 28. 8. a 6. 9. 2026).
    # -1 znamena "HA hodnotu nema".
    payload: >-
      {"token":"{{ pc_token }}","action":"tick","args":"{{ allowed }}","used_min":{{ used_min | default(-1) | int(-1) }}}""",
)

# --- H5: backoff podla veku kontaktu ---------------------------------------
swap(
    "tick-akcie",
    """    actions:
      - action: rest_command.pc_tick
        continue_on_error: true
        data:
          pc_token: !secret pc_agent_token
          allowed: "{{ states('sensor.simona_pc_povolene') | int(0) }}"
        response_variable: pc
      # Ked je PC vypnute, volanie ticho zlyha a 'pc' vobec nevznikne -
      # podmienka nas tu zastavi a posledna znama spotreba ostava platit.
      - condition: template
        value_template: >-
          {{ pc is defined and pc.content is defined and pc.content.used is defined }}
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_pc_pouzite
        data:
          # V ramci dna monotonne: pokles znamena, ze agent stratil stav
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
            {% endif %}
      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.simona_pc_kontakt
        data:
          datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
      - action: "input_boolean.turn_{{ 'on' if pc.content.active | default(false) else 'off' }}"
        target:
          entity_id: input_boolean.simona_pc_pouziva_sa""",
    """    actions:
      - action: rest_command.pc_tick
        continue_on_error: true
        data:
          pc_token: !secret pc_agent_token
          # -1, nie 0: "0" by agent prijal ako platny strop a povedal
          # dietatu, ze cas sa minul. "-1" nevyhovie jeho regexu, takze si
          # podrzi posledny znamy strop.
          allowed: "{{ states('sensor.simona_pc_povolene') | int(-1) }}"
          used_min: "{{ states('input_number.simona_pc_pouzite') | int(-1) }}"
        response_variable: pc
      # Ked je PC vypnute, volanie ticho zlyha a 'pc' vobec nevznikne -
      # podmienka nas tu zastavi a posledna znama spotreba ostava platit.
      - condition: template
        value_template: >-
          {{ pc is defined and pc.content is defined and pc.content.used is defined }}

      # ---- co sa da z odpovede vycitat ---------------------------------------
      # POZOR na tvar zapisu: pc.content.idle_sec | int(0) nad odpovedou BEZ
      # toho pola vyhodi UndefinedError a zhodi cely beh (a to je presne
      # odpoved dnesneho agenta 1.0.0). Bezpecny tvar je 'is defined' alebo
      # '| default(...) | int(...)' - v tomto poradi.
      - variables:
          # Agent 1.1.0 posiela idle_sec (ako dlho je ticho) a age_sec (ako
          # stara je vzorka). Agent 1.0.0 neposiela ani jedno.
          novy: >-
            {{ pc.content.idle_sec is defined and pc.content.age_sec is defined }}
          idle_ok: >-
            {{ (pc.content.idle_sec | default(-1) | int(-1)) >= 0
               and (pc.content.idle_sec | default(99999) | int(99999)) < 60
               and (pc.content.age_sec | default(99999) | int(99999)) < 90 }}
          nove:  "{{ pc.content.used | int(-1) }}"
          stare: "{{ states('input_number.simona_pc_pouzite') | int(0) }}"
          pred:  "{{ states('input_number.simona_pc_pouzite') | int(-1) }}"
          # Pri starom agentovi je jediny dokaz pritomnosti RAST napocitanych
          # minut - tie rastu len z realneho vstupu (myš/klavesnica).
          rast: "{{ pred >= 0 and (nove | int) > pred }}"
          sedi_teraz: "{{ idle_ok or ((not novy) and rast) }}"
          # Odstup od POSLEDNEHO USPESNEHO tiku. kontakt prepisujeme az nizsie,
          # takze tu este drzi cas predchadzajuceho tiku. Citame atribut
          # 'timestamp', nie last_changed - ten sa po restarte HA prepise na
          # cas restartu a poistka by bola nezmyselne tesna.
          kontakt_ts: "{{ state_attr('input_datetime.simona_pc_kontakt', 'timestamp') | float(0) }}"
          odstup: >-
            {{ [ (now().timestamp() - kontakt_ts) | int, 0 ] | max if kontakt_ts > 0 else 86400 }}
          # Kolko minut MOZE za ten odstup pribudnut: agent pripocitava najviac
          # tolko sekund, kolko realne ubehlo, takze used nerastie rychlejsie
          # nez cas. +1 je zaokruhlenie nadol na oboch koncoch, +1 rezerva na
          # latenciu tiku a rozdiel hodin PC voci HA.
          strop_skok: "{{ (odstup | int // 60) + 2 }}"
          # Nezavisly strop: viac minut, nez ich od polnoci ubehlo, sa dnes
          # minut nedalo. Kryje zastaraly kontakt aj okno 00:00-00:06.
          strop_dnes: "{{ ((now() - today_at('00:00')).total_seconds() / 60) | int }}"
          povolene: "{{ [ (stare | int) + (strop_skok | int), strop_dnes | int ] | min }}"
          # Pokles a hodnota bez zmeny prechadzaju vzdy - poistka je len na rast.
          hodnoverne: >-
            {{ (nove | int) >= 0
               and ( (nove | int) <= (stare | int) or (nove | int) <= (povolene | int) ) }}
          # Latencia tiku. trigger.now pri time_pattern existuje, ale pri
          # rucnom spusteni automatizacie trigger.now chyba - bez fallbacku by
          # UndefinedError zabil beh.
          lat: >-
            {{ [ [ 0, ( as_timestamp(now())
                        - as_timestamp(trigger.now
                            if (trigger is defined and trigger.now is defined)
                            else now()) ) | round(2) ] | max, 60 ] | min }}

      # (1) KONTAKT VZDY, aj ked hodnotu spotreby zamietneme: tik prisiel, PC
      #     zije. Keby sme ho pri zamietnuti nezapisali, odstup by rastol, s nim
      #     aj strop_skok - a zamietnuta hodnota by o par minut presla.
      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.simona_pc_kontakt
        data:
          datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"

      # (2) VSTUP pred spotrebou: automatizacia po limite sa spusta prave na
      #     zmenu spotreby, takze opacne poradie by boli preteky o to, ktoru
      #     hodnotu uvidi.
      - if:
          - condition: template
            value_template: "{{ sedi_teraz }}"
        then:
          - action: input_datetime.set_datetime
            target:
              entity_id: input_datetime.simona_pc_vstup
            data:
              datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
      # Zneplatnenie ("nikto tu nie je") smie zapisat LEN novy agent. Stary
      # mlci a znacka sa necha dobehnut sama - senzor zhasne po uplynuti okna.
      - if:
          - condition: template
            value_template: "{{ novy and not idle_ok }}"
        then:
          - action: input_datetime.set_datetime
            target:
              entity_id: input_datetime.simona_pc_vstup
            data:
              datetime: "{{ (now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S') }}"

      # (3) Surova vzorka agenta. Uz nic neriadi, ostava na diagnostiku
      #     "co presne hlasi agent" - prezenciu odvodzuje senzor vyssie.
      - action: "input_boolean.turn_{{ 'on' if pc.content.active | default(false) else 'off' }}"
        target:
          entity_id: input_boolean.simona_pc_pouziva_sa

      # (4) Spotreba: dole monotonna (pokles = strata stavu na PC, nie
      #     odsedeny cas spat), hore obmedzena tym, kolko sa vobec dalo stihnut.
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ hodnoverne }}"
            sequence:
              - action: input_number.set_value
                target:
                  entity_id: input_number.simona_pc_pouzite
                data:
                  # Vynimka z monotonnosti su prve minuty po polnoci: agent
                  # resetuje den o 00:00, HA az o 00:06.
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
          # Hodnotu NEPREBERAME. Ziadny zapis = ziadna zmena stavu, teda ani
          # zbytocne spustenie sync tabletu a automatizacie po limite.
          # Zamerne tu nie je "po N zamietnutiach to aj tak prevezmi" - to by
          # bola ta ista zapadka, len oneskorena. Zamrznuta hodnota znamena,
          # ze HA podpocitava, teda dieta dostane casu viac; to je bezpecny
          # smer zlyhania. Rozviazat to ma clovek.
          - action: counter.increment
            target:
              entity_id: counter.simona_pc_skok_zamietnuty
          - action: system_log.write
            data:
              level: warning
              logger: simona_cas
              message: >-
                PC tick: zamietnuty skok pouzite {{ stare }} -> {{ nove }}
                (odstup {{ odstup }} s, povolene max {{ povolene }})

      # (5) Diagnostika na koniec - pripadna chyba tu uz nezhodi nic podstatne.
      #     if/then, nie hola condition: nesplnena podmienka by ukoncila beh.
      - if:
          - condition: template
            value_template: "{{ lat | float(0) > 1 }}"
        then:
          - action: input_number.set_value
            target:
              entity_id: input_number.simona_pc_latencia
            data:
              value: "{{ lat }}"
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_pc_lag_max
        data:
          value: >-
            {{ [ [ states('input_number.simona_pc_lag_max') | int(0),
                   pc.content.lag_max | default(0) | int(0) ] | max, 3600 ] | min }}""",
)

# --- H7 + H9: polnocny reset -----------------------------------------------
swap(
    "polnoc-snimky",
    """      - action: input_number.set_value
        target:
          entity_id:
            - input_number.simona_snap_tablet
            - input_number.simona_snap_pc
            - input_number.simona_pc_snap_vypnutie
        data:
          value: -1""",
    """      - action: input_number.set_value
        target:
          entity_id:
            - input_number.simona_snap_tablet
            - input_number.simona_pc_snap_vypnutie
        data:
          value: -1
      # Snimka PC zvlast: ked rezim "bez limitu" pokracuje cez polnoc, musi
      # ostat platna (>= 0). Inak by sablona pc_zapocitane prepadla na
      # raw - off a ranne minuty by sa dodatocne zapocitali. Nula preto, lebo
      # pc_pouzite sme v tej istej automatizacii prave vynulovali.
      - action: input_number.set_value
        target:
          entity_id: input_number.simona_snap_pc
        data:
          value: >-
            {{ 0 if is_state('input_boolean.simona_bez_limitu', 'on') else -1 }}
      # Novy den, novy pokus o vypnutie po limite.
      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.simona_pc_vypnutie_pokus
        data:
          datetime: "1970-01-01 00:00:00"
      - action: counter.reset
        target:
          entity_id: counter.simona_pc_skok_zamietnuty""",
)

swap(
    "polnoc-diagnostika",
    """      - action: input_number.set_value
        target:
          entity_id:
            - input_number.simona_pc_pouzite
            - input_number.simona_offset_tablet
            - input_number.simona_offset_pc
        data:
          value: 0""",
    """      - action: input_number.set_value
        target:
          entity_id:
            - input_number.simona_pc_pouzite
            - input_number.simona_offset_tablet
            - input_number.simona_offset_pc
            - input_number.simona_pc_latencia
            - input_number.simona_pc_lag_max
        data:
          value: 0""",
)

# --- H8: ochrana pri ukonceni rezimu bez limitu ----------------------------
swap(
    "bez-limitu-offset-pc",
    """      - action: input_number.set_value
        target:
          entity_id: input_number.simona_offset_pc
        data:
          value: >-
            {% set raw = states('input_number.simona_pc_pouzite') | int(0) %}
            {% set snap = states('input_number.simona_snap_pc') | int(0) %}
            {{ [ (states('input_number.simona_offset_pc') | int(0)) + [ raw - snap, 0 ] | max, 1440 ] | min }}""",
    """      - action: input_number.set_value
        target:
          entity_id: input_number.simona_offset_pc
        data:
          value: >-
            {% set raw  = states('input_number.simona_pc_pouzite') | int(0) %}
            {% set snap = states('input_number.simona_snap_pc') | int(0) %}
            {% set off  = states('input_number.simona_offset_pc') | int(0) %}
            {% if raw < snap %}
            {{ [ off - (snap - raw), 0 ] | max }}
            {% else %}
            {{ [ off + (raw - snap), 1440 ] | min }}
            {% endif %}""",
)

# --- H6: vypnutie po limite -------------------------------------------------
swap(
    "vypnutie-triggery",
    """      # alebo bol uz minuty a ona PC prave zapla
      - trigger: state
        entity_id: binary_sensor.simona_pc_online
        from: "off"
        to: "on"
      - trigger: state
        entity_id: input_boolean.simona_pc_pouziva_sa
        from: "off"
        to: "on\"""",
    """      # alebo bol uz minuty a ona PC prave zapla.
      # for: 5 s zabije 70 ms blik senzora na hranici minuty (sablona sa
      # prepocitava o ~0,48 s po celej minute, teda tesne pred zapisom tiku).
      - trigger: state
        entity_id: binary_sensor.simona_pc_online
        from: "off"
        to: "on"
        for: "00:00:05"
      - trigger: state
        entity_id: input_boolean.simona_pc_pouziva_sa
        from: "off"
        to: "on"
      # Poistka proti zmeskanej hrane: ked su online aj prezencia stabilne,
      # ziadna hrana nepride a automatizacia by sa nespustila vobec.
      - trigger: time_pattern
        minutes: "/5\"""",
)

swap(
    "vypnutie-throttle",
    """      # -1 = dnes sme este nevypinali.
      - condition: numeric_state
        entity_id: input_number.simona_pc_snap_vypnutie
        below: 0""",
    """      # -1 = PC dnes po limite este naozaj nezhaslo. Neuspesny pokus tuto
      # snimku NEnastavuje - ta znamena vylucne "PC potvrdilo vypnutie".
      - condition: numeric_state
        entity_id: input_number.simona_pc_snap_vypnutie
        below: 0
      # Ked pokus zlyhal, skusame znova - ale nie castejsie ako raz za
      # 10 minut. Bez toho by nas rozkmital kazdy blik prezencie.
      - condition: template
        value_template: >-
          {{ (as_timestamp(now())
              - as_timestamp(states('input_datetime.simona_pc_vypnutie_pokus'), 0)) > 600 }}""",
)

swap(
    "vypnutie-msg",
    """      - action: rest_command.pc_cmd
        continue_on_error: true
        data:
          action: msg
          args: Čas na dnes sa minul - počítač sa o minútu vypne.""",
    """      # notify, nie msg: agent pri 'msg' spusti notify.ps1 AJ speak.ps1,
      # takze veta by zaznela dvakrat (raz z akcie speak vyssie).
      - action: rest_command.pc_cmd
        continue_on_error: true
        data:
          action: notify
          args: Čas na dnes sa minul - počítač sa o minútu vypne.""",
)

swap(
    "vypnutie-zaver",
    """      # Snimka az tesne pred vypnutim, nech sa tie 3 minuty po opatovnom
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
            {{ states('sensor.simona_rozpocet_celkom') | int(0) }} min).""",
    """      # Hodnotu na snimku si odlozime TERAZ - po vypnuti uz tiky nechodia
      # a spotrebu by nam medzitym mohol prepisat oneskoreny tik.
      - variables:
          pouzite_pred: "{{ states('input_number.simona_pc_pouzite') | int(0) }}"
      # Pokus evidujeme VZDY, aj ked sa nepodari - to je ten throttle vyssie.
      - action: input_datetime.set_datetime
        target:
          entity_id: input_datetime.simona_pc_vypnutie_pokus
        data:
          datetime: "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"
      - action: rest_command.pc_cmd
        continue_on_error: true
        response_variable: vypnutie
        data:
          action: shutdown
          delay: 10
      - variables:
          # Agent na 'shutdown' odpoveda 200 + {"ok":true,...}. Ked PC nebezi
          # alebo odpoved nepride, 'vypnutie' vobec nevznikne - rovnaky vzor
          # ako pri tiku. Senzor "PC online" tu nestaci: je to len test veku
          # kontaktu, takze este ~5 minut po vypnuti tvrdi "on" (namerane
          # oneskorenie 4 min 50 s az 5 min 29 s).
          odislo: >-
            {{ vypnutie is defined
               and (vypnutie.status | default(0)) == 200
               and (vypnutie.content is mapping)
               and (vypnutie.content.ok | default(false)) }}
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ odislo }}"
            sequence:
              # Snimka LEN teraz - PC vypnutie potvrdilo. Od tejto hodnoty sa
              # rataju tie 3 minuty, po ktorych zacneme upozornovat.
              - action: input_number.set_value
                target:
                  entity_id: input_number.simona_pc_snap_vypnutie
                data:
                  value: "{{ pouzite_pred }}"
              - action: telegram_bot.send_message
                continue_on_error: true
                data:
                  chat_id: 5756450012
                  parse_mode: html
                  message: >-
                    🖥 Simonke sa minul čas, počítač som vypol
                    (tablet {{ states('sensor.simona_tablet_pouzite') | int(0) }} +
                    PC {{ pouzite_pred }} z
                    {{ states('sensor.simona_rozpocet_celkom') | int(0) }} min).
        default:
          # snap_vypnutie zostava -1: PC nezhaslo, takze nemame od coho ratat
          # tie 3 minuty a upozornenia "zapla si PC" sa NESMU spustit.
          - action: telegram_bot.send_message
            continue_on_error: true
            data:
              chat_id: 5756450012
              parse_mode: html
              message: >-
                ⚠️ Simonke sa minul čas, ale <b>počítač sa vypnúť nepodarilo</b>
                (neodpovedal). Skúsim znova o 10 minút.""",
)

# --- H10: nove automatizacie ------------------------------------------------
swap(
    "automatizacia-skok-alarm",
    """  # -- Upozornenia rodicom ----------------------------------------------------
  - id: simona_cas_varovania""",
    """  # -- PC hlasi nedoveryhodnu spotrebu ----------------------------------------
  # Bez tejto spravy by sa spotreba mohla ticho zastavit na poslednej
  # doveryhodnej hodnote a nikto by o tom nevedel.
  - id: simona_cas_pc_skok_alarm
    alias: "Simona čas: PC hlási nedôveryhodnú spotrebu"
    mode: single
    triggers:
      - trigger: numeric_state
        entity_id: counter.simona_pc_skok_zamietnuty
        above: 2
    actions:
      - action: telegram_bot.send_message
        continue_on_error: true
        data:
          chat_id: 5756450012
          parse_mode: html
          message: >-
            ⚠️ PC agent hlási spotrebu, ktorá sa nedá stihnúť
            ({{ states('counter.simona_pc_skok_zamietnuty') }}× po sebe).
            HA drží poslednú dôveryhodnú hodnotu
            {{ states('input_number.simona_pc_pouzite') | int(0) }} min.
            Skontroluj state.json na PC.

  # -- Upozornenia rodicom ----------------------------------------------------
  - id: simona_cas_varovania""",
)

# --- poznamka k faze 0c v automatizacii po limite --------------------------
swap(
    "po-limite-poznamka",
    """      - condition: state
        entity_id: input_boolean.simona_pc_pouziva_sa
        state: "on"
      # Az ked uz raz po limite vypnuty bol ...""",
    """      # FAZA 0c (az po nasadeni agenta 1.1.0): tuto podmienku nahradi vek
      # znacky vstupu -
      #   {{ (as_timestamp(now())
      #       - as_timestamp(states('input_datetime.simona_pc_vstup'), 0)) < 240 }}
      # Skor to prepnut NEMOZNO: kym agent neposiela idle_sec, znacka sa hybe
      # len pri raste spotreby a po vypnuti PC uz nikdy - podmienka by bola
      # trvale nesplnena a upozornenie by prestalo chodit uplne, bez chyby v
      # logu. Prepina sa az ked trasa tiku ukaze, ze pole idle_sec chodi.
      - condition: state
        entity_id: input_boolean.simona_pc_pouziva_sa
        state: "on"
      # Az ked uz raz po limite vypnuty bol ...""",
)

open(p, "w", encoding="utf-8").write(s)
print("hotovo:", ", ".join(done) if done else "uz bolo zaplatane")
