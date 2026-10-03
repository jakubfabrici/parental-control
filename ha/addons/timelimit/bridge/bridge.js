/*
 * Most medzi TimeLimit serverom a Home Assistantom.
 *
 * Server nema REST API pre tretie strany, ma len sync protokol pre svoju appku.
 * Tento most sa do rodiny prihlasi ako dalsie rodicovske zariadenie
 * ("Home Assistant") cez mailovy kod - ten si sam precita z Mailpitu, ktory
 * bezi v tom istom kontajneri. Zariadenie prihlasene cez
 * /parent/sign-in-into-family dostane isUserKeptSignedIn = true, takze
 * rodicovske akcie prejdu s integrity "device" - bez hesla a bez HMAC.
 *
 * Potom raz za sync_interval taha /sync/pull-status, drzi si kopiu dat rodiny
 * a cez MQTT discovery vytvara v HA entity (per dieta, kategoria, zariadenie).
 * Prikazy z HA (switch/number/set, timelimit/cmd) prekladat na rodicovske akcie
 * do /sync/push-actions.
 *
 * Protokol je viazany na server v1.17.0 - meni sa len vtedy, ked server
 * aktualizuje Jakub.
 */
'use strict';

const fs = require('fs');
const crypto = require('crypto');
const mqtt = require('mqtt');

const OPTIONS_FILE = process.env.OPTIONS_FILE || '/data/options.json';
const STATE_FILE = process.env.STATE_FILE || '/data/bridge.json';
const SERVER = process.env.TIMELIMIT_URL || 'http://127.0.0.1:8080';
const MAILPIT = process.env.MAILPIT_URL || 'http://127.0.0.1:8025';
const SUPERVISOR_TOKEN = process.env.SUPERVISOR_TOKEN || '';
const DISCOVERY_PREFIX = 'homeassistant';
const BASE = 'timelimit';
const MINUTE = 60 * 1000;
const FULL_DAY_START = 0;
const FULL_DAY_END = 24 * 60 - 1;

const log = (...a) => console.log('[bridge]', ...a);
const warn = (...a) => console.error('[bridge]', ...a);

// ---------------------------------------------------------------- options / stav

function readJson(file, fallback) {
    try {
        return JSON.parse(fs.readFileSync(file, 'utf8'));
    } catch (e) {
        return fallback;
    }
}

const options = readJson(OPTIONS_FILE, {});
const parentMail = (options.parent_mail || '').trim().toLowerCase();
const syncInterval = Math.max(15, Number(options.sync_interval) || 60) * 1000;
const bridgeDeviceName = options.bridge_device_name || 'Home Assistant';
// kategoria, ktora znamena "vzdy povolene" (bez pravidiel) - podla nazvu v appke
const alwaysAllowedTitle = (options.always_allowed_category || 'Allowed Apps').trim().toLowerCase();
const NONE = '—';

const emptyState = () => ({
    mail: '',
    deviceAuthToken: '',
    deviceId: '',
    parentUserId: '',
    seq: 0,
    // co server uz poslal (verzie) - posiela sa spat v pull-status
    status: { devices: '', users: '', apps: {}, categories: {}, devicesDetail: {} },
    devices: [],
    users: [],
    categories: {},   // id -> { base, rules, usedTimes, apps }
    published: {},    // discovery topic -> true (aby sa dali odstranit)
    haRules: {},      // categoryId -> ruleId pravidla "strop na dnes", ktore vlastni HA
    targets: {},      // categoryId -> { day, minutes } "cielovy cas na dnes" zo zdielaneho rozpoctu
    lastSync: 0
});

let state = Object.assign(emptyState(), readJson(STATE_FILE, {}));
if (!state.status) state.status = emptyState().status;

function saveState() {
    const tmp = STATE_FILE + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(state));
    fs.renameSync(tmp, STATE_FILE);
}

function nextSeq() {
    // Server preskoci akciu so sequenceNumber < nextSequenceNumber a nastavi
    // next = seq + 1. Stlpec Devices.nextSequenceNumber je int(11), takze
    // cislo musi ostat pod 2^31 - casova znacka v ms tam neprejde (500).
    // Nove zariadenie zacina na 0; token aj citac su v jednom subore, takze
    // pri strate stavu sa most prihlasi znova ako nove zariadenie a zacne od 0.
    if (!Number.isInteger(state.seq) || state.seq < 0 || state.seq > 2000000000) state.seq = 0;
    state.seq += 1;
    return state.seq;
}

const genId = () => {
    const alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const bytes = crypto.randomBytes(6);
    let s = '';
    for (let i = 0; i < 6; i++) s += alphabet[bytes[i] % alphabet.length];
    return s;
};

// ---------------------------------------------------------------- HTTP

class HttpError extends Error {
    constructor(status, body) {
        super('HTTP ' + status + ': ' + String(body).slice(0, 300));
        this.status = status;
        this.body = body;
    }
}

async function post(path, body) {
    const res = await fetch(SERVER + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    });
    const text = await res.text();
    if (!res.ok) throw new HttpError(res.status, text);
    return text ? JSON.parse(text) : {};
}

async function getJson(url) {
    const res = await fetch(url);
    if (!res.ok) throw new HttpError(res.status, await res.text());
    return res.json();
}

// ---------------------------------------------------------------- cas a dni

function localParts(ts, timeZone) {
    const fmt = new Intl.DateTimeFormat('en-CA', {
        timeZone, hourCycle: 'h23',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
    const p = {};
    for (const part of fmt.formatToParts(new Date(ts))) p[part.type] = part.value;
    return {
        y: Number(p.year), m: Number(p.month), d: Number(p.day),
        hh: Number(p.hour), mm: Number(p.minute), ss: Number(p.second)
    };
}

// dayOfEpoch tak, ako ho pocita appka: epoch day lokalneho datumu v casovej zone
function epochDay(ts, timeZone) {
    const { y, m, d } = localParts(ts, timeZone);
    return Math.floor(Date.UTC(y, m - 1, d) / 86400000);
}

// TimeLimit: bit 0 = pondelok ... bit 6 = nedela
function dayBit(ts, timeZone) {
    const { y, m, d } = localParts(ts, timeZone);
    const jsDay = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = nedela
    return 1 << ((jsDay + 6) % 7);
}

function endOfLocalDay(ts, timeZone) {
    const p = localParts(ts, timeZone);
    const offset = Date.UTC(p.y, p.m - 1, p.d, p.hh, p.mm, p.ss) - Math.floor(ts / 1000) * 1000;
    return Date.UTC(p.y, p.m - 1, p.d + 1) - offset;
}

// ---------------------------------------------------------------- Mailpit

async function waitForLoginCode(mail, since, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        const list = await getJson(MAILPIT + '/api/v1/messages?limit=20');
        const msg = (list.messages || []).find((m) =>
            (m.To || []).some((t) => (t.Address || '').toLowerCase() === mail) &&
            Date.parse(m.Created) >= since - 10000);
        if (msg) {
            const full = await getJson(MAILPIT + '/api/v1/message/' + msg.ID);
            const lines = String(full.Text || '').replace(/\r/g, '').split('\n').map((l) => l.trim());
            const idx = lines.findIndex((l) => /enter the following code|folgenden Code/i.test(l));
            const code = lines.slice(idx + 1).find((l) => l.length > 0);
            if (code) return code;
        }
        await sleep(2000);
    }
    throw new Error('prihlasovaci kod nedorazil do Mailpitu do ' + (timeoutMs / 1000) + ' s');
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------- prihlasenie do rodiny

async function mailAuth(mail) {
    const since = Date.now();
    const r1 = await post('/auth/send-mail-login-code-v2', { mail, locale: 'en' });
    if (r1.mailAddressNotWhitelisted) throw new Error('adresa ' + mail + ' nie je vo whiteliste (mail_whitelist)');
    if (r1.mailServerBlacklisted) throw new Error('mailovy server je na blackliste');
    const code = await waitForLoginCode(mail, since, 60000);
    const r2 = await post('/auth/sign-in-by-mail-code', { receivedCode: code, mailLoginToken: r1.mailLoginToken });
    return r2.mailAuthToken;
}

async function enroll(mail) {
    log('prihlasujem sa do rodiny ako "' + bridgeDeviceName + '" cez', mail);
    const mailAuthToken = await mailAuth(mail);
    let r;
    try {
        r = await post('/parent/sign-in-into-family', {
            mailAuthToken,
            parentDevice: { model: 'Home Assistant' },
            deviceName: bridgeDeviceName
        });
    } catch (e) {
        if (e.status === 409) throw new Error('rodina pre ' + mail + ' este neexistuje - zaloz ju v appke');
        throw e;
    }
    state = Object.assign(emptyState(), {
        mail,
        deviceAuthToken: r.deviceAuthToken,
        deviceId: r.ownDeviceId,
        published: state.published || {}
    });
    applyServerStatus(r.data || {});
    const me = state.devices.find((d) => d.deviceId === state.deviceId);
    const parent = state.users.find((u) => u.type === 'parent' && (u.mail || '').toLowerCase() === mail)
        || (me && state.users.find((u) => u.id === me.currentUserId));
    if (!parent) throw new Error('v rodine som nenasiel rodica s adresou ' + mail);
    state.parentUserId = parent.id;
    saveState();
    log('prihlasene: zariadenie', state.deviceId, 'rodic', parent.name, '(' + parent.id + ')');
}

// ---------------------------------------------------------------- sync (pull)

function clientStatus() {
    const s = state.status;
    const categories = {};
    for (const [id, c] of Object.entries(s.categories)) {
        categories[id] = { base: c.base || '', apps: c.apps || '', rules: c.rules || '', usedTime: c.usedTime || '', tasks: c.tasks || '' };
    }
    const out = { devices: s.devices || '', users: s.users || '', apps: s.apps || {}, categories, devicesDetail: s.devicesDetail || {} };
    if (s.dh) out.dh = s.dh;
    if (s.u2f) out.u2f = s.u2f;
    if (s.kri) out.kri = s.kri;
    if (s.kr) out.kr = s.kr;
    return out;
}

// zapracuje odpoved servera (ServerDataStatus) do lokalnej kopie; vrati true,
// ked pribudla kategoria, o ktorej este nemame pravidla/casy (treba dalsi pull)
function applyServerStatus(d) {
    const s = state.status;
    let needMore = false;
    if (d.devices) { state.devices = d.devices.data || []; s.devices = d.devices.version || ''; }
    if (d.users) { state.users = d.users.data || []; s.users = d.users.version || ''; }
    for (const id of d.rmCategories || []) { delete state.categories[id]; delete s.categories[id]; }
    for (const base of d.categoryBase || []) {
        const c = state.categories[base.categoryId] || (state.categories[base.categoryId] = {});
        c.base = base;
        const st = s.categories[base.categoryId] || (s.categories[base.categoryId] = { base: '', apps: '', rules: '', usedTime: '', tasks: '' });
        st.base = base.version;
        if (!st.rules || !st.usedTime) needMore = true;
    }
    for (const r of d.rules || []) {
        const c = state.categories[r.categoryId] || (state.categories[r.categoryId] = {});
        c.rules = r.rules || [];
        const st = s.categories[r.categoryId] || (s.categories[r.categoryId] = { base: '', apps: '', rules: '', usedTime: '', tasks: '' });
        st.rules = r.version;
    }
    for (const u of d.usedTimes || []) {
        const c = state.categories[u.categoryId] || (state.categories[u.categoryId] = {});
        c.usedTimes = u.times || [];
        const st = s.categories[u.categoryId] || (s.categories[u.categoryId] = { base: '', apps: '', rules: '', usedTime: '', tasks: '' });
        st.usedTime = u.version;
    }
    for (const a of d.categoryApp || []) {
        const c = state.categories[a.categoryId] || (state.categories[a.categoryId] = {});
        c.apps = a.apps || [];
        const st = s.categories[a.categoryId] || (s.categories[a.categoryId] = { base: '', apps: '', rules: '', usedTime: '', tasks: '' });
        st.apps = a.version;
    }
    for (const t of d.tasks || []) {
        const st = s.categories[t.categoryId];
        if (st) st.tasks = t.version;
    }
    for (const a of d.apps || []) s.apps[a.deviceId] = a.version;
    for (const dd of d.devices2 || []) {
        s.devicesDetail[dd.deviceId] = {
            appsB: dd.appsBase ? dd.appsBase.version : '',
            appsD: dd.appsDiff ? dd.appsDiff.version : ''
        };
    }
    if (d.dh) s.dh = d.dh.v;
    if (d.u2f) s.u2f = d.u2f.v;
    for (const k of d.krq || []) s.kri = Math.max(s.kri || 0, k.srvSeq);
    for (const k of d.kr || []) s.kr = Math.max(s.kr || 0, k.srvSeq);
    // kategorie, ktore server uz nepozna, by prisli v rmCategories; pre istotu
    // zahod aj tie, ktore nemaju base
    for (const id of Object.keys(state.categories)) if (!state.categories[id].base) { delete state.categories[id]; delete s.categories[id]; }
    return needMore;
}

async function pull() {
    for (let i = 0; i < 4; i++) {
        const d = await post('/sync/pull-status', { deviceAuthToken: state.deviceAuthToken, status: clientStatus() });
        const more = applyServerStatus(d);
        if (!more) break;
    }
    state.lastSync = Date.now();
    saveState();
}

// ---------------------------------------------------------------- push (rodicovske akcie)

async function pushActions(encodedActions) {
    if (!state.deviceAuthToken) throw new Error('most nie je prihlaseny do rodiny');
    const actions = encodedActions.map((a) => ({
        encodedAction: JSON.stringify(a),
        sequenceNumber: nextSeq(),
        integrity: 'device',
        type: 'parent',
        userId: state.parentUserId
    }));
    saveState();
    const r = await post('/sync/push-actions', { deviceAuthToken: state.deviceAuthToken, actions });
    log('push', encodedActions.map((a) => a.type).join(','), '->', JSON.stringify(r));
    return r;
}

// ---------------------------------------------------------------- model rodiny

const children = () => state.users.filter((u) => u.type === 'child');
const userById = (id) => state.users.find((u) => u.id === id);
const catsOf = (childId) => Object.values(state.categories).filter((c) => c.base && c.base.childId === childId);
const topCatsOf = (childId) => catsOf(childId).filter((c) => !c.base.parentCategoryId);
const timeZoneOf = (user) => (user && user.timeZone) || 'Europe/Bratislava';

function usedTodayMs(cat, today) {
    return (cat.usedTimes || [])
        .filter((t) => t.day === today && t.start === FULL_DAY_START && t.end === FULL_DAY_END)
        .reduce((a, t) => a + (t.time || 0), 0);
}

function extraTodayMs(cat, today) {
    const b = cat.base;
    if (!b || !b.extraTime) return 0;
    return (b.extraTimeDay === -1 || b.extraTimeDay === today) ? b.extraTime : 0;
}

function isBlocked(cat, now) {
    const b = cat.base;
    return !!(b && b.tempBlocked && (!b.tempBlockTime || b.tempBlockTime > now));
}

// Pravidla, ktore dnes obmedzuju cely den (bez casovych okien a session
// limitov). perDay = limit plati pre kazdy den masky zvlast; bez perDay je
// to spolocny rozpocet na vsetky dni masky v tomto tyzdni (napr. 180 min na
// vikend dokopy) - vtedy sa od neho odrata aj spotreba z ostatnych dni masky.
function fullDayRulesToday(cat, bit) {
    return (cat.rules || []).filter((r) => (r.dayMask & bit) &&
        (r.start === undefined || r.start === FULL_DAY_START) && (r.end === undefined || r.end === FULL_DAY_END) && !r.extraTime);
}

function isSingleDay(mask) { return mask !== 0 && (mask & (mask - 1)) === 0; }

// epoch day pondelka tyzdna, do ktoreho patri dnesok
function weekStart(today, bit) {
    let dow = 0;
    while ((1 << dow) !== bit && dow < 7) dow++;
    return today - dow;
}

function usedOnDayMs(cat, day) {
    return (cat.usedTimes || [])
        .filter((t) => t.day === day && t.start === FULL_DAY_START && t.end === FULL_DAY_END)
        .reduce((a, t) => a + (t.time || 0), 0);
}

// kolko minut dnes dovoluju pravidla (minimum) a kolko z toho zostava;
// null = ziadne pravidlo na cely den
function limitsToday(cat, today, bit, extra, skipRuleId) {
    const rules = fullDayRulesToday(cat, bit).filter((r) => r.id !== skipRuleId);
    if (rules.length === 0) return { limit: null, remaining: null };
    const usedToday = usedOnDayMs(cat, today);
    const monday = weekStart(today, bit);
    let limit = Infinity;
    let remaining = Infinity;
    for (const r of rules) {
        let otherDays = 0;
        if (!r.perDay && !isSingleDay(r.dayMask)) {
            for (let d = 0; d < 7; d++) {
                const day = monday + d;
                if (day !== today && (r.dayMask & (1 << d))) otherDays += usedOnDayMs(cat, day);
            }
        }
        const todayAllowance = Math.max(0, r.maxTime - otherDays);
        limit = Math.min(limit, todayAllowance);
        remaining = Math.min(remaining, todayAllowance + extra - usedToday);
    }
    return { limit, remaining: Math.max(0, remaining) };
}

function categorySummary(cat, now) {
    const child = userById(cat.base.childId);
    const tz = timeZoneOf(child);
    const today = epochDay(now, tz);
    const bit = dayBit(now, tz);
    const used = usedTodayMs(cat, today);
    const extra = extraTodayMs(cat, today);
    const { limit, remaining } = limitsToday(cat, today, bit, extra);
    return {
        id: cat.base.categoryId,
        title: cat.base.title,
        childId: cat.base.childId,
        parentCategoryId: cat.base.parentCategoryId || '',
        used_min: Math.round(used / MINUTE),
        extra_min: Math.round(extra / MINUTE),
        limit_min: limit === null ? null : Math.round(limit / MINUTE),
        remaining_min: remaining === null ? null : Math.round(remaining / MINUTE),
        blocked: isBlocked(cat, now),
        blocked_until: cat.base.tempBlockTime || 0,
        rules: (cat.rules || []).length,
        target: (state.targets || {})[cat.base.categoryId] || null
    };
}

function childSummary(child, now) {
    const tops = limitedTopCatsOf(child.id).map((c) => categorySummary(c, now));
    const all = catsOf(child.id).map((c) => categorySummary(c, now));
    const withLimit = tops.filter((c) => c.limit_min !== null);
    return {
        id: child.id,
        name: child.name,
        timeZone: timeZoneOf(child),
        used_min: tops.reduce((a, c) => a + c.used_min, 0),
        limit_min: withLimit.length ? Math.min(...withLimit.map((c) => c.limit_min)) : null,
        remaining_min: withLimit.length ? Math.min(...withLimit.map((c) => c.remaining_min)) : null,
        extra_min: tops.length ? Math.max(...tops.map((c) => c.extra_min)) : 0,
        // zablokovanie dietata = vsetky vrcholove kategorie vratane Allowed Apps
        blocked: (() => { const all = topCatsOf(child.id); return all.length > 0 && all.every((c) => isBlocked(c, now)); })(),
        no_limits: !!(child.disableLimitsUntil && child.disableLimitsUntil > now),
        no_limits_until: child.disableLimitsUntil || 0,
        categories: all
    };
}

// Zoznam nainstalovanych aplikacii posiela tablet sifrovane (EncryptedAppLists),
// most ho citat nevie. Vidi vsak balíky priradene do kategorii (CategoryApps),
// takze "vzdy povolene" = presunut balik do kategorie bez pravidiel.
function alwaysAllowedCatOf(childId) {
    return catsOf(childId).find((c) => (c.base.title || '').trim().toLowerCase() === alwaysAllowedTitle) || null;
}

function appsSummary(child) {
    const allowed = alwaysAllowedCatOf(child.id);
    const others = {};
    for (const c of catsOf(child.id)) {
        if (allowed && c.base.categoryId === allowed.base.categoryId) continue;
        others[c.base.title] = (c.apps || []).slice().sort();
    }
    return {
        category: allowed ? allowed.base.title : null,
        category_id: allowed ? allowed.base.categoryId : null,
        apps: allowed ? (allowed.apps || []).slice().sort() : [],
        other_apps: others,
        unassigned_category: (() => { const c = state.categories[child.categoryForNotAssignedApps]; return c ? c.base.title : null; })()
    };
}

// Vrcholove kategorie s limitom = vsetky okrem "vzdy povolenych". Prikazy na
// urovni dietata (extra cas, strop, cielovy cas) idu len sem - inak by strop
// obmedzil aj Allowed Apps.
function limitedTopCatsOf(childId) {
    const allowed = alwaysAllowedCatOf(childId);
    return topCatsOf(childId).filter((c) => !allowed || c.base.categoryId !== allowed.base.categoryId);
}

async function addAlwaysAllowed(child, packageName) {
    const allowed = alwaysAllowedCatOf(child.id);
    if (!allowed) throw new Error('dieta ' + child.name + ' nema kategoriu "' + alwaysAllowedTitle + '"');
    const pkg = String(packageName || '').trim();
    if (!/^[A-Za-z0-9_.:@-]{3,200}$/.test(pkg)) throw new Error('neplatny nazov balika: ' + pkg);
    // ADD_CATEGORY_APPS balik zaroven odoberie z inych kategorii dietata (presun)
    await pushActions([{ type: 'ADD_CATEGORY_APPS', categoryId: allowed.base.categoryId, packageNames: [pkg] }]);
}

async function removeAlwaysAllowed(child, packageName) {
    const allowed = alwaysAllowedCatOf(child.id);
    if (!allowed) throw new Error('dieta ' + child.name + ' nema kategoriu "' + alwaysAllowedTitle + '"');
    const pkg = String(packageName || '').trim();
    if (!(allowed.apps || []).includes(pkg)) throw new Error(pkg + ' nie je medzi vzdy povolenymi');
    // Nepriradeny balik padne do categoryForNotAssignedApps; ked ziadna nie je
    // nastavena, appka ho blokuje. Ked ma dieta prave jednu dalsiu vrcholovu
    // kategoriu, presunieme ho radsej tam (typicky "hry s limitom").
    const otherTops = topCatsOf(child.id).filter((c) => c.base.categoryId !== allowed.base.categoryId);
    if (!child.categoryForNotAssignedApps && otherTops.length === 1) {
        await pushActions([{ type: 'ADD_CATEGORY_APPS', categoryId: otherTops[0].base.categoryId, packageNames: [pkg] }]);
    } else {
        await pushActions([{ type: 'REMOVE_CATEGORY_APPS', categoryId: allowed.base.categoryId, packageNames: [pkg] }]);
    }
}

// ---------------------------------------------------------------- akcie

function actBlock(categoryId, blocked, endTime) {
    const a = { type: 'UPDATE_CATEGORY_TEMPORARILY_BLOCKED', categoryId, blocked: !!blocked };
    if (blocked && endTime) a.endTime = endTime;
    return a;
}

async function setChildBlocked(child, blocked, minutes) {
    const endTime = blocked && minutes ? Date.now() + minutes * MINUTE : undefined;
    // zablokovat staci vrcholove kategorie (podkategorie dedia), odblokovat vsetky
    const cats = blocked ? topCatsOf(child.id) : catsOf(child.id);
    if (cats.length === 0) throw new Error('dieta ' + child.name + ' nema ziadne kategorie');
    await pushActions(cats.map((c) => actBlock(c.base.categoryId, blocked, endTime)));
}

async function setCategoryBlocked(cat, blocked, minutes) {
    const endTime = blocked && minutes ? Date.now() + minutes * MINUTE : undefined;
    await pushActions([actBlock(cat.base.categoryId, blocked, endTime)]);
}

async function setNoLimits(child, on, minutes) {
    const tz = timeZoneOf(child);
    const time = on ? (minutes ? Date.now() + minutes * MINUTE : endOfLocalDay(Date.now(), tz)) : 0;
    await pushActions([{ type: 'SET_USER_DISABLE_LIMITS_UNTIL', childId: child.id, time }]);
}

function actExtra(cat, minutes, today, increment) {
    return increment
        ? { type: 'INCREMENT_CATEGORY_EXTRATIME', categoryId: cat.base.categoryId, addedExtraTime: Math.round(minutes * MINUTE), day: today }
        : { type: 'SET_CATEGORY_EXTRA_TIME', categoryId: cat.base.categoryId, newExtraTime: Math.max(0, Math.round(minutes * MINUTE)), day: today };
}

async function setExtra(cats, minutes, increment) {
    if (cats.length === 0) throw new Error('ziadna kategoria');
    const child = userById(cats[0].base.childId);
    const today = epochDay(Date.now(), timeZoneOf(child));
    await pushActions(cats.map((c) => actExtra(c, minutes, today, increment)));
}

// "Strop na dnes": pravidlo, ktore vlastni HA. Appka ma svoj tyzdenny rozvrh
// (casto jedno pravidlo na kazdy den) a ten sa NIKDY nemeni - HA si drzi
// vlastne pravidlo len s dnesnym dnom (id si pamata v state.haRules) a plati
// minimum zo vsetkych pravidiel, takze HA vie strop len stlacit nizsie;
// zvysit sa da extra casom. Rovnako to robi dnesna Family Link integracia.
// Strop >= 1440 min alebo zaporny = pravidlo HA zmazat (ziadny strop).
function haRuleOf(cat) {
    const id = (state.haRules || {})[cat.base.categoryId];
    return id ? (cat.rules || []).find((r) => r.id === id) || null : null;
}

function actLimitToday(cat, minutes, bit) {
    const existing = haRuleOf(cat);
    if (!(minutes >= 0) || minutes >= 1440) {
        if (!existing) return [];
        delete state.haRules[cat.base.categoryId];
        return [{ type: 'DELETE_TIMELIMIT_RULE', ruleId: existing.id }];
    }
    const time = Math.round(minutes * MINUTE);
    const common = { time, days: bit, extraTime: false, start: FULL_DAY_START, end: FULL_DAY_END, dur: 0, pause: 0, perDay: true };
    if (existing) {
        return [Object.assign({ type: 'UPDATE_TIMELIMIT_RULE', ruleId: existing.id }, common)];
    }
    const ruleId = genId();
    state.haRules = state.haRules || {};
    state.haRules[cat.base.categoryId] = ruleId;
    return [{ type: 'CREATE_TIMELIMIT_RULE', rule: Object.assign({ ruleId, categoryId: cat.base.categoryId }, common) }];
}

async function setLimitToday(cats, minutes) {
    if (cats.length === 0) throw new Error('ziadna kategoria');
    const child = userById(cats[0].base.childId);
    const bit = dayBit(Date.now(), timeZoneOf(child));
    const actions = cats.flatMap((c) => actLimitToday(c, minutes, bit));
    if (actions.length > 0) await pushActions(actions);
}

// "Cielovy cas na dnes" (zdielany rozpocet s PC): HA povie, kolko minut smie
// kategoria dnes CELKOVO (T). Pravidla appky su strop, ktory HA zvysit nevie,
// preto: vlastne pravidlo HA = min(T, strop appky) a co je nad strop appky,
// doplni extra cas. Extra cas appka pri pouzivani odpocitava, takze ho most
// pri kazdej synchronizacii dorovna na presny zvysok:
//   extra = max(0, (T - pouzite) - max(0, cap - pouzite))
// Zvysok pre appku je potom max(0, cap - pouzite) + extra = T - pouzite.
// Rucny extra cas a strop z dashboardu sa pri aktivnom cieli prepisu.
//
// Setrenie baterky tabletu: kazdy push na server znamena "should sync" pre
// tablet (websocket) a ten sa hned synchronizuje. Ked sedi pri PC, ciel
// klesa kazdu minutu - posielat to kazdu minutu by tablet budilo zbytocne.
// Preto: uvolnenie (rodic pridal cas) ide hned; sprisnenie sa posiela az
// ked narastie aspon na TARGET_STEP minut, a ked tabletu zostava menej nez
// TARGET_EXACT minut, ide presne. Tablet tak nikdy neprekroci spolocny
// rozpocet, len sa dozvie o spotrebe na PC po 5-minutovych krokoch.
const TARGET_STEP = 5 * MINUTE;
const TARGET_EXACT = 15 * MINUTE;

function worthSending(want, have, remainingAfter) {
    if (want === have) return false;
    if (want > have) return true;                       // uvolnenie: hned
    if (remainingAfter <= TARGET_EXACT) return true;    // koniec: presne
    return (have - want) >= TARGET_STEP;                // inak po krokoch
}

async function enforceTargets() {
    const actions = [];
    for (const [categoryId, tgt] of Object.entries(state.targets || {})) {
        const cat = state.categories[categoryId];
        if (!cat) { delete state.targets[categoryId]; continue; }
        const child = userById(cat.base.childId);
        const tz = timeZoneOf(child);
        const now = Date.now();
        const today = epochDay(now, tz);
        if (tgt.day !== today) { delete state.targets[categoryId]; continue; }
        const bit = dayBit(now, tz);
        const T = Math.min(1440, Math.max(0, tgt.minutes)) * MINUTE;
        const used = usedTodayMs(cat, today);
        const haRule = haRuleOf(cat);
        const app = limitsToday(cat, today, bit, 0, haRule ? haRule.id : undefined);
        const appCap = app.limit;                       // ms alebo null
        const cap = appCap === null ? T : Math.min(T, appCap);
        // pravidlo HA: netreba, ked strop appky uz staci (T >= appCap)
        const wantRuleMin = (appCap !== null && T >= appCap) ? null : Math.round(cap / MINUTE);
        const haveRuleMin = haRule ? Math.round(haRule.maxTime / MINUTE) : null;
        const remainingAfter = T - used;
        if (wantRuleMin !== haveRuleMin) {
            // bez pravidla HA = strop appky (alebo nekonecno)
            const asMs = (m) => (m === null ? (appCap === null ? Infinity : appCap) : m * MINUTE);
            if (worthSending(asMs(wantRuleMin), asMs(haveRuleMin), remainingAfter)) {
                actions.push(...actLimitToday(cat, wantRuleMin === null ? 1440 : wantRuleMin, bit));
            }
        }
        const wantExtra = Math.max(0, (T - used) - Math.max(0, cap - used));
        const haveExtra = extraTodayMs(cat, today);
        if (Math.abs(wantExtra - haveExtra) >= MINUTE && worthSending(wantExtra, haveExtra, remainingAfter)) {
            actions.push({ type: 'SET_CATEGORY_EXTRA_TIME', categoryId, newExtraTime: Math.round(wantExtra), day: today });
        }
        tgt.applied = { rule_min: wantRuleMin, extra_min: Math.round(wantExtra / MINUTE), used_min: Math.round(used / MINUTE) };
    }
    if (actions.length > 0) {
        log('ciel na dnes: posielam', actions.map((a) => a.type).join(','));
        await pushActions(actions);
        await pull();
    }
}

async function setTarget(cats, minutes) {
    if (cats.length === 0) throw new Error('ziadna kategoria');
    for (const cat of cats) {
        const child = userById(cat.base.childId);
        const today = epochDay(Date.now(), timeZoneOf(child));
        if (minutes === null || minutes === undefined || !(Number(minutes) >= 0)) {
            // Zrusenie ciela = HA uz tablet neriadi: uprac vlastne pravidlo aj
            // extra cas, ktory most doplnal, nech plati len rozvrh appky.
            const had = state.targets && state.targets[cat.base.categoryId];
            delete state.targets[cat.base.categoryId];
            const cleanup = actLimitToday(cat, 1440, dayBit(Date.now(), timeZoneOf(child)));
            if (had && extraTodayMs(cat, today) > 0) {
                cleanup.push({ type: 'SET_CATEGORY_EXTRA_TIME', categoryId: cat.base.categoryId, newExtraTime: 0, day: today });
            }
            if (cleanup.length > 0) {
                log('ciel zruseny: upratujem', cleanup.map((a) => a.type).join(','));
                await pushActions(cleanup);
                await pull();
            }
        } else {
            state.targets = state.targets || {};
            state.targets[cat.base.categoryId] = { day: today, minutes: Math.round(Number(minutes)) };
        }
    }
    saveState();
    await enforceTargets();
}

// Strop plati len na dnes: po polnoci by pravidlo HA s vcerajsim dnom platilo
// o tyzden znova, tak ho most pri synchronizacii zmaze. Zmaze aj zaznamy
// o pravidlach, ktore uz na serveri nie su (zmazane v appke).
async function cleanupHaRules() {
    const actions = [];
    for (const [categoryId, ruleId] of Object.entries(state.haRules || {})) {
        const cat = state.categories[categoryId];
        const rule = cat && (cat.rules || []).find((r) => r.id === ruleId);
        if (!cat || !rule) { delete state.haRules[categoryId]; continue; }
        const child = userById(cat.base.childId);
        const bit = dayBit(Date.now(), timeZoneOf(child));
        if (rule.dayMask !== bit) {
            actions.push({ type: 'DELETE_TIMELIMIT_RULE', ruleId });
            delete state.haRules[categoryId];
        }
    }
    if (actions.length > 0) {
        log('mazem', actions.length, 'stare pravidla HA (strop z ineho dna)');
        await pushActions(actions);
        await pull();
    }
}

async function addChild(name, timeZone) {
    const userId = genId();
    await pushActions([{ type: 'ADD_USER', name, userId, userType: 'child', timeZone: timeZone || 'Europe/Bratislava' }]);
    return userId;
}

async function addCategory(child, title, defaultForUnassigned) {
    const categoryId = genId();
    const actions = [{ type: 'CREATE_CATEGORY', childId: child.id, categoryId, title }];
    if (defaultForUnassigned) actions.push({ type: 'SET_CATEGORY_FOR_UNASSIGNED_APPS', childId: child.id, categoryId });
    await pushActions(actions);
    return categoryId;
}

// ---------------------------------------------------------------- MQTT

let client = null;
const availabilityTopic = BASE + '/bridge/status';

async function mqttConfig() {
    if (options.mqtt_host) {
        return { host: options.mqtt_host, port: options.mqtt_port || 1883, username: options.mqtt_user || undefined, password: options.mqtt_password || undefined };
    }
    if (!SUPERVISOR_TOKEN) throw new Error('bez SUPERVISOR_TOKEN a bez mqtt_host neviem, kam sa pripojit');
    const res = await fetch('http://supervisor/services/mqtt', { headers: { Authorization: 'Bearer ' + SUPERVISOR_TOKEN } });
    if (!res.ok) throw new Error('Supervisor /services/mqtt: HTTP ' + res.status + ' (bezi Mosquitto add-on?)');
    const d = (await res.json()).data;
    return { host: d.host, port: d.port, username: d.username, password: d.password };
}

function pub(topic, payload, retain = true) {
    if (!client) return;
    client.publish(topic, typeof payload === 'string' ? payload : JSON.stringify(payload), { retain, qos: 0 });
}

const bridgeDevice = {
    identifiers: ['timelimit_bridge'],
    name: 'TimeLimit',
    manufacturer: 'timelimit.io',
    model: 'server v1.17.0, HA add-on'
};

function childDevice(child) {
    return {
        identifiers: ['timelimit_child_' + child.id],
        name: 'TimeLimit – ' + child.name,
        manufacturer: 'timelimit.io',
        model: 'dieťa',
        via_device: 'timelimit_bridge'
    };
}

function discover(component, objectId, config) {
    const topic = DISCOVERY_PREFIX + '/' + component + '/' + objectId + '/config';
    const payload = Object.assign({
        unique_id: objectId,
        object_id: objectId,
        availability: [{ topic: availabilityTopic }],
        origin: { name: 'TimeLimit most', sw_version: '1.17.0-8', support_url: 'https://github.com/jakubfabrici/parental-control' }
    }, config);
    pub(topic, payload);
    state.published[topic] = true;
}

function publishDiscovery() {
    const wanted = new Set();
    const mark = (component, objectId) => wanted.add(DISCOVERY_PREFIX + '/' + component + '/' + objectId + '/config');

    // most
    mark('sensor', 'timelimit_most');
    discover('sensor', 'timelimit_most', {
        name: 'Most', icon: 'mdi:bridge', device: bridgeDevice,
        state_topic: BASE + '/bridge/state', value_template: '{{ value_json.state }}',
        json_attributes_topic: BASE + '/bridge/state', entity_category: 'diagnostic'
    });
    mark('button', 'timelimit_sync');
    discover('button', 'timelimit_sync', {
        name: 'Synchronizovať', icon: 'mdi:sync', device: bridgeDevice,
        command_topic: BASE + '/cmd', payload_press: '{"action":"sync"}', entity_category: 'diagnostic'
    });

    // zariadenia
    for (const dev of state.devices) {
        const oid = 'timelimit_device_' + dev.deviceId;
        mark('sensor', oid);
        discover('sensor', oid, {
            name: 'Zariadenie ' + dev.name, icon: 'mdi:cellphone', device: bridgeDevice,
            state_topic: BASE + '/device/' + dev.deviceId + '/state', value_template: '{{ value_json.user }}',
            json_attributes_topic: BASE + '/device/' + dev.deviceId + '/state'
        });
    }

    // deti a ich kategorie
    for (const child of children()) {
        const dev = childDevice(child);
        const t = BASE + '/child/' + child.id;
        const p = 'timelimit_' + child.id + '_';
        mark('sensor', p + 'used');
        discover('sensor', p + 'used', {
            name: 'Použité dnes', icon: 'mdi:timer-sand', device: dev, unit_of_measurement: 'min', state_class: 'measurement',
            state_topic: t + '/state', value_template: '{{ value_json.used_min }}', json_attributes_topic: t + '/state'
        });
        mark('sensor', p + 'remaining');
        discover('sensor', p + 'remaining', {
            name: 'Zostáva dnes', icon: 'mdi:timer-outline', device: dev, unit_of_measurement: 'min', state_class: 'measurement',
            state_topic: t + '/state', value_template: '{{ value_json.remaining_min if value_json.remaining_min is not none else "unknown" }}'
        });
        mark('sensor', p + 'limit_today');
        discover('sensor', p + 'limit_today', {
            name: 'Limit dnes', icon: 'mdi:calendar-clock', device: dev, unit_of_measurement: 'min',
            state_topic: t + '/state', value_template: '{{ value_json.limit_min if value_json.limit_min is not none else "unknown" }}'
        });
        mark('switch', p + 'blocked');
        discover('switch', p + 'blocked', {
            name: 'Zablokované', icon: 'mdi:cellphone-lock', device: dev,
            state_topic: t + '/blocked', command_topic: t + '/blocked/set', payload_on: 'ON', payload_off: 'OFF'
        });
        mark('switch', p + 'no_limits');
        discover('switch', p + 'no_limits', {
            name: 'Bez limitu', icon: 'mdi:timer-off-outline', device: dev,
            state_topic: t + '/no_limits', command_topic: t + '/no_limits/set', payload_on: 'ON', payload_off: 'OFF'
        });
        mark('number', p + 'extra');
        discover('number', p + 'extra', {
            name: 'Extra čas dnes', icon: 'mdi:timer-plus-outline', device: dev, unit_of_measurement: 'min', min: 0, max: 1440, step: 5, mode: 'box',
            state_topic: t + '/extra', command_topic: t + '/extra/set'
        });
        mark('number', p + 'limit');
        discover('number', p + 'limit', {
            name: 'Strop na dnes', icon: 'mdi:timer-lock-outline', device: dev, unit_of_measurement: 'min', min: 0, max: 1440, step: 5, mode: 'box',
            state_topic: t + '/limit', command_topic: t + '/limit/set'
        });

        // vzdy povolene aplikacie
        const apps = appsSummary(child);
        const otherPkgs = Object.values(apps.other_apps).flat().sort();
        mark('sensor', p + 'allowed_apps');
        discover('sensor', p + 'allowed_apps', {
            name: 'Vždy povolené aplikácie', icon: 'mdi:shield-check-outline', device: dev,
            state_topic: t + '/allowed_apps', value_template: '{{ value_json.apps | length }}', json_attributes_topic: t + '/allowed_apps'
        });
        mark('select', p + 'allowed_apps_add');
        discover('select', p + 'allowed_apps_add', {
            name: 'Pridať medzi vždy povolené', icon: 'mdi:shield-plus-outline', device: dev,
            options: [NONE].concat(otherPkgs),
            state_topic: t + '/allowed_apps/add', command_topic: t + '/allowed_apps/add/set'
        });
        mark('select', p + 'allowed_apps_remove');
        discover('select', p + 'allowed_apps_remove', {
            name: 'Odobrať z vždy povolených', icon: 'mdi:shield-remove-outline', device: dev,
            options: [NONE].concat(apps.apps),
            state_topic: t + '/allowed_apps/remove', command_topic: t + '/allowed_apps/remove/set'
        });
        mark('text', p + 'allowed_apps_pkg');
        discover('text', p + 'allowed_apps_pkg', {
            name: 'Pridať balík medzi vždy povolené', icon: 'mdi:package-variant-plus', device: dev,
            min: 0, max: 200, pattern: '^$|^[A-Za-z0-9_.:@-]{3,200}$',
            state_topic: t + '/allowed_apps/pkg', command_topic: t + '/allowed_apps/pkg/set'
        });

        for (const cat of catsOf(child.id)) {
            const cid = cat.base.categoryId;
            const ct = BASE + '/category/' + cid;
            const cp = 'timelimit_' + child.id + '_cat_' + cid + '_';
            const title = cat.base.title;
            mark('sensor', cp + 'used');
            discover('sensor', cp + 'used', {
                name: title + ' – použité dnes', icon: 'mdi:timer-sand', device: dev, unit_of_measurement: 'min', state_class: 'measurement',
                state_topic: ct + '/state', value_template: '{{ value_json.used_min }}', json_attributes_topic: ct + '/state'
            });
            mark('switch', cp + 'blocked');
            discover('switch', cp + 'blocked', {
                name: title + ' – zablokované', icon: 'mdi:lock-outline', device: dev,
                state_topic: ct + '/blocked', command_topic: ct + '/blocked/set', payload_on: 'ON', payload_off: 'OFF'
            });
            mark('number', cp + 'extra');
            discover('number', cp + 'extra', {
                name: title + ' – extra čas dnes', icon: 'mdi:timer-plus-outline', device: dev, unit_of_measurement: 'min', min: 0, max: 1440, step: 5, mode: 'box',
                state_topic: ct + '/extra', command_topic: ct + '/extra/set'
            });
            mark('number', cp + 'limit');
            discover('number', cp + 'limit', {
                name: title + ' – strop na dnes', icon: 'mdi:timer-lock-outline', device: dev, unit_of_measurement: 'min', min: 0, max: 1440, step: 5, mode: 'box',
                state_topic: ct + '/limit', command_topic: ct + '/limit/set'
            });
        }
    }

    // odstran entity, ktore uz nemaju co reprezentovat
    for (const topic of Object.keys(state.published)) {
        if (!wanted.has(topic)) { pub(topic, ''); delete state.published[topic]; }
    }
}

function publishState() {
    const now = Date.now();
    pub(BASE + '/bridge/state', {
        state: state.deviceAuthToken ? 'pripojené' : (parentMail ? 'čaká na rodinu' : 'bez parent_mail'),
        mail: state.mail || parentMail,
        device_id: state.deviceId,
        parent_user_id: state.parentUserId,
        last_sync: state.lastSync ? new Date(state.lastSync).toISOString() : null,
        children: children().map((c) => c.name),
        devices: state.devices.map((d) => d.name),
        categories: Object.keys(state.categories).length,
        ha_rules: Object.keys(state.haRules || {}).length
    });
    for (const dev of state.devices) {
        const u = userById(dev.currentUserId);
        pub(BASE + '/device/' + dev.deviceId + '/state', {
            user: u ? u.name : 'nikto', user_id: dev.currentUserId || '', model: dev.model, name: dev.name,
            device_id: dev.deviceId, app_version: dev.cAppVersion, is_bridge: dev.deviceId === state.deviceId
        });
    }
    for (const child of children()) {
        const s = childSummary(child, now);
        const t = BASE + '/child/' + child.id;
        pub(t + '/state', s);
        pub(t + '/blocked', s.blocked ? 'ON' : 'OFF');
        pub(t + '/no_limits', s.no_limits ? 'ON' : 'OFF');
        pub(t + '/extra', String(s.extra_min));
        pub(t + '/limit', s.limit_min === null ? 'None' : String(s.limit_min));
        pub(t + '/allowed_apps', appsSummary(child));
        pub(t + '/allowed_apps/add', NONE);
        pub(t + '/allowed_apps/remove', NONE);
        pub(t + '/allowed_apps/pkg', '');
        for (const c of s.categories) {
            const ct = BASE + '/category/' + c.id;
            pub(ct + '/state', c);
            pub(ct + '/blocked', c.blocked ? 'ON' : 'OFF');
            pub(ct + '/extra', String(c.extra_min));
            pub(ct + '/limit', c.limit_min === null ? 'None' : String(c.limit_min));
        }
    }
}

// ---------------------------------------------------------------- prikazy

function findChild(ref) {
    if (!ref) return null;
    return children().find((c) => c.id === ref || c.name.toLowerCase() === String(ref).toLowerCase()) || null;
}

function findCategory(ref, child) {
    if (!ref) return null;
    const pool = child ? catsOf(child.id) : Object.values(state.categories);
    return pool.find((c) => c.base.categoryId === ref || c.base.title.toLowerCase() === String(ref).toLowerCase()) || null;
}

async function handleCommand(cmd) {
    const action = cmd.action;
    if (action === 'sync') return;
    if (action === 'enroll') {
        await enroll((cmd.mail || parentMail).toLowerCase());
        return;
    }
    if (action === 'raw') {
        await pushActions(cmd.actions || []);
        return;
    }
    if (action === 'add_child') {
        await addChild(cmd.name, cmd.timeZone);
        return;
    }
    const child = findChild(cmd.child);
    const cat = findCategory(cmd.category, child);
    const target = cat ? [cat] : (child ? limitedTopCatsOf(child.id) : []);
    switch (action) {
        case 'set_total':
            await setTarget(target, cmd.minutes);
            return;
        case 'clear_total':
            await setTarget(target, null);
            return;
        case 'allow_app':
            if (!child) throw new Error('allow_app potrebuje child');
            await addAlwaysAllowed(child, cmd.package);
            return;
        case 'disallow_app':
            if (!child) throw new Error('disallow_app potrebuje child');
            await removeAlwaysAllowed(child, cmd.package);
            return;
        case 'add_category':
            if (!child) throw new Error('add_category potrebuje child');
            await addCategory(child, cmd.title, cmd.default !== false);
            return;
        case 'block':
            if (cat) await setCategoryBlocked(cat, cmd.blocked !== false, cmd.minutes);
            else if (child) await setChildBlocked(child, cmd.blocked !== false, cmd.minutes);
            else throw new Error('block potrebuje child alebo category');
            return;
        case 'unblock':
            if (cat) await setCategoryBlocked(cat, false);
            else if (child) await setChildBlocked(child, false);
            else throw new Error('unblock potrebuje child alebo category');
            return;
        case 'add_time':
            await setExtra(target, Number(cmd.minutes), true);
            return;
        case 'set_extra':
            await setExtra(target, Number(cmd.minutes), false);
            return;
        case 'set_limit':
            await setLimitToday(target, Number(cmd.minutes));
            return;
        case 'no_limits':
            if (!child) throw new Error('no_limits potrebuje child');
            await setNoLimits(child, cmd.on !== false, cmd.minutes);
            return;
        default:
            throw new Error('neznamy prikaz ' + action);
    }
}

async function onMessage(topic, payloadBuf) {
    const payload = payloadBuf.toString().trim();
    try {
        if (topic === BASE + '/cmd') {
            await handleCommand(JSON.parse(payload));
        } else {
            const ma = topic.match(/^timelimit\/child\/([^/]+)\/allowed_apps\/(add|remove|pkg)\/set$/);
            if (ma) {
                const child = findChild(ma[1]);
                if (!child) throw new Error('nezname dieta ' + ma[1]);
                if (payload === '' || payload === NONE) return;
                if (ma[2] === 'remove') await removeAlwaysAllowed(child, payload);
                else await addAlwaysAllowed(child, payload);
                await pull();
                publishDiscovery();
                publishState();
                saveState();
                return;
            }
            const m = topic.match(/^timelimit\/(child|category)\/([^/]+)\/(blocked|no_limits|extra|limit)\/set$/);
            if (!m) return;
            const [, kind, id, key] = m;
            const child = kind === 'child' ? findChild(id) : null;
            const cat = kind === 'category' ? findCategory(id) : null;
            if (kind === 'child' && !child) throw new Error('nezname dieta ' + id);
            if (kind === 'category' && !cat) throw new Error('neznama kategoria ' + id);
            const target = cat ? [cat] : limitedTopCatsOf(child.id);
            const on = /^(ON|true|1)$/i.test(payload);
            if (key === 'blocked') {
                if (cat) await setCategoryBlocked(cat, on); else await setChildBlocked(child, on);
            } else if (key === 'no_limits') {
                await setNoLimits(child, on);
            } else if (key === 'extra') {
                await setExtra(target, Number(payload), false);
            } else if (key === 'limit') {
                await setLimitToday(target, Number(payload));
            }
        }
        await pull();
        publishDiscovery();
        publishState();
        saveState();
    } catch (e) {
        warn('prikaz', topic, payload, 'zlyhal:', e.message);
        pub(BASE + '/bridge/error', { topic, payload, error: e.message, at: new Date().toISOString() }, false);
    }
}

// ---------------------------------------------------------------- hlavna slucka

async function connectMqtt() {
    const cfg = await mqttConfig();
    log('MQTT', cfg.host + ':' + cfg.port, 'ako', cfg.username || '(bez mena)');
    client = mqtt.connect('mqtt://' + cfg.host + ':' + cfg.port, {
        username: cfg.username, password: cfg.password, clientId: 'timelimit-bridge-' + genId(),
        will: { topic: availabilityTopic, payload: 'offline', retain: true }
    });
    client.on('connect', () => {
        pub(availabilityTopic, 'online');
        client.subscribe([BASE + '/cmd', BASE + '/child/+/+/set', BASE + '/category/+/+/set', BASE + '/child/+/allowed_apps/+/set']);
        publishDiscovery();
        publishState();
    });
    client.on('message', (t, p) => { onMessage(t, p); });
    client.on('error', (e) => warn('MQTT:', e.message));
}

async function tick() {
    try {
        if (parentMail && state.mail && state.mail !== parentMail) {
            log('parent_mail sa zmenil z', state.mail, 'na', parentMail, '- prihlasujem znova');
            state.deviceAuthToken = '';
        }
        if (!state.deviceAuthToken) {
            if (!parentMail) { publishState(); return; }
            await enroll(parentMail);
        }
        try {
            await pull();
            await cleanupHaRules();
            await enforceTargets();
        } catch (e) {
            if (e.status === 401) {
                warn('server odmietol token (zariadenie bolo odstranene z rodiny?) - prihlasim sa znova');
                state.deviceAuthToken = '';
                saveState();
            }
            throw e;
        }
        publishDiscovery();
        publishState();
        saveState();
    } catch (e) {
        warn('tick:', e.message);
        publishState();
    }
}

async function main() {
    log('start; server', SERVER, '; rodic', parentMail || '(parent_mail nenastaveny)');
    // pockaj, kym server nabehne
    for (let i = 0; i < 60; i++) {
        try { await getJson(SERVER + '/time'); break; } catch (e) { await sleep(2000); }
    }
    await connectMqtt();
    await tick();
    setInterval(tick, syncInterval);
}

main().catch((e) => { warn('fatal:', e); process.exit(1); });
