/*
 * Spusta sa pri builde image (Dockerfile): zapoji patches/ha-sync.js do
 * build/websocket/index.js - nacitanie modulu so serverom (spusti port pre
 * HA) a volanie po ohlaseni pripojeneho zariadenia - a do build/api/sync.js
 * (zaznam o kazdom pull-status zariadenia). Ked kotvy v novej verzii servera
 * nesedia, build spadne - nech sa doplnok nestrati potichu.
 */
'use strict';
const fs = require('fs');
const build = process.argv[2] || '/usr/src/app/build';
const files = {
    'websocket/index.js': [
        {
            anchor: 'const rooms_1 = require("./rooms");\n',
            hook: '// HA: synchronizacia detskych zariadeni (patches/ha-sync.js)\nconst haSync = require("./ha-sync");\n'
        },
        {
            anchor: '                    connectedDevicesManager.connectedDevicesManager.reportDeviceConnected({ key });\n',
            hook: '                    haSync.startPeriodicSync({ socket, database, familyId: deviceEntry.familyId, deviceId: deviceEntry.deviceId });\n'
        }
    ],
    // kazde stiahnutie zmien zariadenim (pull-status) - most podla toho vie,
    // ze si tablet uplny zamok naozaj stiahol
    'api/sync.js': [
        {
            anchor: '                const { familyId, deviceId, lastConnectivity } = deviceEntryUnsafe;\n',
            hook: '                require("../websocket/ha-sync").notePull(deviceId);\n'
        }
    ]
};
for (const [rel, parts] of Object.entries(files)) {
    const file = build + '/' + rel;
    let s = fs.readFileSync(file, 'utf8');
    for (const { anchor, hook } of parts) {
        if (s.includes(anchor + hook)) continue;
        const n = s.split(anchor).length - 1;
        if (n !== 1) {
            console.error('ha-sync: ' + rel + ': kotva sedi ' + n + 'x, cakal som 1x: ' + anchor.trim());
            process.exit(1);
        }
        s = s.replace(anchor, anchor + hook);
    }
    fs.writeFileSync(file, s);
    console.log('ha-sync: zapojene do ' + file);
}
