/*
 * Spusta sa pri builde image (Dockerfile): zapoji patches/ha-sync.js do
 * build/websocket/index.js - nacitanie modulu so serverom (spusti port pre
 * HA) a volanie po ohlaseni pripojeneho zariadenia. Ked kotvy v novej
 * verzii servera nesedia, build spadne - nech sa doplnok nestrati potichu.
 */
'use strict';
const fs = require('fs');
const file = process.argv[2] || '/usr/src/app/build/websocket/index.js';
const parts = [
    {
        anchor: 'const rooms_1 = require("./rooms");\n',
        hook: '// HA: synchronizacia detskych zariadeni (patches/ha-sync.js)\nconst haSync = require("./ha-sync");\n'
    },
    {
        anchor: '                    connectedDevicesManager.connectedDevicesManager.reportDeviceConnected({ key });\n',
        hook: '                    haSync.startPeriodicSync({ socket, database, familyId: deviceEntry.familyId, deviceId: deviceEntry.deviceId });\n'
    }
];
let s = fs.readFileSync(file, 'utf8');
for (const { anchor, hook } of parts) {
    if (s.includes(anchor + hook)) continue;
    const n = s.split(anchor).length - 1;
    if (n !== 1) {
        console.error('ha-sync: kotva sedi ' + n + 'x, cakal som 1x: ' + anchor.trim());
        process.exit(1);
    }
    s = s.replace(anchor, anchor + hook);
}
fs.writeFileSync(file, s);
console.log('ha-sync: zapojene do ' + file);
