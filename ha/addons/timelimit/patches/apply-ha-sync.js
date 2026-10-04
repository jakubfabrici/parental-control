/*
 * Spusta sa pri builde image (Dockerfile): zapoji patches/ha-sync.js do
 * build/websocket/index.js hned za ohlasenie pripojeneho zariadenia.
 * Ked sa kotva v novej verzii servera zmeni, build spadne - nech sa doplnok
 * nestrati potichu.
 */
'use strict';
const fs = require('fs');
const file = process.argv[2] || '/usr/src/app/build/websocket/index.js';
const anchor = '                    connectedDevicesManager.connectedDevicesManager.reportDeviceConnected({ key });\n';
const hook = '                    // HA: pravidelna synchronizacia detskych zariadeni (patches/ha-sync.js)\n' +
    '                    require(\'./ha-sync\').startPeriodicSync({ socket, database, familyId: deviceEntry.familyId, deviceId: deviceEntry.deviceId });\n';
let s = fs.readFileSync(file, 'utf8');
if (s.includes(hook)) {
    console.log('ha-sync: uz zapojene');
    process.exit(0);
}
const n = s.split(anchor).length - 1;
if (n !== 1) {
    console.error('ha-sync: kotva sedi ' + n + 'x, cakal som 1x');
    process.exit(1);
}
s = s.replace(anchor, anchor + hook);
fs.writeFileSync(file, s);
console.log('ha-sync: zapojene do ' + file);
