"use strict";
/*
 * Doplnok servera pre Home Assistant: synchronizacia detskych zariadeni.
 * V povodnom serveri nie je - Dockerfile ho kopiruje do
 * build/websocket/ha-sync.js a patches/apply-ha-sync.js ho zapoji do
 * build/websocket/index.js (nacita sa so serverom, kazde prihlasenie
 * zariadenia na websocket zavola startPeriodicSync).
 *
 * Preco: appka TimeLimit si spotrebovany cas zapisuje kazdych 30 s (a hned
 * pri zhasnuti obrazovky), ale odosiela ho s najnizsou prioritou - najskor
 * 10 minut po poslednej synchronizacii (SyncUtil, VeryUnimportant). HA by tak
 * cas tabletu videl oneskoreny az o 10 minut.
 *
 * Server preto pripojenemu zariadeniu dietata posiela 'should sync'
 * {isImportant: true}; appka hned odosle cakajuce akcie (aj spotrebu) a
 * stiahne zmeny - to iste, co robi po kazdej zmene od rodica. Do databazy sa
 * nic nezapisuje, je to len sprava na socket.
 *
 * Kedy, podla stavu obrazovky (HA ho hlasi cez POST /screen, zdroj je senzor
 * Interactive z companion appky na tablete):
 *   - zapnuta: kazdych HA_SYNC_ACTIVE_SEC (30 s), aj ked sa prave nic nerata
 *     (dieta moze z "Allowed Apps" kedykolvek prejst do appky s limitom);
 *     po zapnuti hned. Poistka: ked sa hodinu nic neodoslalo (zaseknuty stav),
 *     len raz za 10 minut;
 *   - zhasnutie: hned jedna zaverecna synchronizacia (appka si spotrebu
 *     zapise do 0,1 s po zhasnuti, HA sa to dozvie o sekundu-dve neskor) a
 *     este jedna o 30 s ako poistka; potom uz nic, kym zariadenie samo nieco
 *     neposle (napr. hudba hra aj so zhasnutou obrazovkou a rata sa);
 *   - neznamy (HA nic nehlasi): pripojenie sa berie ako zapnuta obrazovka -
 *     appka bez prepinaca "Keep connected when the screen is off" sa pri
 *     zhasnuti do 1 s odpoji, takze pripojena = obrazovka svieti. Prepinac
 *     bez senzora Interactive preto nezapinat (budilo by to aj pri zhasnutej
 *     obrazovke, po hodine ticha aspon len raz za 10 minut).
 * Bez prepinaca sa po zhasnuti uz synchronizovat neda (socket je prec);
 * zvysok pride po zapnuti obrazovky, ked sa appka pripoji a synchronizuje sama.
 *
 * Endpointy (len 127.0.0.1 vnutri kontajnera, most bezi vedla):
 *   POST /sync                    - hned synchronizovat (tlacidlo v HA)
 *   POST /screen?state=on|off|unknown
 *   GET  /status                  - stav pripojenych detskych zariadeni
 * HA_SYNC_DISABLE=1 doplnok vypne.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.startPeriodicSync = void 0;
const http = require("http");

const seconds = (name, fallback, min) => {
    const v = Number(process.env[name]);
    return Math.max(min, Number.isFinite(v) && v > 0 ? v : fallback) * 1000;
};
const ACTIVE = seconds('HA_SYNC_ACTIVE_SEC', 30, 10);
const MINUTE = 60 * 1000;
const STUCK_ON_AFTER = 60 * MINUTE;   // "zapnuta" a hodinu bez akejkolvek akcie
const STUCK_ON_EVERY = 10 * MINUTE;
const OFF_QUIET = 40 * 1000;          // zhasnute: zariadenie este posiela?
const PORT = Number(process.env.HA_SYNC_PORT) || 8081;
const disabled = process.env.HA_SYNC_DISABLE === '1';

// stav obrazovky podla HA - jeden pre vsetky deti (dieta ma jeden tablet);
// drzi sa aj cez opatovne pripojenie zariadenia
const screen = { state: 'unknown', at: Date.now() };
// pripojene zariadenia
const controls = new Set();

const startPeriodicSync = ({ socket, database, familyId, deviceId }) => {
    if (disabled) return;
    const st = {
        deviceId,
        connectedAt: Date.now(),
        isChild: null,
        lastSeq: null,
        lastSeqChangeAt: 0,
        wokenAt: 0,
        lastEmit: Date.now(),         // po pripojeni sa appka synchronizuje sama
        finalAt: 0                     // poistna synchronizacia po zhasnuti
    };
    const emit = () => {
        if (!socket.connected) return;
        st.lastEmit = Date.now();
        socket.emit('should sync', { isImportant: true });
    };
    const control = {
        st,
        wake: () => {
            if (st.isChild === false) return false;
            st.wokenAt = Date.now();
            emit();
            return true;
        },
        screenChanged: (state) => {
            if (st.isChild === false) return false;
            st.finalAt = state === 'off' ? Date.now() + ACTIVE : 0;
            emit();
            return true;
        }
    };
    controls.add(control);
    const due = (now) => {
        if (st.finalAt && now >= st.finalAt) { st.finalAt = 0; return true; }
        const sinceEmit = now - st.lastEmit;
        if (screen.state === 'off') {
            // zhasnute: len kym zariadenie samo posiela (napr. hudba)
            const sending = now - Math.max(st.lastSeqChangeAt, st.wokenAt) < OFF_QUIET;
            return sending && sinceEmit >= ACTIVE - 1000;
        }
        // zapnute alebo nezname (pripojene = svieti)
        const quietFor = now - Math.max(screen.at, st.lastSeqChangeAt, st.connectedAt, st.wokenAt);
        return sinceEmit >= (quietFor < STUCK_ON_AFTER ? ACTIVE : STUCK_ON_EVERY) - 1000;
    };
    const timer = setInterval(() => {
        if (!socket.connected) return;
        (async () => {
            const device = await database.device.findOne({
                where: { familyId, deviceId },
                attributes: ['nextSequenceNumber', 'currentUserId']
            });
            if (!device || !device.currentUserId) { st.isChild = false; return; }
            const user = await database.user.findOne({
                where: { familyId, userId: device.currentUserId },
                attributes: ['type']
            });
            st.isChild = !!user && user.type === 'child';
            if (!st.isChild) return;
            // nextSequenceNumber rastie s kazdou akciou, ktoru zariadenie odosle
            const seq = String(device.nextSequenceNumber);
            const now = Date.now();
            if (st.lastSeq !== null && seq !== st.lastSeq) st.lastSeqChangeAt = now;
            st.lastSeq = seq;
            if (due(now)) emit();
        })().catch(() => { });
    }, Math.min(ACTIVE, 15 * 1000));
    socket.on('disconnect', () => {
        clearInterval(timer);
        controls.delete(control);
    });
};
exports.startPeriodicSync = startPeriodicSync;

const status = () => ({
    screen: screen.state,
    screenAt: new Date(screen.at).toISOString(),
    devices: [...controls].filter((c) => c.st.isChild !== false).map((c) => ({
        deviceId: c.st.deviceId,
        connectedAt: new Date(c.st.connectedAt).toISOString(),
        lastUploadAt: c.st.lastSeqChangeAt ? new Date(c.st.lastSeqChangeAt).toISOString() : null,
        lastNudgeAt: new Date(c.st.lastEmit).toISOString()
    }))
});

if (!disabled) {
    http.createServer((req, res) => {
        const url = new URL(req.url, 'http://127.0.0.1');
        const reply = (code, body) => {
            res.writeHead(code, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify(body));
        };
        if (req.method === 'POST' && url.pathname === '/sync') {
            let woken = 0;
            for (const c of controls) if (c.wake()) woken++;
            reply(200, { woken });
        } else if (req.method === 'POST' && url.pathname === '/screen') {
            const state = url.searchParams.get('state');
            if (!['on', 'off', 'unknown'].includes(state)) return reply(400, { error: 'state=on|off|unknown' });
            const changed = state !== screen.state;
            screen.state = state;
            screen.at = Date.now();
            let woken = 0;
            if (changed && state !== 'unknown') for (const c of controls) if (c.screenChanged(state)) woken++;
            reply(200, { screen: state, changed, woken });
        } else if (req.method === 'GET' && url.pathname === '/status') {
            reply(200, status());
        } else {
            reply(404, { error: 'not found' });
        }
    }).on('error', (e) => console.warn('[ha-sync] port ' + PORT + ': ' + e.message))
        .listen(PORT, '127.0.0.1');
}
