"use strict";
/*
 * Doplnok servera pre Home Assistant: synchronizacia detskych zariadeni.
 * V povodnom serveri nie je - Dockerfile ho kopiruje do
 * build/websocket/ha-sync.js a patches/apply-ha-sync.js ho zapoji do
 * build/websocket/index.js (nacita sa so serverom, kazde prihlasenie
 * zariadenia na websocket zavola startPeriodicSync).
 *
 * Preco: appka TimeLimit si spotrebovany cas zapisuje kazdych 30 s, ale
 * odosiela ho s najnizsou prioritou - najskor 10 minut po poslednej
 * synchronizacii (SyncUtil, priorita VeryUnimportant). HA by tak cas tabletu
 * videl oneskoreny az o 10 minut a zdielany rozpocet s PC by sa ratal zle.
 *
 * Server preto pripojenemu zariadeniu dietata posiela 'should sync'
 * {isImportant: true}. Appka na to hned odosle cakajuce akcie (aj spotrebu)
 * a stiahne zmeny - to iste, co robi po kazdej zmene od rodica. Do databazy
 * sa nic nezapisuje, je to len sprava na socket.
 *
 * Rytmus:
 *   - kym zariadenie posiela nove akcie, kazdych HA_SYNC_ACTIVE_SEC (30 s);
 *   - ked dve kola po sebe nic nove neposlalo (nic sa nerata, obrazovka
 *     zhasnuta), uz ho neziada vobec - posledna z tychto synchronizacii je
 *     ta "jedna pri necinnosti";
 *   - znova sa rozbehne, ked zariadenie nieco odosle samo (napr. pri
 *     opatovnom pripojeni po zapnuti obrazovky), alebo ked HA zavola
 *     POST http://127.0.0.1:HA_SYNC_PORT/sync (most na prikaz {"action":"sync"},
 *     HA pri zapnuti obrazovky tabletu) - to zariadenie hned poziada
 *     o synchronizaciu a minutu sleduje, ci sa nieco rata.
 * Port pocuva len na 127.0.0.1 vnutri kontajnera (most bezi vedla).
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
const IDLE_ROUNDS = 2;
const PORT = Number(process.env.HA_SYNC_PORT) || 8081;
const disabled = process.env.HA_SYNC_DISABLE === '1';

// pripojene zariadenia: kazde ma wake() - hned synchronizovat a sledovat znova
const controls = new Set();

const startPeriodicSync = ({ socket, database, familyId, deviceId }) => {
    if (disabled) return;
    let lastSeq = null;
    let idleRounds = 0;
    let isChild = null;
    let lastEmit = 0;
    const emit = () => {
        if (!socket.connected) return;
        lastEmit = Date.now();
        socket.emit('should sync', { isImportant: true });
    };
    const control = {
        wake: () => {
            if (isChild === false) return false;
            lastSeq = null;
            idleRounds = 0;
            emit();
            return true;
        }
    };
    controls.add(control);
    const timer = setInterval(() => {
        if (!socket.connected) return;
        (async () => {
            const device = await database.device.findOne({
                where: { familyId, deviceId },
                attributes: ['nextSequenceNumber', 'currentUserId']
            });
            if (!device || !device.currentUserId) { isChild = false; return; }
            const user = await database.user.findOne({
                where: { familyId, userId: device.currentUserId },
                attributes: ['type']
            });
            isChild = !!user && user.type === 'child';
            if (!isChild) return;
            // nextSequenceNumber rastie s kazdou akciou, ktoru zariadenie odosle
            const seq = String(device.nextSequenceNumber);
            if (lastSeq !== null) idleRounds = seq === lastSeq ? idleRounds + 1 : 0;
            lastSeq = seq;
            // po prebudeni z HA neposielat hned druhy pokyn
            if (idleRounds < IDLE_ROUNDS && Date.now() - lastEmit >= ACTIVE / 2) emit();
        })().catch(() => { });
    }, ACTIVE);
    socket.on('disconnect', () => {
        clearInterval(timer);
        controls.delete(control);
    });
};
exports.startPeriodicSync = startPeriodicSync;

if (!disabled) {
    http.createServer((req, res) => {
        if (req.method === 'POST' && req.url === '/sync') {
            let woken = 0;
            for (const c of controls) if (c.wake()) woken++;
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ woken }));
        } else {
            res.writeHead(404);
            res.end();
        }
    }).on('error', (e) => console.warn('[ha-sync] port ' + PORT + ': ' + e.message))
        .listen(PORT, '127.0.0.1');
}
