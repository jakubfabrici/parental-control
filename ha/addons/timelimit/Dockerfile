# Oficialny image TimeLimit servera + binarka Mailpitu v jednom kontajneri.
# Supervisor tento Dockerfile zostavi sam (lokalny add-on bez "image:").
#
# latest je rozbity (ESM/CommonJS konflikt v http-errors), preto pin na v1.17.0.
FROM axllent/mailpit:v1.31.4 AS mailpit

FROM ghcr.io/michaelsp/timelimit-server/timelimit:v1.17.0

# Mailpit je staticka Go binarka, staci ju prekopirovat.
COPY --from=mailpit /mailpit /usr/local/bin/mailpit

# Oprava migracii v image (zly glob + umzug v2 vs v3) - viz patches/umzug.js.
COPY patches/umzug.js /usr/src/app/build/database/migration/umzug.js

# Most do Home Assistantu (MQTT discovery) - jedina zavislost je mqtt klient,
# instaluje sa pri builde image.
COPY bridge /opt/bridge
RUN cd /opt/bridge && npm install --omit=dev --no-audit --no-fund && npm cache clean --force

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
