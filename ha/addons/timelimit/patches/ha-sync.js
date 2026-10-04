"use strict";
/*
 * Doplnok servera pre Home Assistant: pravidelna synchronizacia detskych
 * zariadeni. V povodnom serveri nie je - Dockerfile ho kopiruje do
 * build/websocket/ha-sync.js a patches/apply-ha-sync.js ho zapoji do
 * build/websocket/index.js (po prihlaseni zariadenia na websocket).
 *
 * Preco: appka TimeLimit si spotrebovany cas zapisuje kazdych 30 s, ale
 * odosiela ho s najnizsou prioritou - najskor 10 minut po poslednej
 * synchronizacii (SyncUtil, priorita VeryUnimportant). HA by tak cas tabletu
 * videl oneskoreny az o 10 minut a zdielany rozpocet s PC by sa ratal zle.
 *
 * Kym je zariadenie dietata pripojene na websocket, posielame mu
 * 'should sync' {isImportant: true}. Appka na to hned odosle cakajuce akcie
 * (aj spotrebu) a stiahne zmeny - presne to iste, co robi po kazdej zmene od
 * rodica. Do databazy sa nic nezapisuje, je to len sprava na socket.
 *
 * Rytmus: HA_SYNC_ACTIVE_SEC (30 s), kym zariadenie posiela nove akcie. Ked
 * dve kola po sebe nic neposlalo (obrazovka zhasnuta, nic sa nerata), ide
 * riedko - HA_SYNC_IDLE_SEC (120 s). Appka sa bez experimentalneho prepinaca
 * "Keep connected when the screen is off" pri zhasnutej obrazovke odpaja, vtedy
 * nebezi nic. HA_SYNC_DISABLE=1 doplnok vypne.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.startPeriodicSync = void 0;

const seconds = (name, fallback, min) => {
    const v = Number(process.env[name]);
    return Math.max(min, Number.isFinite(v) && v > 0 ? v : fallback) * 1000;
};
const ACTIVE = seconds('HA_SYNC_ACTIVE_SEC', 30, 10);
const IDLE = Math.max(ACTIVE, seconds('HA_SYNC_IDLE_SEC', 120, 30));
const IDLE_ROUNDS = 2;

const startPeriodicSync = ({ socket, database, familyId, deviceId }) => {
    if (process.env.HA_SYNC_DISABLE === '1') return;
    let lastSeq = null;
    let idleRounds = 0;
    // po pripojeni si appka dolezitu synchronizaciu vyziada sama
    let lastEmit = Date.now();
    const timer = setInterval(() => {
        if (!socket.connected) return;
        (async () => {
            const device = await database.device.findOne({
                where: { familyId, deviceId },
                attributes: ['nextSequenceNumber', 'currentUserId']
            });
            if (!device || !device.currentUserId) return;
            const user = await database.user.findOne({
                where: { familyId, userId: device.currentUserId },
                attributes: ['type']
            });
            if (!user || user.type !== 'child') return;
            // nextSequenceNumber rastie s kazdou odoslanou akciou zariadenia
            const seq = String(device.nextSequenceNumber);
            if (lastSeq !== null) idleRounds = seq === lastSeq ? idleRounds + 1 : 0;
            lastSeq = seq;
            const wait = idleRounds >= IDLE_ROUNDS ? IDLE : ACTIVE;
            if (Date.now() - lastEmit >= wait - 1000) {
                lastEmit = Date.now();
                if (socket.connected) socket.emit('should sync', { isImportant: true });
            }
        })().catch(() => { });
    }, ACTIVE);
    socket.on('disconnect', () => clearInterval(timer));
};
exports.startPeriodicSync = startPeriodicSync;
