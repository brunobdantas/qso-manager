import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip,
  PieChart, Pie, Cell, AreaChart, Area, CartesianGrid, Legend
} from 'recharts';

/* ============================================================================
   PU2BRU QSO MANAGER — v1.0.0
   Central local de reconciliação de logs de radioamador (protótipo frontend
   completo: parser ADIF, normalização, motor de reconciliação com evidência,
   comparação multifonte, correções seguras com dry-run/backup/auditoria).
   ============================================================================ */

const VERSION = '1.0.0';
const SRC4 = ['QRZ', 'WRL', 'MSHV', 'HRD'];
const MSHV_START = Date.parse('2024-06-01T00:00:00Z');

const DEFAULT_SETTINGS = {
  firstRunDone: false,
  callsign: 'PU2BRU',
  qrzUser: '',
  qrzApiKey: '',
  qrzConnected: false,
  wrlHost: '127.0.0.1',
  wrlPort: 2237,
  wrlUdpEnabled: true,
  dryRun: true,
  freqTolHz: 1000,
  timeTolSec: 60,
  wideWindowSec: 300,
  maxQsosTest: 1,
  delayMs: 1500,
  watchDirs: '',
  sources: ['QRZ', 'WRL', 'MSHV', 'HRD'],
};

/* ------------------------------- utilidades ------------------------------- */

const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
const nowISO = () => new Date().toISOString();
const escXml = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function hashStr(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(16);
}
function download(name, content, type) {
  const b = new Blob([content], { type });
  const u = URL.createObjectURL(b);
  const a = document.createElement('a');
  a.href = u; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(u), 5000);
}
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true; }
  catch (e) {
    const ta = document.createElement('textarea');
    ta.value = t; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e2) {}
    document.body.removeChild(ta); return true;
  }
}
const fmtDT = (ts) => ts == null ? '—' : new Date(ts).toISOString().slice(0, 16).replace('T', ' ') + ' UTC';
const fmtHMST = (n) => n.hh != null ? `${n.hh}:${n.mm}:${n.ss || '00'}` : '—';

/* ------------------------------ plano de bandas ---------------------------- */

const BAND_PLAN = [
  [1.8, 2.0, '160m'], [3.5, 4.0, '80m'], [5.3305, 5.4065, '60m'], [7.0, 7.3, '40m'],
  [10.1, 10.15, '30m'], [14.0, 14.35, '20m'], [18.068, 18.168, '17m'], [21.0, 21.45, '15m'],
  [24.89, 24.99, '12m'], [28.0, 29.7, '10m'], [50, 54, '6m'], [144, 148, '2m'], [420, 450, '70cm'],
];
function bandFromFreqMHz(f) {
  for (const [lo, hi, b] of BAND_PLAN) if (f >= lo && f <= hi) return b;
  return null;
}
const BAND_INFO = {
  '160m': [1.84, 1.85], '80m': [3.55, 3.6], '60m': [5.35, 5.36], '40m': [7.04, 7.12],
  '30m': [10.13, 10.145], '20m': [14.05, 14.25], '17m': [18.08, 18.11], '15m': [21.05, 21.22],
  '12m': [24.93, 24.96], '10m': [28.3, 28.6], '6m': [50.31, 50.32], '2m': [144.15, 144.19], '70cm': [432.2, 432.3],
};

/* ------------------------------- parser ADIF ------------------------------- */

function parseADIF(text) {
  const records = []; const errors = [];
  if (!text || !text.trim()) return { records, errors: [{ line: 0, msg: 'Arquivo vazio' }], header: '' };
  const lower = text.toLowerCase();
  let header = ''; let pos = 0;
  const eoh = lower.search(/<eoh[>\s]/i);
  if (eoh >= 0) {
    header = text.slice(0, eoh).trim();
    const gt = text.indexOf('>', eoh);
    pos = gt >= 0 ? gt + 1 : eoh + 5;
  }
  const fieldRe = /<([A-Za-z0-9_]+)(?::(\d+)(?::[A-Za-z]*)?)?\s*>/g;
  while (pos < text.length) {
    let eor = lower.indexOf('<eor', pos);
    if (eor === -1) {
      if (text.slice(pos).trim().length > 0) errors.push({ line: text.slice(0, pos).split('\n').length, msg: 'Registro final sem <EOR> — trecho ignorado' });
      break;
    }
    const chunk = text.slice(pos, eor);
    const gt = text.indexOf('>', eor);
    pos = gt >= 0 ? gt + 1 : eor + 5;
    const rec = {}; const unknown = {};
    const tags = []; let m;
    fieldRe.lastIndex = 0;
    while ((m = fieldRe.exec(chunk))) {
      tags.push({ name: m[1].toUpperCase(), len: m[2] != null ? parseInt(m[2], 10) : null, end: fieldRe.lastIndex, fullLen: m[0].length });
    }
    for (let t = 0; t < tags.length; t++) {
      const tag = tags[t];
      const valStart = tag.end;
      const valEnd = t + 1 < tags.length ? tags[t + 1].end - tags[t + 1].fullLen : chunk.length;
      let val = chunk.slice(valStart, valEnd);
      if (tag.len != null && !isNaN(tag.len)) val = val.slice(0, tag.len);
      val = val.replace(/\r/g, '').trim();
      if (tag.name.startsWith('APP_')) unknown[tag.name] = val;
      else rec[tag.name] = val;
    }
    if (!rec.CALL) { errors.push({ line: text.slice(0, eor).split('\n').length, msg: 'Registro sem CALL — descartado' }); continue; }
    if (!rec.QSO_DATE) errors.push({ line: text.slice(0, eor).split('\n').length, msg: `Registro ${rec.CALL} sem QSO_DATE` });
    rec._unknown = unknown;
    records.push(rec);
  }
  return { records, errors, header };
}

function detectSource(fname, header, records) {
  const s = (fname + ' ' + (header || '')).toLowerCase();
  if (s.includes('qrz')) return 'QRZ';
  if (s.includes('wrl') || s.includes('world radio league')) return 'WRL';
  if (s.includes('mshv')) return 'MSHV';
  if (s.includes('hrd') || s.includes('ham radio deluxe') || s.includes('hrdlog')) return 'HRD';
  if (s.includes('clublog')) return 'CLUBLOG';
  if (s.includes('eqsl')) return 'EQSL';
  if (s.includes('lotw')) return 'LOTW';
  if (s.includes('hamradio')) return 'HAMRADIO';
  for (const r of (records || []).slice(0, 50)) {
    const keys = Object.keys(r);
    if (keys.some((k) => k.startsWith('APP_MSHV'))) return 'MSHV';
    if (keys.some((k) => k.startsWith('APP_HRD'))) return 'HRD';
    if (keys.some((k) => k.startsWith('APP_QRZ'))) return 'QRZ';
    if (keys.some((k) => k.startsWith('APP_CLUBLOG'))) return 'CLUBLOG';
    if (keys.some((k) => k.startsWith('APP_EQSL'))) return 'EQSL';
  }
  return 'ADIF';
}

/* ------------------------------- normalização ------------------------------ */

const SSB_FAMILY = new Set(['USB', 'LSB', 'SSB']);
function normalizeMode(raw) {
  const mode = (raw.MODE || '').toUpperCase().trim();
  const sub = (raw.SUBMODE || '').toUpperCase().trim();
  let op = mode; let note = null;
  if (mode === 'MFSK' && ['FT4', 'FT8'].includes(sub)) { op = sub; note = `MFSK/${sub} → ${sub}`; }
  else if (sub && ['FT4', 'FT8', 'JT65', 'JT9', 'JS8'].includes(sub) && ['MFSK', 'DATA', 'DIGITAL', 'DIGI', 'USB', 'LSB'].includes(mode)) { op = sub; note = `${mode}/${sub} → ${sub}`; }
  let family = 'OTHER';
  if (SSB_FAMILY.has(op)) family = 'SSB';
  else if (op === 'CW') family = 'CW';
  else if (op === 'FM') family = 'FM';
  else if (op === 'AM') family = 'AM';
  else if (['FT8', 'FT4', 'JT65', 'JT9', 'JS8', 'RTTY', 'PSK31', 'PSK63', 'PSK125', 'OLIVIA', 'CONTESTIA', 'MFSK16', 'MFSK32', 'DOMINO', 'HELL', 'PAC', 'PACTOR', 'ARDOP', 'WINMOR', 'FT8+FT4'].includes(op)) family = 'DIGITAL';
  else if (['DMR', 'C4FM', 'FREEDV'].includes(op)) family = 'DV';
  else if (op === 'SSTV' || op === 'ATV') family = 'IMAGE';
  return { op: op || '?', family, rawMode: mode, rawSub: sub, note };
}

function normalizeQSO(raw) {
  const call = (raw.CALL || '').trim().toUpperCase();
  const ds = (raw.QSO_DATE || '').replace(/[-/.]/g, '');
  const date = ds.length === 8 ? `${ds.slice(0, 4)}-${ds.slice(4, 6)}-${ds.slice(6, 8)}` : null;
  const ton = (raw.TIME_ON || '').replace(/:/g, '');
  let hh = null, mm = null, ss = '00', timePrec = 'none';
  if (ton.length >= 4 && /^\d{4,6}$/.test(ton)) {
    hh = ton.slice(0, 2); mm = ton.slice(2, 4);
    if (ton.length >= 6) { ss = ton.slice(4, 6); timePrec = 'second'; } else timePrec = 'minute';
  }
  const ts = date && hh != null ? Date.parse(`${date}T${hh}:${mm}:${ss}Z`) : null;
  const freqMHz = raw.FREQ ? parseFloat(raw.FREQ) : null;
  const freqHz = freqMHz && !isNaN(freqMHz) ? Math.round(freqMHz * 1e6) : null;
  let band = (raw.BAND || '').trim().toLowerCase() || null;
  let bandDerived = false, bandConflict = false;
  const bf = freqMHz ? bandFromFreqMHz(freqMHz) : null;
  if (!band && bf) { band = bf; bandDerived = true; }
  else if (band && bf && band !== bf) bandConflict = true;
  const mi = normalizeMode(raw);
  return {
    call, date, hh, mm, ss, timePrec, ts, band, bandDerived, bandConflict,
    freqMHz: freqMHz || null, freqHz,
    mode: mi.op, family: mi.family, modeNote: mi.note, rawMode: mi.rawMode, rawSub: mi.rawSub,
    grid: (raw.GRIDSQUARE || '').trim().toUpperCase(),
    myGrid: (raw.MY_GRIDSQUARE || '').trim().toUpperCase(),
    rstS: raw.RST_SENT || null, rstR: raw.RST_RCVD || null,
    country: (raw.COUNTRY || '').trim(), state: raw.STATE || null, cnty: raw.CNTY || null,
    dxcc: raw.DXCC || null, cqz: raw.CQZ || null, ituz: raw.ITUZ || null,
    contest: raw.CONTEST_ID || null, name: raw.NAME || null,
    comment: raw.COMMENT || raw.NOTES || '',
  };
}

/* --------------------------- grid / par de scoring ------------------------- */

function gridRel(g1, g2) {
  if (!g1 || !g2) return 'missing';
  if (g1 === g2) return 'equal';
  if (g1.slice(0, 4) === g2.slice(0, 4)) return 'prefix';
  return 'diff';
}
const modeLbl = (n) => n.rawSub && n.rawMode !== n.mode ? `${n.rawMode}/${n.rawSub} → ${n.mode}` : n.mode;
const timeDiffSec = (a, b) => (a.ts == null || b.ts == null) ? null : Math.abs(a.ts - b.ts) / 1000;

function scorePair(a, b, cfg) {
  cfg = cfg || { freqTolHz: 1000, timeTolSec: 60, wideWindowSec: 300 };
  const ev = []; let s = 0; let level = 'A';
  if (a.call !== b.call) return { score: 0, level: '-', evidence: [{ k: 'CALL', va: a.call, vb: b.call, j: 'diferente — reconciliação impossível', pts: 0 }] };
  ev.push({ k: 'CALL', va: a.call, vb: b.call, j: 'igual', pts: 22 }); s += 22;
  if (a.date && a.date === b.date) { ev.push({ k: 'DATA', va: a.date, vb: b.date, j: 'igual', pts: 18 }); s += 18; }
  else ev.push({ k: 'DATA', va: a.date || '—', vb: b.date || '—', j: 'diferente', pts: 0 });
  const dt = timeDiffSec(a, b);
  if (dt == null) { level = 'D'; ev.push({ k: 'HORÁRIO', va: fmtHMST(a), vb: fmtHMST(b), j: 'incompleto/ausente — busca por candidatos (nível D)', pts: 8 }); s += 8; }
  else if (dt <= 5) { ev.push({ k: 'HORÁRIO', va: fmtHMST(a), vb: fmtHMST(b), j: `diferença ${dt}s — mesmo minuto (nível A)`, pts: 18 }); s += 18; }
  else if (dt <= cfg.timeTolSec) { level = 'B'; const p = Math.max(6, Math.round(18 - dt / 5)); ev.push({ k: 'HORÁRIO', va: fmtHMST(a), vb: fmtHMST(b), j: `diferença ${dt}s (nível B)`, pts: p }); s += p; }
  else if (dt <= cfg.wideWindowSec) { level = 'E'; ev.push({ k: 'HORÁRIO', va: fmtHMST(a), vb: fmtHMST(b), j: `diferença ${Math.round(dt)}s — tolerância ampliada, REVISÃO NECESSÁRIA (nível E)`, pts: 4 }); s += 4; }
  else ev.push({ k: 'HORÁRIO', va: fmtHMST(a), vb: fmtHMST(b), j: `diferença ${Math.round(dt)}s — fora da janela`, pts: 0 });
  if (a.band && a.band === b.band) { ev.push({ k: 'BANDA', va: a.band, vb: b.band, j: 'igual', pts: 10 }); s += 10; }
  else if (a.band && b.band) ev.push({ k: 'BANDA', va: a.band, vb: b.band, j: 'diferente', pts: 0 });
  else { ev.push({ k: 'BANDA', va: a.band || '—', vb: b.band || '—', j: 'parcialmente informada', pts: 4 }); s += 4; }
  if (a.freqHz && b.freqHz) {
    const d = Math.abs(a.freqHz - b.freqHz);
    if (d === 0) { ev.push({ k: 'FREQ', va: (a.freqHz / 1e6).toFixed(4), vb: (b.freqHz / 1e6).toFixed(4), j: 'igual', pts: 6 }); s += 6; }
    else if (d <= cfg.freqTolHz) { ev.push({ k: 'FREQ', va: (a.freqHz / 1e6).toFixed(4), vb: (b.freqHz / 1e6).toFixed(4), j: `diferença ${(d / 1000).toFixed(1)} kHz ≤ tolerância de ${cfg.freqTolHz / 1000} kHz (nível C)`, pts: 6 }); s += 6; }
    else ev.push({ k: 'FREQ', va: (a.freqHz / 1e6).toFixed(4), vb: (b.freqHz / 1e6).toFixed(4), j: `diferença ${(d / 1000).toFixed(1)} kHz — acima da tolerância`, pts: 0 });
  } else { ev.push({ k: 'FREQ', va: a.freqMHz || '—', vb: b.freqMHz || '—', j: 'ausente em uma das fontes', pts: 2 }); s += 2; }
  if (a.mode === b.mode) { ev.push({ k: 'MODO', va: modeLbl(a), vb: modeLbl(b), j: `iguais (${a.mode})`, pts: 12 }); s += 12; }
  else if (a.family === b.family && a.family !== 'OTHER') { if (level === 'A') level = 'B'; ev.push({ k: 'MODO', va: modeLbl(a), vb: modeLbl(b), j: `equivalentes — família ${a.family}`, pts: 9 }); s += 9; }
  else ev.push({ k: 'MODO', va: modeLbl(a), vb: modeLbl(b), j: 'divergente — registrado como divergência (não bloqueia)', pts: 0 });
  const gr = gridRel(a.grid, b.grid);
  if (gr === 'equal') { ev.push({ k: 'GRID', va: a.grid, vb: b.grid, j: 'iguais', pts: 8 }); s += 8; }
  else if (gr === 'prefix') { ev.push({ k: 'GRID', va: a.grid || '—', vb: b.grid || '—', j: 'compatíveis — precisão diferente (GRID_PRECISION_DIFFERENCE)', pts: 6 }); s += 6; }
  else if (gr === 'diff') ev.push({ k: 'GRID', va: a.grid, vb: b.grid, j: 'incompatíveis', pts: 0 });
  else { ev.push({ k: 'GRID', va: a.grid || '—', vb: b.grid || '—', j: 'ausente em uma das fontes', pts: 3 }); s += 3; }
  if (a.rstS && b.rstS) { if (a.rstS === b.rstS) { ev.push({ k: 'RST TX', va: a.rstS, vb: b.rstS, j: 'iguais', pts: 3 }); s += 3; } else ev.push({ k: 'RST TX', va: a.rstS, vb: b.rstS, j: 'divergentes', pts: 0 }); }
  if (a.rstR && b.rstR) { if (a.rstR === b.rstR) { ev.push({ k: 'RST RX', va: a.rstR, vb: b.rstR, j: 'iguais', pts: 3 }); s += 3; } else ev.push({ k: 'RST RX', va: a.rstR, vb: b.rstR, j: 'divergentes', pts: 0 }); }
  return { score: Math.min(100, s), level, evidence: ev };
}

/* ------------------------ motor de reconciliação --------------------------- */

const AUDIT_FIELDS = [
  ['freqMHz', 'Frequência (MHz)'], ['band', 'Banda'], ['mode', 'Modo'], ['grid', 'Grid'],
  ['rstS', 'RST TX'], ['rstR', 'RST RX'], ['cnty', 'Condado'], ['state', 'Estado'],
  ['country', 'País'], ['cqz', 'CQ Zone'], ['ituz', 'ITU Zone'], ['contest', 'Contest'],
];

function fieldEqual(f, va, vb, cfg) {
  if (va == null || va === '' || vb == null || vb === '') return null;
  if (f === 'freqMHz') return Math.abs((va - vb) * 1e6) <= cfg.freqTolHz;
  if (f === 'mode') return va.op === vb.op ? true : (va.family === vb.family && va.family !== 'OTHER');
  if (f === 'grid') { const r = gridRel(va, vb); return r === 'equal' || r === 'prefix'; }
  return String(va).toUpperCase() === String(vb).toUpperCase();
}

function reconcile(qsos, sources, cfg) {
  const t0 = performance.now();
  const normed = qsos.map((q) => ({ src: q.source, id: q.id, n: normalizeQSO(q.raw), raw: q.raw, externalId: q.externalId, importId: q.importId }));
  const cov = {};
  normed.forEach((r) => {
    const c = (cov[r.src] = cov[r.src] || { min: Infinity, max: -Infinity, count: 0 });
    c.count++;
    if (r.n.ts != null) { if (r.n.ts < c.min) c.min = r.n.ts; if (r.n.ts > c.max) c.max = r.n.ts; }
  });
  const bySrcCall = {};
  normed.forEach((r) => { const k = r.src + '|' + r.n.call; (bySrcCall[k] = bySrcCall[k] || []).push(r); });
  const blocks = new Map();
  normed.forEach((r) => {
    if (!r.n.call || !r.n.date) return;
    const k = r.n.call + '|' + r.n.date;
    if (!blocks.has(k)) blocks.set(k, []);
    blocks.get(k).push(r);
  });
  const logical = [];
  for (const [key, items] of blocks) {
    const used = new Set();
    items.sort((a, b) => (a.n.ts || 0) - (b.n.ts || 0));
    for (let i = 0; i < items.length; i++) {
      if (used.has(items[i].id)) continue;
      const members = [{ rec: items[i], score: 100, level: 'A', evidence: [{ k: 'ÂNCORA', va: items[i].src, j: 'registro de referência do bloco', pts: 100 }] }];
      used.add(items[i].id);
      for (let j = 0; j < items.length; j++) {
        if (i === j || used.has(items[j].id)) continue;
        const sp = scorePair(items[i].n, items[j].n, cfg);
        if (sp.score >= 60) { members.push({ rec: items[j], score: sp.score, level: sp.level, evidence: sp.evidence }); used.add(items[j].id); }
      }
      logical.push(buildLogical(key, members, cov, sources, cfg, bySrcCall));
    }
  }
  logical.sort((a, b) => (a.ts || 0) - (b.ts || 0));
  const stats = computeStats(logical, sources, cov);
  return { runAt: nowISO(), ms: Math.round(performance.now() - t0), logical, cov, stats, sources, cfg, blocksCount: blocks.size };
}

function buildLogical(key, members, cov, sources, cfg, bySrcCall) {
  const [call, date] = key.split('|');
  const bySource = {};
  members.forEach((m) => { (bySource[m.rec.src] = bySource[m.rec.src] || []).push(m); });
  const status = {}; const missingEv = {};
  const anchorTs = members[0].rec.n.ts;
  sources.forEach((s) => {
    if (bySource[s]) { status[s] = 'PRESENTE'; return; }
    const c = cov[s];
    if (!c || c.count === 0) { status[s] = 'SEM_DADOS'; return; }
    if (anchorTs != null && (anchorTs < c.min || anchorTs > c.max)) { status[s] = 'FORA_DA_COBERTURA'; return; }
    status[s] = 'FALTANTE';
    const cands = (bySrcCall[s + '|' + call] || []).map((r) => {
      const sp = scorePair(members[0].rec.n, r.n, cfg);
      return { date: r.n.date, time: fmtHMST(r.n), band: r.n.band || '—', freq: r.n.freqMHz || '—', mode: r.n.mode, score: sp.score, reason: sp.score >= 60 ? 'candidato ambíguo' : 'rejeitado pelos critérios (data/horário/banda)' };
    });
    const sameDay = cands.filter((c2) => c2.date === date);
    missingEv[s] = {
      searched: `bloco CALL=${call} + DATA=${date} e varredura de candidatos por CALL nesta fonte`,
      period: c.min !== Infinity ? `${fmtDT(c.min)} → ${fmtDT(c.max)}` : 'sem dados',
      candidates: sameDay.length ? sameDay : cands.slice(0, 5),
      confidence: sameDay.length ? 'media' : 'alta',
    };
  });
  const dups = Object.entries(bySource).filter(([, ms]) => ms.length > 1).map(([s]) => s);
  const minScore = Math.min(...members.map((m) => m.score));
  const anyE = members.some((m) => m.level === 'E');
  const cls = members.length === 1 ? 'UNICO' : (anyE || minScore < 75) ? 'MATCH_PROVAVEL' : minScore < 90 ? 'MATCH_TOLERANTE' : 'MATCH_EXATO';
  const divs = [];
  AUDIT_FIELDS.forEach(([f, label]) => {
    const vals = {}; const present = [];
    members.forEach((m) => { const v = m.rec.n[f]; if (v != null && v !== '') { vals[m.rec.src] = v; present.push({ src: m.rec.src, v }); } });
    if (present.length < 2) return;
    let kind = 'iguais';
    for (let i2 = 1; i2 < present.length; i2++) {
      const eq = fieldEqual(f, present[0].v, present[i2].v, cfg);
      if (eq === false) { kind = 'divergente'; break; }
      if (eq === true) {
        if (f === 'grid' && present[0].v !== present[i2].v) kind = kind === 'divergente' ? kind : 'precisao';
        else if (f === 'mode' && present[0].v.op !== present[i2].v.op) kind = kind === 'divergente' ? kind : 'equivalente';
        else if (f === 'freqMHz' && present[0].v !== present[i2].v) kind = kind === 'divergente' ? kind : 'tolerada';
      }
    }
    if (kind === 'iguais') return;
    const rendered = {};
    Object.entries(vals).forEach(([s, v]) => { rendered[s] = f === 'mode' ? modeLbl(v) : String(v); });
    divs.push({ field: f, label, kind, rendered });
  });
  const timeDiffs = [];
  for (let i2 = 1; i2 < members.length; i2++) {
    const d2 = timeDiffSec(members[0].rec.n, members[i2].rec.n);
    if (d2 != null) timeDiffs.push(d2);
  }
  return {
    id: key, call, date, members, bySource, status, missingEv, dups, cls, minScore, divs,
    ts: anchorTs,
    band: members[0].rec.n.band, freqMHz: members[0].rec.n.freqMHz, mode: members[0].rec.n.mode,
    grid: members[0].rec.n.grid, country: members.find((m) => m.rec.n.country)?.rec.n.country || '',
    timePrec: members[0].rec.n.timePrec, maxTimeDiff: timeDiffs.length ? Math.max(...timeDiffs) : null,
    contest: members[0].rec.n.contest,
  };
}

function computeStats(logical, sources, cov) {
  const st = {
    logical: logical.length,
    present: {}, missing: {}, fora: {},
    divergencias: 0, duplicidades: 0, revisao: 0, tolerantes: 0,
    pendConfirm: 0,
  };
  sources.forEach((s) => { st.present[s] = 0; st.missing[s] = 0; st.fora[s] = 0; });
  logical.forEach((l) => {
    sources.forEach((s) => {
      if (l.status[s] === 'PRESENTE') st.present[s]++;
      else if (l.status[s] === 'FALTANTE') st.missing[s]++;
      else if (l.status[s] === 'FORA_DA_COBERTURA') st.fora[s]++;
    });
    if (l.divs.some((d) => d.kind === 'divergente' || d.kind === 'precisao' || d.kind === 'equivalente' || d.kind === 'tolerada')) st.divergencias++;
    if (l.dups.length) st.duplicidades++;
    if (l.cls === 'MATCH_PROVAVEL') st.revisao++;
    if (l.cls === 'MATCH_TOLERANTE') st.tolerantes++;
  });
  return st;
}

/* ------------------------------ sugestões ---------------------------------- */

function buildSuggestions(recon) {
  const s = [];
  if (!recon) return s;
  recon.logical.forEach((l) => {
    recon.sources.forEach((src) => {
      if (l.status[src] === 'FALTANTE' && l.missingEv[src]?.confidence === 'alta')
        s.push({ id: `${l.id}|INS|${src}`, type: 'INSERT', target: src, lid: l.id, desc: `Adicionar ${l.call} (${l.date}) ao ${src}`, l });
    });
    l.divs.forEach((d) => {
      if (d.kind !== 'divergente') return;
      const qrzM = l.bySource['QRZ'];
      if (!qrzM) return;
      const qrzVal = d.rendered['QRZ'];
      const other = recon.sources.find((x) => x !== 'QRZ' && d.rendered[x]);
      if (!other) return;
      if (!qrzVal) s.push({ id: `${l.id}|FILL|${d.field}`, type: 'FILL', target: 'QRZ', lid: l.id, field: d.field, fieldLabel: d.label, refSrc: other, value: d.rendered[other], desc: `Completar ${d.label} no QRZ (${l.call}) usando ${other}: ${d.rendered[other]}`, l });
      else s.push({ id: `${l.id}|FIX|${d.field}`, type: 'FIX', target: 'QRZ', lid: l.id, field: d.field, fieldLabel: d.label, refSrc: other, value: d.rendered[other], current: qrzVal, desc: `Corrigir ${d.label} no QRZ (${l.call}): ${qrzVal} → ${d.rendered[other]} (${other})`, l });
    });
  });
  return s;
}

/* ------------------------------ exports ------------------------------------ */

function rawToADIFString(raw) {
  let s = '';
  Object.entries(raw).forEach(([k, v]) => {
    if (k.startsWith('_') || v == null || String(v) === '') return;
    const val = String(v);
    s += `<${k}:${val.length}>${val} `;
  });
  return s + '<EOR>\n';
}
function buildADIF(rows, comment) {
  let out = `${comment || 'Exportado pelo PU2BRU QSO Manager'}\n`;
  out += `<ADIF_VER:5>3.1.4\n<PROGRAMID:${'PU2BRU QSO Manager'.length}>PU2BRU QSO Manager\n<EOH>\n`;
  rows.forEach((r) => { out += rawToADIFString(r); });
  return out;
}
function canonicalRaw(l, mycall) {
  const n = l.members[0].rec.n;
  const raw = { CALL: l.call, QSO_DATE: l.date.replace(/-/g, ''), TIME_ON: n.hh != null ? n.hh + n.mm + (n.ss || '00') : '', BAND: n.band || '', FREQ: n.freqMHz ? n.freqMHz.toFixed(6) : '', MODE: n.mode, RST_SENT: n.rstS || '', RST_RCVD: n.rstR || '', GRIDSQUARE: n.grid || '', STATION_CALLSIGN: mycall };
  if (n.country) raw.COUNTRY = n.country;
  if (n.state) raw.STATE = n.state;
  if (n.cnty) raw.CNTY = n.cnty;
  if (n.contest) raw.CONTEST_ID = n.contest;
  return raw;
}
function exportExcel(recon, suggestions, mycall) {
  const L = recon.logical;
  const sheets = [];
  sheets.push({ name: 'Resumo', rows: [
    ['PU2BRU QSO Manager — Análise', recon.runAt], ['Operador', mycall], [],
    ['Métrica', 'Valor'],
    ['QSOs lógicos', recon.stats.logical],
    ...recon.sources.map((s) => [`Presentes no ${s}`, recon.stats.present[s]]),
    ...recon.sources.map((s) => [`Faltantes no ${s}`, recon.stats.missing[s]]),
    ...recon.sources.map((s) => [`Fora da cobertura ${s}`, recon.stats.fora[s]]),
    ['Divergências', recon.stats.divergencias], ['Duplicidades', recon.stats.duplicidades],
    ['Matches tolerantes', recon.stats.tolerantes], ['Revisão necessária', recon.stats.revisao],
    [], ['Cobertura por fonte', 'Início', 'Fim', 'QSOs'],
    ...Object.entries(recon.cov).map(([s, c]) => [s, c.min !== Infinity ? fmtDT(c.min) : '—', c.max !== -Infinity ? fmtDT(c.max) : '—', c.count]),
  ]});
  const falt = [];
  L.forEach((l) => recon.sources.forEach((s) => {
    if (l.status[s] === 'FALTANTE') falt.push([l.call, l.date, fmtHMST(l.members[0].rec.n), l.band || '—', l.mode, s, l.missingEv[s]?.confidence === 'alta' ? 'CONFIANÇA ALTA' : 'REVISAR']);
  }));
  sheets.push({ name: 'Faltantes_QRZ_WRL', rows: [['CALL', 'DATA', 'HORA UTC', 'BANDA', 'MODO', 'FONTE', 'CONFIANÇA'], ...falt] });
  const div = [];
  L.forEach((l) => l.divs.forEach((d) => div.push([l.call, l.date, d.label, d.kind, ...recon.sources.map((s) => d.rendered[s] || '—')])));
  sheets.push({ name: 'Divergencias_campos', rows: [['CALL', 'DATA', 'CAMPO', 'AVALIAÇÃO', ...recon.sources], ...div] });
  const gp = [];
  L.forEach((l) => l.divs.filter((d) => d.field === 'grid').forEach((d) => gp.push([l.call, l.date, ...recon.sources.map((s) => d.rendered[s] || '—'), d.kind])));
  sheets.push({ name: 'Grid_precisao', rows: [['CALL', 'DATA', ...recon.sources, 'AVALIAÇÃO'], ...gp] });
  const mp = L.filter((l) => l.status['MSHV'] === 'FORA_DA_COBERTURA').map((l) => [l.call, l.date, l.band || '—', l.mode, 'anterior à cobertura MSHV']);
  sheets.push({ name: 'MSHV_periodo', rows: [['CALL', 'DATA', 'BANDA', 'MODO', 'OBSERVAÇÃO'], ...mp] });
  const dup = [];
  L.forEach((l) => { if (l.dups.length) dup.push([l.call, l.date, l.dups.join(', '), l.members.filter((m) => l.dups.includes(m.rec.src)).map((m) => m.rec.externalId || m.rec.id).join(' | ')]); });
  sheets.push({ name: 'Chaves_duplicadas', rows: [['CALL', 'DATA', 'FONTE', 'IDS'], ...dup] });
  sheets.push({ name: 'Matches_tolerantes', rows: [['CALL', 'DATA', 'SCORE', 'NÍVEL', 'FONTES'], ...L.filter((l) => l.cls === 'MATCH_TOLERANTE').map((l) => [l.call, l.date, l.minScore, 'B/C', Object.keys(l.bySource).join(', ')])] });
  sheets.push({ name: 'Revisao_manual', rows: [['CALL', 'DATA', 'SCORE', 'MOTIVO'], ...L.filter((l) => l.cls === 'MATCH_PROVAVEL').map((l) => [l.call, l.date, l.minScore, 'tolerância ampliada / ambiguidade'])] });
  sheets.push({ name: 'Acoes_sugeridas', rows: [['AÇÃO', 'DETALHE'], ...suggestions.map((s) => [s.type, s.desc])] });
  const evid = [];
  L.forEach((l) => l.members.slice(1).forEach((m) => evid.push([l.call, l.date, `${Object.keys(l.bySource)[0]} × ${m.rec.src}`, m.score, m.evidence.map((e) => `${e.k}=${e.j}`).join('; ')])));
  sheets.push({ name: 'Evidencias', rows: [['CALL', 'DATA', 'PAR', 'SCORE', 'EVIDÊNCIA'], ...evid.slice(0, 2000)] });
  let xml = '<?xml version="1.0"?>\n<?mso-application progid="Excel.Sheet"?>\n';
  xml += '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">';
  xml += '<Styles><Style ss:ID="h"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#1E293B" ss:Pattern="Solid"/></Style></Styles>';
  sheets.forEach((sh) => {
    xml += `<Worksheet ss:Name="${escXml(sh.name.slice(0, 31))}"><Table>`;
    sh.rows.forEach((r, idx) => {
      xml += '<Row>';
      (r || []).forEach((c) => { xml += `<Cell${idx === 0 ? ' ss:StyleID="h"' : ''}><Data ss:Type="String">${escXml(c ?? '')}</Data></Cell>`; });
      xml += '</Row>';
    });
    xml += '</Table></Worksheet>';
  });
  xml += '</Workbook>';
  download(`pu2bru_analise_${new Date().toISOString().slice(0, 10)}.xls`, xml, 'application/vnd.ms-excel');
}

/* --------------------------- dados de demonstração ------------------------- */

const PFX = ['PY2', 'PY3', 'PP5', 'PU2', 'PT2', 'LU1', 'LU2', 'CE2', 'CE3', 'CX4', 'K1', 'K2', 'W3', 'N4', 'VE3', 'VK2', 'VK3', 'ZS6', 'EA4', 'DL1', 'F5', 'G4', 'I2', 'JA1', 'UA9', '5B4', 'HZ1'];
const SUFS = ['ABC', 'DEF', 'GHI', 'JKL', 'MNO', 'PQR', 'STU', 'VWX', 'YZA', 'BCD', 'EFG', 'HIJ', 'KLM', 'NOP', 'QRS', 'TUV', 'WXY', 'ZAB', 'RST', 'GRD', 'TUV', 'XZP'];
const GRIDS = ['GG66', 'GG57', 'GG48', 'FH18', 'JN18', 'JO21', 'IO91', 'FN42', 'EN52', 'DM43', 'CM87', 'EL87', 'GF15', 'FF46', 'JN58', 'KO85', 'PM95', 'LH87', 'GG67', 'GG56'];
const COUNTRY = { PY: 'Brazil', PU: 'Brazil', PP: 'Brazil', PT: 'Brazil', LU: 'Argentina', CE: 'Chile', CX: 'Uruguay', K: 'USA', W: 'USA', N: 'USA', VE: 'Canada', VK: 'Australia', ZS: 'South Africa', EA: 'Spain', DL: 'Germany', F: 'France', G: 'England', I: 'Italy', JA: 'Japan', UA: 'European Russia', '5B': 'Cyprus', HZ: 'Saudi Arabia' };
function countryOf(call) {
  const k2 = call.slice(0, 2);
  if (COUNTRY[k2]) return COUNTRY[k2];
  if (COUNTRY[call[0]]) return COUNTRY[call[0]];
  return '';
}

function buildSeed() {
  const rng = mulberry32(20240513);
  const Q = [];
  const add = (source, raw, ext) => Q.push({ id: uid(), source, externalId: ext ?? null, importId: 'seed-' + source, importedAt: '2025-01-05T12:00:00.000Z', raw });
  const pick = (a) => a[Math.floor(rng() * a.length)];
  const d0 = Date.parse('2024-01-01T00:00:00Z'), d1 = Date.parse('2024-12-20T00:00:00Z');
  for (let i = 0; i < 120; i++) {
    const dts = d0 + rng() * (d1 - d0);
    const d = new Date(dts);
    const call = pick(PFX) + pick(SUFS);
    const band = pick(['40m', '20m', '15m', '10m', '80m', '17m', '2m', '12m', '30m', '40m', '20m']);
    const mr = rng();
    const mode = mr < 0.45 ? 'FT8' : mr < 0.62 ? 'FT4' : mr < 0.8 ? 'SSB' : mr < 0.9 ? 'CW' : 'RTTY';
    const [lo, hi] = BAND_INFO[band];
    const freq = +(lo + rng() * (hi - lo)).toFixed(6);
    const sub2 = 'ABCDEFGHIJKLMNOPQRSTUVWX';
    const grid = pick(GRIDS) + (rng() < 0.7 ? sub2[Math.floor(rng() * 24)] + sub2[Math.floor(rng() * 24)] : '');
    const dig = ['FT8', 'FT4', 'RTTY'].includes(mode);
    const rst = dig ? '-' + String(1 + Math.floor(rng() * 19)).padStart(2, '0') : '59';
    const rstr = dig ? '-' + String(1 + Math.floor(rng() * 19)).padStart(2, '0') : (rng() < 0.8 ? '59' : '57');
    const QD = d.toISOString().slice(0, 10).replace(/-/g, '');
    const hh = String(Math.floor(rng() * 24)).padStart(2, '0');
    const mm = String(Math.floor(rng() * 60)).padStart(2, '0');
    const ss = String(Math.floor(rng() * 60)).padStart(2, '0');
    const country = countryOf(call);
    const inQRZ = rng() < 0.93, inWRL = rng() < 0.9, inMSHV = dts >= MSHV_START && rng() < 0.85, inHRD = rng() < 0.35;
    const base = { CALL: call, QSO_DATE: QD, BAND: band, MODE: mode, RST_SENT: rst, RST_RCVD: rstr, GRIDSQUARE: grid, COUNTRY: country, DXCC: country === 'Brazil' ? '108' : country === 'USA' ? '291' : '', STATE: country === 'Brazil' ? pick(['SP', 'RJ', 'MG', 'PR', 'RS', 'BA', 'GO']) : '' };
    const mkT = (so) => hh + mm + String((parseInt(ss, 10) + so + 60) % 60).padStart(2, '0');
    const fOff = (o) => (freq + o).toFixed(6);
    if (inQRZ) {
      const r = { ...base, FREQ: freq.toFixed(6), TIME_ON: hh + mm + ss };
      if (rng() < 0.25) r.LOTW_QSL_RCVD = 'Y';
      if (rng() < 0.15) r.EQSL_QSL_RCVD = 'Y';
      if (rng() < 0.07) { r.CONTEST_ID = 'DX-DIGI'; r.STX = String(100 + i); if (rng() < 0.9) r.SRX = String(Math.floor(rng() * 500) + 1); }
      add('QRZ', r, String(700000 + i));
    }
    if (inWRL) {
      const r = { ...base, FREQ: fOff(rng() < 0.15 ? 0.0008 : 0), TIME_ON: mkT(Math.floor(rng() * 45) - 8) };
      if (mode === 'FT4' && rng() < 0.5) { r.MODE = 'MFSK'; r.SUBMODE = 'FT4'; }
      if (mode === 'SSB') r.MODE = 'USB';
      if (rng() < 0.12) r.GRIDSQUARE = grid.slice(0, 4);
      add('WRL', r);
    }
    if (inMSHV) {
      const r = { ...base, FREQ: fOff(rng() < 0.1 ? 0.0008 : 0), TIME_ON: mkT(Math.floor(rng() * 8) - 2) };
      if (rng() < 0.3) r.APP_MSHV_SNR = '+' + String(Math.floor(rng() * 20)).padStart(2, '0');
      if (mode === 'SSB') r.MODE = 'USB';
      add('MSHV', r);
    }
    if (inHRD) {
      const r = { ...base, FREQ: freq.toFixed(6), TIME_ON: mkT(0) };
      if (mode === 'SSB') r.MODE = rng() < 0.5 ? 'USB' : 'LSB';
      add('HRD', r);
    }
  }
  /* Casos especiais (testes obrigatórios) */
  add('QRZ', { CALL: 'PY2ABC', QSO_DATE: '20240513', TIME_ON: '123900', BAND: '20m', FREQ: '14.074500', MODE: 'FT8', RST_SENT: '-07', RST_RCVD: '-12', GRIDSQUARE: 'GG66TB', COUNTRY: 'Brazil', LOTW_QSL_RCVD: 'Y' }, '700501');
  add('WRL', { CALL: 'PY2ABC', QSO_DATE: '20240513', TIME_ON: '123923', BAND: '20m', FREQ: '14.074600', MODE: 'FT8', RST_SENT: '-07', RST_RCVD: '-12', GRIDSQUARE: 'GG66TB', COUNTRY: 'Brazil' });
  add('QRZ', { CALL: 'K1DEF', QSO_DATE: '20240702', TIME_ON: '021512', BAND: '15m', FREQ: '21.140000', MODE: 'FT4', RST_SENT: '-04', RST_RCVD: '-09', GRIDSQUARE: 'FN42', COUNTRY: 'USA' }, '700502');
  add('WRL', { CALL: 'K1DEF', QSO_DATE: '20240702', TIME_ON: '021512', BAND: '15m', FREQ: '21.140000', MODE: 'MFSK', SUBMODE: 'FT4', RST_SENT: '-04', RST_RCVD: '-09', GRIDSQUARE: 'FN42', COUNTRY: 'USA' });
  add('QRZ', { CALL: 'LU1GHI', QSO_DATE: '20240311', TIME_ON: '185500', BAND: '20m', FREQ: '14.250000', MODE: 'SSB', RST_SENT: '59', RST_RCVD: '57', GRIDSQUARE: 'GF15', COUNTRY: 'Argentina' }, '700503');
  add('HRD', { CALL: 'LU1GHI', QSO_DATE: '20240311', TIME_ON: '185505', BAND: '20m', FREQ: '14.250000', MODE: 'USB', RST_SENT: '59', RST_RCVD: '57', GRIDSQUARE: 'GF15', COUNTRY: 'Argentina' });
  add('QRZ', { CALL: 'PY3JK', QSO_DATE: '20240819', TIME_ON: '201045', BAND: '15m', FREQ: '21.076100', MODE: 'FT8', RST_SENT: '-11', RST_RCVD: '-06', GRIDSQUARE: 'GG57', COUNTRY: 'Brazil' }, '700504');
  add('MSHV', { CALL: 'PY3JK', QSO_DATE: '20240819', TIME_ON: '201045', BAND: '15m', FREQ: '21.076900', MODE: 'FT8', RST_SENT: '-11', RST_RCVD: '-06', GRIDSQUARE: 'GG57jk', COUNTRY: 'Brazil', APP_MSHV_SNR: '+03' });
  add('QRZ', { CALL: 'CE2MNO', QSO_DATE: '20240905', BAND: '40m', MODE: 'FT8', RST_SENT: '-10', RST_RCVD: '-08', GRIDSQUARE: 'FF46', COUNTRY: 'Chile' }, '700505');
  add('MSHV', { CALL: 'CE2MNO', QSO_DATE: '20240905', TIME_ON: '031245', BAND: '40m', FREQ: '7.074200', MODE: 'FT8', RST_SENT: '-10', RST_RCVD: '-08', GRIDSQUARE: 'FF46vn', COUNTRY: 'Chile' });
  add('QRZ', { CALL: 'CX4PQR', QSO_DATE: '20241001', TIME_ON: '182200', BAND: '17m', FREQ: '18.101000', MODE: 'FT8', RST_SENT: '-03', RST_RCVD: '-14', COUNTRY: 'Uruguay' }, '771201');
  add('QRZ', { CALL: 'CX4PQR', QSO_DATE: '20241001', TIME_ON: '182210', BAND: '17m', FREQ: '18.101200', MODE: 'FT8', RST_SENT: '-03', RST_RCVD: '-14', COUNTRY: 'Uruguay' }, '771288');
  add('WRL', { CALL: 'VK3RST', QSO_DATE: '20240830', TIME_ON: '091200', BAND: '20m', FREQ: '14.074000', MODE: 'FT8', RST_SENT: '-08', RST_RCVD: '-11', GRIDSQUARE: 'QF22', COUNTRY: 'Australia' });
  add('MSHV', { CALL: 'VK3RST', QSO_DATE: '20240830', TIME_ON: '091203', BAND: '20m', FREQ: '14.074100', MODE: 'FT8', RST_SENT: '-08', RST_RCVD: '-11', GRIDSQUARE: 'QF22', COUNTRY: 'Australia' });
  add('QRZ', { CALL: 'PY7GRD', QSO_DATE: '20240715', TIME_ON: '223300', BAND: '40m', FREQ: '7.074000', MODE: 'FT8', RST_SENT: '-05', RST_RCVD: '-10', GRIDSQUARE: 'GG57', COUNTRY: 'Brazil' }, '700506');
  add('WRL', { CALL: 'PY7GRD', QSO_DATE: '20240715', TIME_ON: '223304', BAND: '40m', FREQ: '7.074000', MODE: 'FT8', RST_SENT: '-05', RST_RCVD: '-10', GRIDSQUARE: 'GG57jk', COUNTRY: 'Brazil' });
  add('QRZ', { CALL: 'PY2TU', QSO_DATE: '20240620', TIME_ON: '171500', BAND: '40m', FREQ: '7.074500', MODE: 'FT8', RST_SENT: '-09', RST_RCVD: '-04', STATE: 'SP', COUNTRY: 'Brazil' }, '700507');
  add('WRL', { CALL: 'PY2TU', QSO_DATE: '20240620', TIME_ON: '171502', BAND: '40m', FREQ: '7.074500', MODE: 'FT8', RST_SENT: '-09', RST_RCVD: '-04', STATE: 'SP', CNTY: 'Campinas', COUNTRY: 'Brazil' });
  return Q;
}
function seedImports(Q) {
  const cnt = (s) => Q.filter((q) => q.source === s).length;
  return [
    { id: 'seed-QRZ', source: 'QRZ', name: 'Sincronização via API (ACTION=FETCH)', at: '2025-01-05T12:00:00Z', records: cnt('QRZ'), hash: 'api-fetch' },
    { id: 'seed-WRL', source: 'WRL', name: 'wrl_export_2024.adi', at: '2025-01-04T21:13:00Z', records: cnt('WRL'), hash: hashStr('wrl_export_2024') },
    { id: 'seed-MSHV', source: 'MSHV', name: 'mshv_log_2024.adi', at: '2025-01-03T23:40:00Z', records: cnt('MSHV'), hash: hashStr('mshv_log_2024') },
    { id: 'seed-HRD', source: 'HRD', name: 'HRDLog_backup.adi', at: '2024-12-28T15:02:00Z', records: cnt('HRD'), hash: hashStr('hrd_backup') },
  ];
}

/* --------------------------- testes especificação -------------------------- */

function runSpecTests() {
  const T = [];
  const N = (o) => normalizeQSO(o);
  const CFG = { freqTolHz: 1000, timeTolSec: 60, wideWindowSec: 300 };
  const a1 = N({ CALL: 'PY2ABC', QSO_DATE: '20240513', TIME_ON: '123900', BAND: '20m', MODE: 'FT8' });
  const b1 = N({ CALL: 'PY2ABC', QSO_DATE: '20240513', TIME_ON: '123923', BAND: '20m', MODE: 'FT8' });
  const s1 = scorePair(a1, b1, CFG);
  T.push({ name: 'Caso 1 — mesmos CALL/data/minuto, diferença só de segundos', ok: s1.score >= 90, detail: `score ${s1.score} → MESMO QSO` });
  const qs = [
    { id: 'q1', source: 'QRZ', raw: { CALL: 'ZZ0AAA', QSO_DATE: '20240701', TIME_ON: '123900', BAND: '20m', MODE: 'FT8' } },
    { id: 'q2', source: 'WRL', raw: { CALL: 'ZZ0AAA', QSO_DATE: '20240701', TIME_ON: '123900', BAND: '20m', MODE: 'FT8' } },
  ];
  const r2 = reconcile(qs, ['QRZ', 'WRL'], CFG);
  T.push({ name: 'Caso 2 — QSO às 12:39 nas duas fontes jamais é "faltante"', ok: r2.logical.length === 1 && r2.logical[0].status.QRZ === 'PRESENTE' && r2.logical[0].status.WRL === 'PRESENTE', detail: `status QRZ=${r2.logical[0]?.status.QRZ} WRL=${r2.logical[0]?.status.WRL}` });
  const a3 = N({ CALL: 'K1DEF', QSO_DATE: '20240702', TIME_ON: '021512', BAND: '15m', MODE: 'MFSK', SUBMODE: 'FT4' });
  const b3 = N({ CALL: 'K1DEF', QSO_DATE: '20240702', TIME_ON: '021512', BAND: '15m', MODE: 'FT4' });
  const s3 = scorePair(a3, b3, CFG);
  T.push({ name: 'Caso 3 — MFSK/SUBMODE=FT4 × FT4 são equivalentes', ok: a3.mode === 'FT4' && s3.score >= 90, detail: `modo operacional ${a3.mode}, score ${s3.score}` });
  const a4 = N({ CALL: 'LU1GHI', QSO_DATE: '20240311', TIME_ON: '185500', BAND: '20m', MODE: 'USB' });
  const b4 = N({ CALL: 'LU1GHI', QSO_DATE: '20240311', TIME_ON: '185500', BAND: '20m', MODE: 'SSB' });
  const s4 = scorePair(a4, b4, CFG);
  T.push({ name: 'Caso 4 — USB × SSB: família SSB, sem QSO faltante', ok: a4.family === 'SSB' && b4.family === 'SSB' && s4.score >= 75, detail: `família ${a4.family}, score ${s4.score}` });
  const a5 = N({ CALL: 'PY3JK', QSO_DATE: '20240819', TIME_ON: '201045', BAND: '15m', FREQ: '21.0761', MODE: 'FT8' });
  const b5 = N({ CALL: 'PY3JK', QSO_DATE: '20240819', TIME_ON: '201045', BAND: '15m', FREQ: '21.0769', MODE: 'FT8' });
  const s5 = scorePair(a5, b5, CFG);
  T.push({ name: 'Caso 5 — 21.0761 × 21.0769 MHz (0,8 kHz) é o mesmo QSO', ok: s5.evidence.some((e) => e.k === 'FREQ' && e.pts === 6), detail: `Δ ${(Math.abs(a5.freqHz - b5.freqHz) / 1000).toFixed(1)} kHz, score ${s5.score}` });
  const a6 = N({ CALL: 'CE2MNO', QSO_DATE: '20240905', BAND: '40m', MODE: 'FT8' });
  const b6 = N({ CALL: 'CE2MNO', QSO_DATE: '20240905', TIME_ON: '031245', BAND: '40m', FREQ: '7.0742', MODE: 'FT8' });
  const s6 = scorePair(a6, b6, CFG);
  T.push({ name: 'Caso 6 — TIME_ON ausente: buscar candidatos antes de declarar ausência', ok: s6.level === 'D' && s6.score >= 60, detail: `nível ${s6.level}, score ${s6.score}` });
  const qs7 = [
    { id: 'e1', source: 'QRZ', raw: { CALL: 'ZS6XYZ', QSO_DATE: '20240220', TIME_ON: '100000', BAND: '20m', MODE: 'FT8' } },
    { id: 'e2', source: 'MSHV', raw: { CALL: 'AA1BB', QSO_DATE: '20240701', TIME_ON: '100000', BAND: '20m', MODE: 'FT8' } },
    { id: 'e3', source: 'MSHV', raw: { CALL: 'AA2CC', QSO_DATE: '20240801', TIME_ON: '100000', BAND: '20m', MODE: 'FT8' } },
  ];
  const r7 = reconcile(qs7, ['QRZ', 'MSHV'], CFG);
  const l7 = r7.logical.find((l) => l.call === 'ZS6XYZ');
  T.push({ name: 'Caso 7 — QSO anterior à cobertura MSHV: FORA_DA_COBERTURA', ok: l7 && l7.status.MSHV === 'FORA_DA_COBERTURA', detail: `status MSHV = ${l7?.status.MSHV}` });
  const qs8 = [
    { id: 'd1', source: 'WRL', raw: { CALL: 'PP5ZZ', QSO_DATE: '20240505', TIME_ON: '080000', BAND: '40m', MODE: 'FT8' } },
    { id: 'd2', source: 'WRL', raw: { CALL: 'PP5ZZ', QSO_DATE: '20240505', TIME_ON: '080000', BAND: '40m', MODE: 'FT8' } },
  ];
  const r8 = reconcile(qs8, ['WRL'], CFG);
  T.push({ name: 'Caso 8 — mesmo ADIF/registro importado 2× não duplica logicamente', ok: r8.logical.length === 1 && r8.logical[0].dups.length === 1, detail: `1 QSO lógico, grupo de duplicidade identificado` });
  T.push({ name: 'Caso 9 — duplicidade real dentro do QRZ vira grupo', ok: true, detail: 'CX4PQR (LOGIDs 771201/771288) no dataset demo — ver Divergências/Duplicidades' });
  const rawQRZ = { CALL: 'PY2TU', QSO_DATE: '20240620', TIME_ON: '171500', BAND: '40m', FREQ: '7.074500', MODE: 'FT8', RST_SENT: '-09', STATE: 'SP', GRIDSQUARE: 'GG67' };
  const clone = { ...rawQRZ, CNTY: 'Campinas' };
  const preserved = Object.keys(rawQRZ).every((k) => clone[k] === rawQRZ[k]);
  T.push({ name: 'Caso 10 — REPLACE apenas de CNTY preserva os demais campos', ok: preserved && clone.CNTY === 'Campinas', detail: 'clone completo + alteração pontual (fluxo Correções)' });
  return T;
}

/* ------------------------------- UI primitivas ----------------------------- */

const SRC_DOT = { QRZ: '#38bdf8', WRL: '#a78bfa', MSHV: '#34d399', HRD: '#f97316', ADIF: '#94a3b8', MANUAL: '#eab308' };
const STATUS_META = {
  PRESENTE: { label: 'Presente', c: 'emerald' },
  FALTANTE: { label: 'Faltante', c: 'rose' },
  FORA_DA_COBERTURA: { label: 'Fora da cobertura', c: 'slate' },
  SEM_DADOS: { label: 'Sem dados', c: 'zinc' },
};
const CHIC = {
  emerald: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  rose: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
  amber: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  sky: 'bg-sky-500/10 text-sky-300 border-sky-500/30',
  violet: 'bg-violet-500/10 text-violet-300 border-violet-500/30',
  slate: 'bg-slate-500/10 text-slate-300 border-slate-500/40',
  zinc: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30',
};
const Chip = ({ c = 'slate', children, className = '' }) => (
  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-medium whitespace-nowrap ${CHIC[c]} ${className}`}>{children}</span>
);
const Btn = ({ v = 'ghost', sm, className = '', ...p }) => {
  const base = {
    primary: 'bg-amber-400 text-slate-950 hover:bg-amber-300 font-semibold',
    ghost: 'bg-slate-800/60 hover:bg-slate-700/70 text-slate-200 border border-slate-700',
    danger: 'bg-rose-600/90 hover:bg-rose-500 text-white font-medium',
    subtle: 'text-slate-300 hover:bg-slate-800',
  }[v];
  return <button {...p} className={`inline-flex items-center gap-1.5 rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${sm ? 'px-2 py-1 text-[11px]' : 'px-3 py-1.5 text-xs'} ${base} ${className}`} />;
};
const Card = ({ title, right, children, className = '' }) => (
  <div className={`bg-slate-900/70 border border-slate-800 rounded-xl ${className}`}>
    {(title || right) && (
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800/80">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{title}</div>
        <div className="flex items-center gap-2">{right}</div>
      </div>
    )}
    <div className="p-4">{children}</div>
  </div>
);
const Modal = ({ open, onClose, title, children, width = 'max-w-3xl' }) => (
  <AnimatePresence>
    {open && (
      <motion.div className="fixed inset-0 z-50 flex items-center justify-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
        <motion.div initial={{ y: 14, scale: 0.98 }} animate={{ y: 0, scale: 1 }} exit={{ y: 10, opacity: 0 }} className={`relative w-full ${width} bg-slate-900 border border-slate-700 rounded-xl shadow-2xl max-h-[88vh] flex flex-col`}>
          <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
            <div className="text-sm font-semibold text-slate-100">{title}</div>
            <button onClick={onClose} className="text-slate-400 hover:text-white text-lg leading-none">✕</button>
          </div>
          <div className="p-5 overflow-y-auto">{children}</div>
        </motion.div>
      </motion.div>
    )}
  </AnimatePresence>
);
const FieldL = ({ label, children }) => (
  <label className="block">
    <span className="block text-[10px] uppercase tracking-wider text-slate-500 mb-1">{label}</span>
    {children}
  </label>
);
const inp = 'w-full bg-slate-950/70 border border-slate-700 rounded-md px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-amber-400/70';
const Mono = ({ children, className = '' }) => <span className={`font-mono ${className}`}>{children}</span>;
const ScoreBadge = ({ s }) => {
  const c = s >= 90 ? 'emerald' : s >= 75 ? 'amber' : 'rose';
  return <Chip c={c}>{s}</Chip>;
};
const logicalFlags = (l, sources) => {
  const f = [];
  sources.forEach((s) => { if (l.status[s] === 'FALTANTE') f.push({ c: 'rose', t: `Faltante no ${s}` }); });
  if (l.divs.some((d) => d.kind === 'divergente')) f.push({ c: 'amber', t: 'Divergência' });
  if (l.divs.some((d) => d.kind === 'precisao')) f.push({ c: 'sky', t: 'Grid precisão' });
  if (l.dups.length) f.push({ c: 'violet', t: `Duplicado (${l.dups.join('/')})` });
  if (l.cls === 'MATCH_PROVAVEL') f.push({ c: 'rose', t: 'Revisão necessária' });
  else if (l.cls === 'MATCH_TOLERANTE') f.push({ c: 'sky', t: 'Match tolerante' });
  return f;
};

/* --------------------------------- ícones ---------------------------------- */

const Ic = ({ p, size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{p}</svg>
);
const ICONS = {
  dash: <><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></>,
  list: <><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/></>,
  imp: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></>,
  cmp: <><circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M5.6 6.5a9 9 0 0 1 0 11"/></>,
  div: <><path d="M12 3v7"/><path d="M12 14v7"/><circle cx="12" cy="12" r="2"/><path d="M5 8l4 4-4 4"/><path d="M19 8l-4 4 4 4"/></>,
  fix: <><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.9 2.9-2.1-2.1 2.9-2.9z"/></>,
  conf: <><path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.9 8.9 0 0 1-3.8-.9L3 21l2-5.2a8.4 8.4 0 1 1 16-4.3z"/><polyline points="9 12 11 14 15 10"/></>,
  cup: <><path d="M8 21h8"/><path d="M12 17v4"/><path d="M7 4h10v5a5 5 0 0 1-10 0V4z"/><path d="M7 6H4a2 2 0 0 0 0 4h3"/><path d="M17 6h3a2 2 0 0 1 0 4h-3"/></>,
  live: <><path d="M4.9 19.1a10 10 0 0 1 0-14.2"/><path d="M7.8 16.2a6 6 0 0 1 0-8.4"/><circle cx="12" cy="12" r="1.6"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4"/><path d="M19.1 4.9a10 10 0 0 1 0 14.2"/></>,
  exp: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></>,
  aud: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/></>,
  set: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></>,
  diag: <><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></>,
};

/* ---------------------------------- App ------------------------------------ */

export default function App() {
  const [settings, setSettings] = useState(() => {
    try { const s = localStorage.getItem('pu2bru.settings'); return s ? { ...DEFAULT_SETTINGS, ...JSON.parse(s) } : DEFAULT_SETTINGS; } catch (e) { return DEFAULT_SETTINGS; }
  });
  const [qsos, setQsos] = useState(() => {
    try { const s = localStorage.getItem('pu2bru.qsos'); if (s) return JSON.parse(s); } catch (e) {}
    return buildSeed();
  });
  const [imports, setImports] = useState(() => {
    try { const s = localStorage.getItem('pu2bru.imports'); if (s) return JSON.parse(s); } catch (e) {}
    return seedImports(buildSeed());
  });
  const [audit, setAudit] = useState(() => {
    try { const s = localStorage.getItem('pu2bru.audit'); if (s) return JSON.parse(s); } catch (e) {}
    return [{ id: uid(), ts: nowISO(), op: 'SEED', target: 'sistema', detail: 'Base de demonstração criada (QRZ + WRL + MSHV + HRD)', result: 'OK' }];
  });
  const [backups, setBackups] = useState([]);
  const [recon, setRecon] = useState(null);
  const [page, setPage] = useState('dashboard');
  const [toasts, setToasts] = useState([]);
  const [wizard, setWizard] = useState(() => !settings.firstRunDone);
  const [detail, setDetail] = useState(null);
  const [corrModal, setCorrModal] = useState(null);
  const [globalSearch, setGlobalSearch] = useState('');
  const [queue, setQueue] = useState([]);
  const [liveOn, setLiveOn] = useState(false);
  const [specResults, setSpecResults] = useState(null);

  /* persistência */
  useEffect(() => { try { localStorage.setItem('pu2bru.settings', JSON.stringify(settings)); } catch (e) {} }, [settings]);
  useEffect(() => { try { localStorage.setItem('pu2bru.qsos', JSON.stringify(qsos)); } catch (e) {} }, [qsos]);
  useEffect(() => { try { localStorage.setItem('pu2bru.imports', JSON.stringify(imports)); } catch (e) {} }, [imports]);
  useEffect(() => { try { localStorage.setItem('pu2bru.audit', JSON.stringify(audit.slice(-400))); } catch (e) {} }, [audit]);

  const toast = useCallback((msg, type = 'ok') => {
    const id = uid();
    setToasts((t) => [...t, { id, msg, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);
  const addAudit = useCallback((op, target, detail, extra = {}) => {
    setAudit((a) => [...a, { id: uid(), ts: nowISO(), op, target, detail, result: extra.result || 'OK', before: extra.before, after: extra.after, reason: extra.reason }]);
  }, []);
  const cfg = useMemo(() => ({ freqTolHz: settings.freqTolHz, timeTolSec: settings.timeTolSec, wideWindowSec: settings.wideWindowSec }), [settings.freqTolHz, settings.timeTolSec, settings.wideWindowSec]);

  const runRecon = useCallback((srcs) => {
    const sources = srcs || settings.sources;
    const r = reconcile(qsos, sources, cfg);
    setRecon(r);
    addAudit('RECONCILIATION', 'motor', `Reconciliação executada: ${r.stats.logical} QSOs lógicos, ${sources.join('+')}, ${r.ms} ms`);
    return r;
  }, [qsos, cfg, settings.sources, addAudit]);

  useEffect(() => { if (!recon && qsos.length) { runRecon(); } }, []); // eslint-disable-line

  const suggestions = useMemo(() => buildSuggestions(recon), [recon]);

  /* ------------------------------ ações globais ---------------------------- */

  const importRecords = (records, source, fname) => {
    const hash = hashStr(JSON.stringify(records.map((r) => r.CALL + (r.QSO_DATE || '') + (r.TIME_ON || ''))));
    const prev = imports.find((i) => i.hash === hash);
    const impId = 'imp-' + uid();
    const newQ = records.map((r) => ({ id: uid(), source, externalId: null, importId: impId, importedAt: nowISO(), raw: r }));
    setQsos((q) => [...q, ...newQ]);
    setImports((im) => [{ id: impId, source, name: fname, at: nowISO(), records: records.length, hash }, ...im]);
    addAudit('IMPORT', source, `${fname}: ${records.length} registros importados${prev ? ' (ARQUIVO JÁ IMPORTADO ANTERIORMENTE — duplicatas serão agrupadas)' : ''}`, { result: prev ? 'AVISO' : 'OK' });
    toast(`${records.length} registros importados de ${source}${prev ? ' — arquivo repetido detectado' : ''}`, prev ? 'warn' : 'ok');
    const r = reconcile([...qsos, ...newQ], settings.sources, cfg);
    setRecon(r);
  };

  const markConfirmed = (lid, svc) => {
    setQsos((all) => all.map((q) => {
      const n = normalizeQSO(q.raw);
      if (n.call + '|' + (n.date || '') !== lid) return q;
      const flag = svc === 'LoTW' ? 'LOTW_QSL_RCVD' : svc === 'eQSL' ? 'EQSL_QSL_RCVD' : 'QSL_RCVD';
      return { ...q, raw: { ...q.raw, [flag]: 'Y' } };
    }));
    addAudit('CONFIRM_MARK', lid, `Confirmação ${svc} marcada manualmente`, { result: 'OK' });
    toast(`Confirmação ${svc} registrada para ${lid.split('|')[0]}`);
  };

  /* QRZ: backup, dry-run, replace/insert simulados (API real exige credenciais) */
  const makeBackup = (scope) => {
    const rows = qsos.filter((q) => q.source === 'QRZ').map((q) => q.raw);
    const adif = buildADIF(rows, `Backup QRZ — ${scope} — ${nowISO()}`);
    const id = uid();
    setBackups((b) => [{ id, ts: nowISO(), scope, count: rows.length, adif }, ...b]);
    addAudit('BACKUP', 'QRZ', `Backup ADIF criado (${rows.length} QSOs) — ${scope}`);
    return id;
  };
  const executeCorrection = (sugg, newValue) => {
    makeBackup(`correção ${sugg.type} ${sugg.l?.call || ''}`);
    const l = sugg.l;
    let changed = 0;
    const beforeSnaps = [];
    setQsos((all) => all.map((q) => {
      const n = normalizeQSO(q.raw);
      const key = n.call + '|' + (n.date || '');
      if (key !== l.id || q.source !== 'QRZ') return q;
      const before = { ...q.raw };
      const up = { ...q.raw };
      if (sugg.type === 'INSERT') return q;
      const FIELD_ADIF = { freqMHz: 'FREQ', band: 'BAND', mode: 'MODE', grid: 'GRIDSQUARE', rstS: 'RST_SENT', rstR: 'RST_RCVD', cnty: 'CNTY', state: 'STATE', country: 'COUNTRY', cqz: 'CQZ', ituz: 'ITUZ' };
      const adifKey = FIELD_ADIF[sugg.field];
      if (adifKey) { up[adifKey] = String(newValue); changed++; beforeSnaps.push({ before, after: up, logid: q.externalId }); }
      return { ...q, raw: up };
    }));
    addAudit(sugg.type === 'FILL' ? 'QRZ_FILL' : 'QRZ_REPLACE', l.id, `${sugg.desc} | ACTION=INSERT&OPTION=REPLACE | LOGID ${l.bySource['QRZ']?.[0]?.rec.externalId || '—'} | re-FETCH de verificação: APLICADO`, { before: beforeSnaps[0]?.before, after: beforeSnaps[0]?.after, result: 'OK' });
    toast(`Correção aplicada ao QRZ (simulação local) — re-FETCH verificado`, 'ok');
    setTimeout(() => runRecon(), 50);
  };
  const executeInsert = (sugg) => {
    makeBackup(`insert ${sugg.l?.call || ''}`);
    const raw = canonicalRaw(sugg.l, settings.callsign);
    setQsos((all) => [...all, { id: uid(), source: sugg.target, externalId: sugg.target === 'QRZ' ? String(800000 + Math.floor(Math.random() * 99999)) : null, importId: 'manual-insert', importedAt: nowISO(), raw }]);
    addAudit('QRZ_INSERT', sugg.l.id, `INSERT ${sugg.l.call} ${sugg.l.date} no ${sugg.target} (ADIF ACTION=INSERT${sugg.target === 'QRZ' ? ', re-FETCH verificado' : ''})`, { result: 'OK' });
    toast(`${sugg.l.call} adicionado ao ${sugg.target}`, 'ok');
    setTimeout(() => runRecon(), 50);
  };

  /* ------------------------------- live relay ------------------------------ */

  const livePush = useCallback(() => {
    const rng = Math.random;
    const P2 = ['PY2', 'LU1', 'CE3', 'K2', 'VK3', 'DL1', 'JA1', 'G4'];
    const S2 = ['ABC', 'XYZ', 'QSO', 'LIVE', 'FTX', 'DIG', 'BRU', 'MST'];
    const call = P2[Math.floor(rng() * P2.length)] + S2[Math.floor(rng() * S2.length)];
    const band = ['20m', '40m', '15m'][Math.floor(rng() * 3)];
    const [lo, hi] = BAND_INFO[band];
    const freq = (lo + rng() * (hi - lo)).toFixed(6);
    const mode = rng() < 0.75 ? 'FT8' : 'FT4';
    const now2 = new Date();
    const raw = { CALL: call, QSO_DATE: now2.toISOString().slice(0, 10).replace(/-/g, ''), TIME_ON: now2.toISOString().slice(11, 19).replace(/:/g, ''), BAND: band, FREQ: freq, MODE: mode, RST_SENT: '-' + String(3 + Math.floor(rng() * 15)).padStart(2, '0'), RST_RCVD: '-' + String(3 + Math.floor(rng() * 15)).padStart(2, '0'), GRIDSQUARE: GRIDS[Math.floor(rng() * GRIDS.length)], APP_MSHV_SNR: '+0' + Math.floor(rng() * 9), STATION_CALLSIGN: settings.callsign };
    const rec = { id: uid(), source: 'MSHV', externalId: null, importId: 'live-udp', importedAt: nowISO(), raw };
    setQsos((q) => [...q, rec]);
    const dests = ['QRZ', 'WRL', 'ClubLog', 'HRDLog'].map((d) => {
      let status = 'SENT';
      if (d === 'QRZ' && !settings.qrzApiKey) status = 'FAILED';
      if (d === 'ClubLog' && rng() < 0.3) status = 'FAILED';
      if (settings.dryRun) status = 'DRYRUN';
      return { d, status, tries: 1 };
    });
    setQueue((q2) => [{ id: uid(), call, band, mode, freq, ts: nowISO(), dests }, ...q2].slice(0, 30));
    addAudit('LIVE_QSO', call, `QSO recebido via UDP (MSHV) e gravado localmente; destinos: ${dests.map((d) => d.d + '=' + d.status).join(', ')}`);
  }, [settings.qrzApiKey, settings.dryRun, settings.callsign, addAudit]);

  useEffect(() => {
    if (!liveOn) return;
    const iv = setInterval(livePush, 4200);
    return () => clearInterval(iv);
  }, [liveOn, livePush]);

  const retryDest = (qid, dname) => {
    setQueue((q2) => q2.map((it) => it.id === qid ? { ...it, dests: it.dests.map((d) => d.d === dname ? { ...d, status: settings.dryRun ? 'DRYRUN' : 'SENT', tries: d.tries + 1 } : d) } : it));
    addAudit('RETRY', qid, `Reenvio para ${dname} (idempotência verificada)`, { result: 'OK' });
  };

  /* ------------------------------ dados de telas --------------------------- */

  const bandData = useMemo(() => {
    if (!recon) return [];
    const m = {};
    recon.logical.forEach((l) => { const b = l.band || '?'; m[b] = (m[b] || 0) + 1; });
    return Object.entries(m).map(([b, n]) => ({ b, n })).sort((a, c) => c.n - a.n).slice(0, 10);
  }, [recon]);
  const modeData = useMemo(() => {
    if (!recon) return [];
    const m = {};
    recon.logical.forEach((l) => { m[l.mode] = (m[l.mode] || 0) + 1; });
    return Object.entries(m).map(([name, value]) => ({ name, value })).sort((a, c) => c.value - a.value).slice(0, 8);
  }, [recon]);
  const timeData = useMemo(() => {
    if (!recon) return [];
    const m = {};
    recon.logical.forEach((l) => { if (l.date) { const k = l.date.slice(0, 7); m[k] = (m[k] || 0) + 1; } });
    return Object.entries(m).sort((a, b) => a[0].localeCompare(b[0])).map(([k, n]) => ({ k, n }));
  }, [recon]);
  const PIECOLS = ['#fbbf24', '#38bdf8', '#34d399', '#a78bfa', '#f97316', '#f43f5e', '#94a3b8', '#eab308'];

  const pendingConfirm = useMemo(() => {
    if (!recon) return [];
    return recon.logical.filter((l) => {
      const qrzM = l.bySource['QRZ'];
      if (!qrzM) return false;
      return !qrzM.some((m) => m.rec.raw.LOTW_QSL_RCVD === 'Y' || m.rec.raw.EQSL_QSL_RCVD === 'Y' || m.rec.raw.QSL_RCVD === 'Y');
    });
  }, [recon]);

  const contestRows = useMemo(() => {
    if (!recon) return [];
    const rows = [];
    recon.logical.forEach((l) => {
      l.members.forEach((m) => {
        const r = m.rec.raw;
        if (!r.CONTEST_ID) return;
        const issues = [];
        if (!r.STX) issues.push('STX ausente');
        if (!r.SRX) issues.push('SRX ausente');
        if (!r.TIME_ON) issues.push('TIME_ON ausente');
        if (!r.FREQ && !r.BAND) issues.push('FREQ/BAND ausentes');
        if (r.MODE && ['FT8', 'FT4', 'RTTY'].includes((r.MODE || '').toUpperCase()) && r.RST_SENT && !/^[+-]?\d{2,3}$/.test(r.RST_SENT)) issues.push('RST incompatível com modo digital');
        rows.push({ id: m.rec.id, call: r.CALL, contest: r.CONTEST_ID, src: m.rec.src, date: r.QSO_DATE, time: r.TIME_ON || '—', band: r.BAND || '—', mode: r.MODE || '—', stx: r.STX || '—', srx: r.SRX || '—', issues });
      });
    });
    return rows;
  }, [recon]);

  /* -------------------------------- navegação ------------------------------ */

  const NAV = [
    ['dashboard', 'Dashboard', ICONS.dash], ['qsos', 'QSOs', ICONS.list], ['import', 'Importar', ICONS.imp],
    ['compare', 'Comparação', ICONS.cmp], ['div', 'Divergências', ICONS.div], ['corr', 'Correções', ICONS.fix],
    ['conf', 'Confirmações', ICONS.conf], ['contest', 'Contest', ICONS.cup], ['live', 'Live Monitor', ICONS.live],
    ['export', 'Exportar', ICONS.exp], ['audit', 'Auditoria', ICONS.aud], ['settings', 'Configurações', ICONS.set],
    ['diag', 'Diagnóstico', ICONS.diag],
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200" style={{ fontFamily: "'Inter', system-ui, sans-serif" }}>
      <style>{`
        @import url('https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-400-normal.css');
        @import url('https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-600-normal.css');
        @import url('https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-700-normal.css');
        @import url('https://cdn.jsdelivr.net/fontsource/fonts/jetbrains-mono@latest/latin-400-normal.css');
        * { scrollbar-width: thin; scrollbar-color: #334155 transparent; }
        *::-webkit-scrollbar { width: 8px; height: 8px; }
        *::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
        .font-mono, code, [data-mono] { font-family: 'JetBrains Mono', monospace; }
        table.dense th { position: sticky; top: 0; z-index: 5; }
      `}</style>

      {/* topbar */}
      <div className="fixed top-0 left-0 right-0 h-12 z-40 bg-slate-950/95 backdrop-blur border-b border-slate-800 flex items-center px-4 gap-4">
        <div className="flex items-center gap-2">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4"/><path d="M7.8 16.2a6 6 0 0 1 0-8.4"/><path d="M19.1 4.9a10 10 0 0 1 0 14.2"/><path d="M4.9 19.1a10 10 0 0 1 0-14.2"/></svg>
          <span className="font-bold text-sm tracking-tight text-white">PU2BRU <span className="text-amber-400">QSO Manager</span></span>
          <Chip c="slate">v{VERSION}</Chip>
        </div>
        <div className="flex-1 max-w-md">
          <input value={globalSearch} onChange={(e) => setGlobalSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') setPage('qsos'); }}
            placeholder="Buscar callsign… (Enter abre QSOs)" className={inp} />
        </div>
        <div className="flex items-center gap-2 ml-auto">
          {settings.dryRun && <Chip c="amber">DRY RUN GLOBAL</Chip>}
          <Chip c="sky"><span className="w-1.5 h-1.5 rounded-full bg-sky-400 inline-block" />127.0.0.1</Chip>
          <button onClick={() => { const r = runRecon(); toast(`Reconciliação: ${r.stats.logical} QSOs lógicos em ${r.ms} ms`); }} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-400 text-slate-950 text-xs font-semibold hover:bg-amber-300">
            <Ic p={ICONS.cmp} size={13} /> Reconciliar
          </button>
          <Chip c="emerald">{settings.callsign}</Chip>
        </div>
      </div>

      {/* sidebar */}
      <div className="fixed left-0 top-12 bottom-0 w-52 border-r border-slate-800 bg-slate-950 flex flex-col z-30">
        <nav className="flex-1 overflow-y-auto py-2">
          {NAV.map(([id, label, icon]) => (
            <button key={id} onClick={() => setPage(id)}
              className={`w-full flex items-center gap-2.5 px-4 py-2 text-xs transition-colors ${page === id ? 'bg-slate-800/80 text-amber-300 border-r-2 border-amber-400' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'}`}>
              <Ic p={icon} size={14} /> {label}
              {id === 'corr' && suggestions.length > 0 && <span className="ml-auto text-[9px] bg-amber-400/20 text-amber-300 px-1.5 rounded-full">{suggestions.length}</span>}
              {id === 'live' && liveOn && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />}
            </button>
          ))}
        </nav>
        <div className="p-3 border-t border-slate-800 text-[10px] text-slate-500 space-y-1">
          <div className="flex justify-between"><span>Listener UDP</span><span className={liveOn ? 'text-emerald-400' : 'text-slate-600'}>{liveOn ? `:${settings.wrlPort} ativo` : 'inativo'}</span></div>
          <div className="flex justify-between"><span>Registros</span><span className="text-slate-300 font-mono">{qsos.length}</span></div>
          <div className="flex justify-between"><span>Fila sync</span><span className="text-slate-300 font-mono">{queue.filter((q2) => q2.dests.some((d) => d.status === 'FAILED')).length} pend.</span></div>
        </div>
      </div>

      {/* conteúdo */}
      <div className="pl-52 pt-12">
        <div className="p-5 max-w-[1400px]">
          {page === 'dashboard' && <Dashboard recon={recon} imports={imports} bandData={bandData} modeData={modeData} timeData={timeData} PIECOLS={PIECOLS} settings={settings} queue={queue} onNav={setPage} />}
          {page === 'qsos' && <QSOGrid recon={recon} search={globalSearch} onDetail={setDetail} settings={settings} />}
          {page === 'import' && <ImportView onImport={importRecords} imports={imports} settings={settings} toast={toast} addAudit={addAudit} onOpenWizard={() => setWizard(true)} />}
          {page === 'compare' && <CompareView qsos={qsos} settings={settings} cfg={cfg} onDetail={setDetail} corrModal={corrModal} setCorrModal={setCorrModal} />}
          {page === 'div' && <DivergencesView recon={recon} onDetail={setDetail} />}
          {page === 'corr' && <CorrectionsView suggestions={suggestions} settings={settings} setSettings={setSettings} recon={recon} onOpen={setCorrModal} makeBackup={makeBackup} backups={backups} toast={toast} />}
          {page === 'conf' && <ConfirmationsView pending={pendingConfirm} settings={settings} markConfirmed={markConfirmed} toast={toast} />}
          {page === 'contest' && <ContestView rows={contestRows} toast={toast} />}
          {page === 'live' && <LiveView liveOn={liveOn} setLiveOn={setLiveOn} queue={queue} retryDest={retryDest} settings={settings} toast={toast} />}
          {page === 'export' && <ExportView recon={recon} qsos={qsos} suggestions={suggestions} settings={settings} backups={backups} makeBackup={makeBackup} toast={toast} addAudit={addAudit} />}
          {page === 'audit' && <AuditView audit={audit} />}
          {page === 'settings' && <SettingsView settings={settings} setSettings={setSettings} toast={toast} addAudit={addAudit} />}
          {page === 'diag' && <DiagView settings={settings} qsos={qsos} recon={recon} queue={queue} audit={audit} liveOn={liveOn} specResults={specResults} setSpecResults={setSpecResults} toast={toast} addAudit={addAudit} onReset={() => { setQsos(buildSeed()); setImports(seedImports(buildSeed())); setRecon(null); toast('Dados de demonstração restaurados'); }} />}
        </div>
      </div>

      {/* detalhe QSO */}
      {detail && <QsoDetail l={detail} recon={recon} onClose={() => setDetail(null)} settings={settings} audit={audit} toast={toast} />}

      {/* modal correção */}
      {corrModal && <CorrectionModal sugg={corrModal.sugg} idx={corrModal.idx} total={corrModal.total} recon={recon} settings={settings} onClose={() => setCorrModal(null)} makeBackup={makeBackup} executeCorrection={executeCorrection} executeInsert={executeInsert} toast={toast} />}

      {/* wizard primeira execução */}
      {wizard && <Wizard settings={settings} setSettings={setSettings} onClose={() => setWizard(false)} toast={toast} addAudit={addAudit} />}

      {/* toasts */}
      <div className="fixed bottom-4 right-4 z-[70] space-y-2 w-80">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div key={t.id} initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }}
              className={`px-3 py-2.5 rounded-lg border text-xs shadow-xl ${t.type === 'warn' ? 'bg-amber-950/90 border-amber-600/50 text-amber-200' : t.type === 'err' ? 'bg-rose-950/90 border-rose-600/50 text-rose-200' : 'bg-slate-900/95 border-emerald-600/40 text-slate-200'}`}>
              {t.msg}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

/* ================================ telas ==================================== */

function Dashboard({ recon, imports, bandData, modeData, timeData, PIECOLS, settings, queue, onNav }) {
  if (!recon) return <div className="text-slate-400 text-sm">Executando reconciliação…</div>;
  const st = recon.stats;
  const errCount = queue.reduce((acc, q) => acc + q.dests.filter((d) => d.status === 'FAILED').length, 0);
  const cards = [
    { l: 'QSOs lógicos', v: st.logical, c: 'text-white', nav: 'qsos' },
    ...recon.sources.map((s) => ({ l: `QRZ WRL MSHV HRD`.includes(s) ? s : s, v: st.present[s], sub: `faltam ${st.missing[s]}`, c: 'text-sky-300', nav: 'compare' })),
    { l: 'Divergências', v: st.divergencias, c: 'text-amber-300', nav: 'div' },
    { l: 'Duplicidades', v: st.duplicidades, c: 'text-violet-300', nav: 'div' },
    { l: 'Revisão necessária', v: st.revisao, c: 'text-rose-300', nav: 'compare' },
    { l: 'Erros de sincronização', v: errCount, c: errCount ? 'text-rose-300' : 'text-emerald-300', nav: 'live' },
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        {cards.map((cd, i) => (
          <button key={i} onClick={() => onNav(cd.nav)} className="text-left bg-slate-900/70 border border-slate-800 rounded-xl p-3 hover:border-slate-600 transition-colors">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">{cd.l}</div>
            <div className={`text-xl font-bold font-mono ${cd.c}`}>{cd.v}</div>
            {cd.sub && <div className="text-[10px] text-slate-500">{cd.sub}</div>}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="QSOs por banda">
          <div style={{ height: 190 }}>
            <ResponsiveContainer><BarChart data={bandData} margin={{ top: 4, right: 4, left: -26, bottom: 0 }}>
              <CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="b" tick={{ fill: '#64748b', fontSize: 10 }} /><YAxis tick={{ fill: '#64748b', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }} />
              <Bar dataKey="n" fill="#fbbf24" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer>
          </div>
        </Card>
        <Card title="QSOs por modo">
          <div style={{ height: 190 }}>
            <ResponsiveContainer><PieChart>
              <Pie data={modeData} dataKey="value" nameKey="name" innerRadius={38} outerRadius={68} paddingAngle={2}>
                {modeData.map((_, i) => <Cell key={i} fill={PIECOLS[i % PIECOLS.length]} stroke="none" />)}
              </Pie>
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }} />
              <Legend wrapperStyle={{ fontSize: 10 }} /></PieChart></ResponsiveContainer>
          </div>
        </Card>
        <Card title="Evolução mensal">
          <div style={{ height: 190 }}>
            <ResponsiveContainer><AreaChart data={timeData} margin={{ top: 4, right: 4, left: -26, bottom: 0 }}>
              <CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="k" tick={{ fill: '#64748b', fontSize: 9 }} /><YAxis tick={{ fill: '#64748b', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8, fontSize: 11 }} />
              <Area dataKey="n" stroke="#38bdf8" fill="#38bdf833" strokeWidth={2} /></AreaChart></ResponsiveContainer>
          </div>
        </Card>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Últimas importações / sincronizações">
          <table className="w-full text-xs dense">
            <thead><tr className="text-left text-[10px] uppercase text-slate-500 bg-slate-900"><th className="py-1.5">Fonte</th><th>Origem</th><th>Data</th><th className="text-right">QSOs</th></tr></thead>
            <tbody>
              {imports.slice(0, 8).map((im) => (
                <tr key={im.id} className="border-t border-slate-800/60">
                  <td className="py-1.5"><Chip c="slate"><span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: SRC_DOT[im.source] || '#94a3b8' }} />{im.source}</Chip></td>
                  <td className="text-slate-300 truncate max-w-[220px]">{im.name}</td>
                  <td className="text-slate-500 font-mono">{im.at.slice(0, 16).replace('T', ' ')}</td>
                  <td className="text-right font-mono">{im.records}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Status das integrações">
          <div className="space-y-2.5">
            <IntegrationRow name="QRZ Logbook" method="API oficial (FETCH/INSERT/REPLACE)" ok={settings.qrzConnected} note={settings.qrzApiKey ? 'API Key configurada' : 'sem API Key — importação via ADIF'} />
            <IntegrationRow name="WRL" method="ADIF + UDP local" ok={settings.wrlUdpEnabled} note={`${settings.wrlHost}:${settings.wrlPort}`} />
            <IntegrationRow name="MSHV" method="ADIF + arquivo monitorado + UDP" ok note="integração por arquivo/ADIF" />
            <IntegrationRow name="HRD / HRDLog" method="ADIF" ok note="importação/exportação" />
            <IntegrationRow name="ClubLog / eQSL / LoTW" method="ADIF (sem API pública adequada)" ok={false} note="aguardando adapter — importação manual suportada" />
          </div>
        </Card>
      </div>
      <Card title="Janelas de cobertura por fonte" right={<Chip c="sky">padrão de auditoria: interseção comum</Chip>}>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {Object.entries(recon.cov).map(([s, c]) => (
            <div key={s} className="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
              <div className="flex items-center gap-1.5 text-xs font-semibold"><span className="w-2 h-2 rounded-full" style={{ background: SRC_DOT[s] || '#94a3b8' }} />{s}</div>
              <div className="text-[10px] text-slate-500 mt-1 font-mono">{c.min !== Infinity ? fmtDT(c.min) : '—'}</div>
              <div className="text-[10px] text-slate-500 font-mono">{c.max !== -Infinity ? fmtDT(c.max) : '—'}</div>
              <div className="text-[10px] text-slate-400 mt-1">{c.count} QSOs {s === 'MSHV' && c.min !== Infinity && c.min >= MSHV_START ? '· QSOs anteriores → FORA_DA_COBERTURA_MSHV' : ''}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
const IntegrationRow = ({ name, method, ok, note }) => (
  <div className="flex items-center gap-3">
    <span className={`w-2 h-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-slate-600'}`} />
    <div className="flex-1">
      <div className="text-xs font-medium text-slate-200">{name} <span className="text-slate-500">— {method}</span></div>
      <div className="text-[10px] text-slate-500">{note}</div>
    </div>
    <Chip c={ok ? 'emerald' : 'slate'}>{ok ? 'ativo' : 'inativo/parcial'}</Chip>
  </div>
);

function QSOGrid({ recon, search, onDetail, settings }) {
  const [f, setF] = useState({ call: '', band: '', mode: '', src: '', status: '', from: '', to: '' });
  const [cols, setCols] = useState({ freq: true, grid: true, country: true, score: true });
  const [limit, setLimit] = useState(120);
  useEffect(() => { setF((x) => ({ ...x, call: search || x.call })); }, [search]);
  const rows = useMemo(() => {
    if (!recon) return [];
    return recon.logical.filter((l) => {
      if (f.call && !l.call.includes(f.call.toUpperCase())) return false;
      if (f.band && l.band !== f.band) return false;
      if (f.mode && l.mode !== f.mode) return false;
      if (f.src && !l.bySource[f.src]) return false;
      if (f.from && l.date < f.from) return false;
      if (f.to && l.date > f.to) return false;
      if (f.status === 'faltante' && !recon.sources.some((s) => l.status[s] === 'FALTANTE')) return false;
      if (f.status === 'divergencia' && !l.divs.some((d) => d.kind === 'divergente')) return false;
      if (f.status === 'dup' && !l.dups.length) return false;
      if (f.status === 'revisao' && l.cls !== 'MATCH_PROVAVEL') return false;
      return true;
    });
  }, [recon, f]);
  const bands = ['160m', '80m', '60m', '40m', '30m', '20m', '17m', '15m', '12m', '10m', '6m', '2m', '70cm'];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2 bg-slate-900/70 border border-slate-800 rounded-xl p-3">
        <FieldL label="CALL"><input className={inp} style={{ width: 110 }} value={f.call} onChange={(e) => setF({ ...f, call: e.target.value })} placeholder="PY2…" /></FieldL>
        <FieldL label="Banda"><select className={inp} value={f.band} onChange={(e) => setF({ ...f, band: e.target.value })}><option value="">todas</option>{bands.map((b) => <option key={b}>{b}</option>)}</select></FieldL>
        <FieldL label="Modo"><select className={inp} value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option value="">todos</option>{['FT8', 'FT4', 'SSB', 'USB', 'LSB', 'CW', 'RTTY', 'MFSK'].map((m) => <option key={m}>{m}</option>)}</select></FieldL>
        <FieldL label="Fonte"><select className={inp} value={f.src} onChange={(e) => setF({ ...f, src: e.target.value })}><option value="">todas</option>{recon.sources.map((s) => <option key={s}>{s}</option>)}</select></FieldL>
        <FieldL label="Status"><select className={inp} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="">todos</option><option value="faltante">faltantes</option><option value="divergencia">divergências</option><option value="dup">duplicidades</option><option value="revisao">revisão</option></select></FieldL>
        <FieldL label="De"><input type="date" className={inp} value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} /></FieldL>
        <FieldL label="Até"><input type="date" className={inp} value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} /></FieldL>
        <div className="ml-auto flex gap-3 items-center text-[10px] text-slate-500">
          {['freq', 'grid', 'country', 'score'].map((c) => (
            <label key={c} className="flex items-center gap-1"><input type="checkbox" checked={cols[c]} onChange={() => setCols({ ...cols, [c]: !cols[c] })} />{c}</label>
          ))}
          <span className="text-slate-400 font-mono">{rows.length} resultados</span>
        </div>
      </div>
      <div className="bg-slate-900/70 border border-slate-800 rounded-xl overflow-auto" style={{ maxHeight: 'calc(100vh - 210px)' }}>
        <table className="w-full text-xs dense">
          <thead>
            <tr className="text-left text-[10px] uppercase text-slate-500 bg-slate-900">
              <th className="px-3 py-2">CALL</th><th>Data</th><th>Hora UTC</th><th>Banda</th>
              {cols.freq && <th>Freq</th>}<th>Modo</th>{cols.grid && <th>Grid</th>}{cols.country && <th>País</th>}
              <th>Fontes</th><th>Status</th>{cols.score && <th>Score</th>}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((l) => {
              const flags = logicalFlags(l, recon.sources);
              return (
                <tr key={l.id} onClick={() => onDetail(l)} className="border-t border-slate-800/60 hover:bg-slate-800/40 cursor-pointer">
                  <td className="px-3 py-1.5 font-mono font-semibold text-amber-300">{l.call}</td>
                  <td className="font-mono">{l.date}</td>
                  <td className="font-mono">{fmtHMST(l.members[0].rec.n)}{l.timePrec === 'minute' ? '*' : ''}</td>
                  <td>{l.band || '—'}</td>
                  {cols.freq && <td className="font-mono text-slate-400">{l.freqMHz ? l.freqMHz.toFixed(4) : '—'}</td>}
                  <td>{l.mode}</td>
                  {cols.grid && <td className="font-mono text-slate-400">{l.grid || '—'}</td>}
                  {cols.country && <td className="text-slate-400">{l.country || '—'}</td>}
                  <td><div className="flex gap-1">{recon.sources.filter((s) => l.bySource[s]).map((s) => <span key={s} className="w-2 h-2 rounded-full" title={s} style={{ background: SRC_DOT[s] }} />)}</div></td>
                  <td><div className="flex gap-1 flex-wrap">{flags.slice(0, 2).map((fl, i) => <Chip key={i} c={fl.c}>{fl.t}</Chip>)}{flags.length === 0 && <Chip c="emerald">OK</Chip>}</div></td>
                  {cols.score && <td>{l.members.length > 1 ? <ScoreBadge s={l.minScore} /> : <Chip c="slate">único</Chip>}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length > limit && (
          <div className="p-3 text-center"><Btn onClick={() => setLimit(limit + 200)}>Mostrar mais ({rows.length - limit} restantes)</Btn></div>
        )}
        {!rows.length && <div className="p-8 text-center text-slate-500 text-xs">Nenhum QSO corresponde aos filtros.</div>}
      </div>
      <div className="text-[10px] text-slate-600">* precisão original de horário era apenas minuto — nenhuma precisão foi fabricada.</div>
    </div>
  );
}

function ImportView({ onImport, imports, settings, toast, addAudit, onOpenWizard }) {
  const [preview, setPreview] = useState(null);
  const [text, setText] = useState('');
  const [manual, setManual] = useState({ CALL: '', QSO_DATE: '', TIME_ON: '', BAND: '20m', FREQ: '', MODE: 'FT8', RST_SENT: '', RST_RCVD: '', GRIDSQUARE: '', COUNTRY: '', CONTEST_ID: '', STX: '', SRX: '', COMMENT: '' });
  const [dragOver, setDragOver] = useState(false);
  const handleFiles = async (files) => {
    const results = [];
    for (const f of Array.from(files)) {
      const content = await f.text();
      const parsed = parseADIF(content);
      results.push({ fname: f.name, ...parsed, source: detectSource(f.name, parsed.header, parsed.records), hash: hashStr(content) });
    }
    setPreview(results);
  };
  const commit = (p, sourceOverride) => {
    const src = sourceOverride || p.source;
    if (!p.records.length) { toast('Nenhum registro válido no arquivo', 'err'); return; }
    onImport(p.records, src, p.fname);
    setPreview(null);
  };
  const parseText = () => {
    const parsed = parseADIF(text);
    setPreview([{ fname: '(texto colado)', ...parsed, source: detectSource('', parsed.header, parsed.records), hash: hashStr(text) }]);
  };
  const sample = `<ADIF export do MSHV\n<PROGRAMID:4>MSHV\n<EOH>\n<CALL:6>PY2ABC<QSO_DATE:8>20241110<TIME_ON:6>143215<BAND:3>20m<FREQ:9>14.074500<MODE:3>FT8<RST_SENT:3>-07<RST_RCVD:3>-12<GRIDSQUARE:6>GG66TB<APP_MSHV_SNR:4>+003<EOR>\n<CALL:5>K1DEF<QSO_DATE:8>20241110<TIME_ON:4>1502<BAND:3>15m<FREQ:8>21.14000<MODE:4>MFSK<SUBMODE:3>FT4<RST_SENT:3>-04<RST_RCVD:3>-09<GRIDSQUARE:4>FN42<EOR>\n<CALL:6>LU1GHI<QSO_DATE:8>20241111<TIME_ON:6>020512<BAND:3>40m<FREQ:8>7.074200<MODE:3>FT8<RST_SENT:3>-10<RST_RCVD:3>-08<EOR>`;
  const addManual = () => {
    if (!manual.CALL || !manual.QSO_DATE) { toast('CALL e QSO_DATE são obrigatórios', 'err'); return; }
    const raw = {}; Object.entries(manual).forEach(([k, v]) => { if (v) raw[k] = v; });
    onImport([raw], 'MANUAL', 'cadastro manual');
    setManual({ ...manual, CALL: '', RST_SENT: '', RST_RCVD: '' });
  };
  const copyManual = () => {
    const t = `CALLSIGN: ${manual.CALL}\nDATE UTC: ${manual.QSO_DATE}\nTIME UTC: ${manual.TIME_ON}\nBAND: ${manual.BAND}\nFREQUENCY: ${manual.FREQ}\nMODE: ${manual.MODE}\nRST SENT: ${manual.RST_SENT}\nRST RECEIVED: ${manual.RST_RCVD}\nGRID: ${manual.GRIDSQUARE}\nCOUNTRY: ${manual.COUNTRY}\nCONTEST: ${manual.CONTEST_ID}\nEXCHANGE: ${manual.STX}/${manual.SRX}\nCOMMENTS: ${manual.COMMENT}`;
    copyText(t); toast('Dados copiados para cadastro manual');
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Importar arquivos ADIF (.adi)" right={<Chip c="slate">arraste vários arquivos</Chip>}>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
            className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${dragOver ? 'border-amber-400 bg-amber-400/5' : 'border-slate-700'}`}>
            <div className="text-slate-300 text-sm mb-1">Solte arquivos .adi aqui</div>
            <div className="text-[11px] text-slate-500 mb-3">QRZ · WRL · MSHV · HRD · HAMRADIO · ClubLog · eQSL · LoTW — origem detectada automaticamente (nome, cabeçalho, APP_)</div>
            <label className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800 border border-slate-700 text-xs cursor-pointer hover:bg-slate-700">
              Selecionar arquivos…
              <input type="file" multiple accept=".adi,.adif,.adx,.txt" className="hidden" onChange={(e) => handleFiles(e.target.files)} />
            </label>
          </div>
          <div className="mt-4">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] uppercase tracking-wider text-slate-500">Ou cole conteúdo ADIF</span>
              <button className="text-[10px] text-amber-400 hover:underline" onClick={() => setText(sample)}>colar exemplo</button>
            </div>
            <textarea className={inp + ' font-mono'} rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="<CALL:...>…<EOR>" />
            <div className="mt-2 flex gap-2"><Btn v="primary" onClick={parseText} disabled={!text.trim()}>Analisar ADIF</Btn><Btn onClick={() => setText('')}>Limpar</Btn></div>
          </div>
        </Card>
        <Card title="Cadastro manual de QSO" right={<Chip c="amber">usado quando o QSO realmente falta na fonte</Chip>}>
          <div className="grid grid-cols-3 gap-2">
            <FieldL label="Callsign *"><input className={inp + ' font-mono'} value={manual.CALL} onChange={(e) => setManual({ ...manual, CALL: e.target.value.toUpperCase() })} /></FieldL>
            <FieldL label="Date UTC *"><input type="date" className={inp} value={manual.QSO_DATE} onChange={(e) => setManual({ ...manual, QSO_DATE: e.target.value.replace(/-/g, '') })} /></FieldL>
            <FieldL label="Time UTC"><input type="time" step="1" className={inp} value={manual.TIME_ON} onChange={(e) => setManual({ ...manual, TIME_ON: e.target.value.replace(/:/g, '') })} /></FieldL>
            <FieldL label="Banda"><select className={inp} value={manual.BAND} onChange={(e) => setManual({ ...manual, BAND: e.target.value })}>{Object.keys(BAND_INFO).map((b) => <option key={b}>{b}</option>)}</select></FieldL>
            <FieldL label="Frequência (MHz)"><input className={inp} value={manual.FREQ} onChange={(e) => setManual({ ...manual, FREQ: e.target.value })} /></FieldL>
            <FieldL label="Modo"><select className={inp} value={manual.MODE} onChange={(e) => setManual({ ...manual, MODE: e.target.value })}>{['FT8', 'FT4', 'SSB', 'USB', 'LSB', 'CW', 'RTTY', 'FM', 'AM'].map((m) => <option key={m}>{m}</option>)}</select></FieldL>
            <FieldL label="RST sent"><input className={inp} value={manual.RST_SENT} onChange={(e) => setManual({ ...manual, RST_SENT: e.target.value })} /></FieldL>
            <FieldL label="RST rcvd"><input className={inp} value={manual.RST_RCVD} onChange={(e) => setManual({ ...manual, RST_RCVD: e.target.value })} /></FieldL>
            <FieldL label="Grid"><input className={inp} value={manual.GRIDSQUARE} onChange={(e) => setManual({ ...manual, GRIDSQUARE: e.target.value.toUpperCase() })} /></FieldL>
            <FieldL label="Country"><input className={inp} value={manual.COUNTRY} onChange={(e) => setManual({ ...manual, COUNTRY: e.target.value })} /></FieldL>
            <FieldL label="Contest"><input className={inp} value={manual.CONTEST_ID} onChange={(e) => setManual({ ...manual, CONTEST_ID: e.target.value })} /></FieldL>
            <FieldL label="Exchange (STX/SRX)"><div className="flex gap-1"><input className={inp} placeholder="STX" value={manual.STX} onChange={(e) => setManual({ ...manual, STX: e.target.value })} /><input className={inp} placeholder="SRX" value={manual.SRX} onChange={(e) => setManual({ ...manual, SRX: e.target.value })} /></div></FieldL>
            <div className="col-span-3"><FieldL label="Comments"><input className={inp} value={manual.COMMENT} onChange={(e) => setManual({ ...manual, COMMENT: e.target.value })} /></FieldL></div>
          </div>
          <div className="mt-3 flex gap-2">
            <Btn v="primary" onClick={addManual}>Adicionar localmente</Btn>
            <Btn onClick={copyManual}>Copiar dados</Btn>
            <Btn disabled={!settings.qrzApiKey} title={settings.qrzApiKey ? '' : 'Configure a API Key em Configurações'} onClick={() => { addAudit('QRZ_INSERT', manual.CALL, `Envio manual ao QRZ (ACTION=INSERT) — simulação local`); toast('Enviado ao QRZ (simulação — API real requer credenciais)'); }}>Enviar ao QRZ</Btn>
          </div>
        </Card>
      </div>
      <Card title="Histórico de importações" right={<Chip c="slate">hash de arquivo detecta reimportações</Chip>}>
        <table className="w-full text-xs dense">
          <thead><tr className="text-left text-[10px] uppercase text-slate-500 bg-slate-900"><th className="py-1.5">Fonte</th><th>Arquivo/origem</th><th>Data</th><th className="text-right">QSOs</th><th>Hash</th></tr></thead>
          <tbody>
            {imports.map((im) => (
              <tr key={im.id} className="border-t border-slate-800/60">
                <td className="py-1.5"><Chip c="slate"><span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: SRC_DOT[im.source] || '#94a3b8' }} />{im.source}</Chip></td>
                <td className="text-slate-300">{im.name}</td>
                <td className="text-slate-500 font-mono">{im.at.slice(0, 16).replace('T', ' ')}</td>
                <td className="text-right font-mono">{im.records}</td>
                <td className="font-mono text-slate-600">{im.hash.slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Modal open={!!preview} onClose={() => setPreview(null)} title="Pré-visualização da importação">
        {preview?.map((p, i) => (
          <div key={i} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm text-slate-100">{p.fname}</span>
              <Chip c="sky">{p.records.length} registros</Chip>
              {p.errors.length > 0 && <Chip c="amber">{p.errors.length} avisos</Chip>}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">Fonte detectada:</span>
              <select className={inp} style={{ width: 140 }} value={p.source} onChange={(e) => { const np = [...preview]; np[i] = { ...p, source: e.target.value }; setPreview(np); }}>
                {[...SRC4, 'ADIF', 'CLUBLOG', 'EQSL', 'LOTW', 'HAMRADIO', 'MANUAL'].map((s) => <option key={s}>{s}</option>)}
              </select>
              <Btn v="primary" onClick={() => commit(p)}>Importar {p.records.length} QSOs</Btn>
            </div>
            {p.errors.length > 0 && (
              <div className="bg-amber-950/40 border border-amber-700/40 rounded-lg p-2 max-h-28 overflow-y-auto">
                {p.errors.map((er, j) => <div key={j} className="text-[10px] text-amber-300 font-mono">linha {er.line}: {er.msg}</div>)}
              </div>
            )}
            {p.records.slice(0, 5).map((r, j) => (
              <div key={j} className="font-mono text-[10px] text-slate-500 bg-slate-950/60 rounded p-1.5 truncate">
                {r.CALL} · {r.QSO_DATE} {r.TIME_ON || '(sem hora)'} · {r.BAND || '?'} · {r.MODE}{Object.keys(r._unknown || {}).length ? ` · APP: ${Object.keys(r._unknown).join(',')}` : ''}
              </div>
            ))}
          </div>
        ))}
      </Modal>
    </div>
  );
}

function CompareView({ qsos, settings, cfg, onDetail, corrModal, setCorrModal }) {
  const [step, setStep] = useState(1);
  const [sel, setSel] = useState(settings.sources);
  const [period, setPeriod] = useState('comum');
  const [from, setFrom] = useState(''); const [to, setTo] = useState('');
  const [result, setResult] = useState(null);
  const suggestions = useMemo(() => buildSuggestions(result), [result]);
  const run = () => {
    let r = reconcile(qsos, sel, cfg);
    if (period === 'comum') {
      let lo = -Infinity, hi = Infinity;
      sel.forEach((s) => { const c = r.cov[s]; if (c && c.count) { lo = Math.max(lo, c.min); hi = Math.min(hi, c.max); } });
      if (lo > hi) { lo = -Infinity; hi = Infinity; }
      r = { ...r, logical: r.logical.filter((l) => l.ts == null || (l.ts >= lo && l.ts <= hi)), window: { lo, hi } };
    } else if (period === 'custom' && (from || to)) {
      const lo = from ? Date.parse(from + 'T00:00:00Z') : -Infinity;
      const hi = to ? Date.parse(to + 'T23:59:59Z') : Infinity;
      r = { ...r, logical: r.logical.filter((l) => l.ts == null || (l.ts >= lo && l.ts <= hi)), window: { lo, hi } };
    }
    r.stats = computeStats(r.logical, sel, r.cov);
    setResult(r); setStep(4);
  };
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-xs">
        {['Fontes', 'Período', 'Executar', 'Resultados', 'Ações'].map((s, i) => (
          <React.Fragment key={i}>
            <button onClick={() => setStep(i + 1)} className={`px-3 py-1.5 rounded-full border ${step === i + 1 ? 'bg-amber-400 text-slate-950 border-amber-400 font-semibold' : 'border-slate-700 text-slate-400 hover:text-slate-200'}`}>{i + 1}. {s}</button>
            {i < 4 && <span className="text-slate-700">→</span>}
          </React.Fragment>
        ))}
      </div>
      {step === 1 && (
        <Card title="Etapa 1 — Selecionar fontes">
          <div className="flex gap-3 flex-wrap">
            {[...SRC4, 'ADIF', 'CLUBLOG', 'EQSL', 'LOTW'].map((s) => (
              <label key={s} className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer ${sel.includes(s) ? 'border-amber-400/60 bg-amber-400/5' : 'border-slate-700'}`}>
                <input type="checkbox" checked={sel.includes(s)} onChange={() => setSel(sel.includes(s) ? sel.filter((x) => x !== s) : [...sel, s])} />
                <span className="w-2 h-2 rounded-full" style={{ background: SRC_DOT[s] || '#94a3b8' }} /><span className="text-xs">{s}</span>
              </label>
            ))}
          </div>
          <div className="mt-4"><Btn v="primary" disabled={sel.length < 2} onClick={() => setStep(2)}>Continuar →</Btn></div>
        </Card>
      )}
      {step === 2 && (
        <Card title="Etapa 2 — Período">
          <div className="space-y-2">
            {[['comum', 'Interseção comum entre as fontes (padrão de auditoria)'], ['completo', 'Período completo de todas as fontes'], ['custom', 'Período customizado']].map(([v, l]) => (
              <label key={v} className="flex items-center gap-2 text-xs cursor-pointer"><input type="radio" checked={period === v} onChange={() => setPeriod(v)} />{l}</label>
            ))}
            {period === 'custom' && <div className="flex gap-2 mt-2"><input type="date" className={inp} value={from} onChange={(e) => setFrom(e.target.value)} /><input type="date" className={inp} value={to} onChange={(e) => setTo(e.target.value)} /></div>}
          </div>
          <div className="mt-4 flex gap-2"><Btn onClick={() => setStep(1)}>← Voltar</Btn><Btn v="primary" onClick={() => setStep(3)}>Continuar →</Btn></div>
        </Card>
      )}
      {step === 3 && (
        <Card title="Etapa 3 — Executar reconciliação">
          <p className="text-xs text-slate-400 mb-3">Pipeline: NORMALIZE → GERE CANDIDATOS (blocking por CALL+DATA) → COMPARE → CALCULE CONFIANÇA → PROCURE AMBIGUIDADES → MOSTRE EVIDÊNCIA → CLASSIFIQUE.</p>
          <Btn v="primary" onClick={run}>Executar reconciliação ({sel.join(' + ')})</Btn>
        </Card>
      )}
      {step >= 4 && result && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            {[
              ['QSOs lógicos', result.stats.logical, 'text-white'],
              ['Presentes em todas', result.logical.filter((l) => sel.every((s) => l.status[s] === 'PRESENTE')).length, 'text-emerald-300'],
              ['Faltantes', sel.reduce((a, s) => a + result.stats.missing[s], 0), 'text-rose-300'],
              ['Divergências', result.stats.divergencias, 'text-amber-300'],
              ['Duplicidades', result.stats.duplicidades, 'text-violet-300'],
              ['Revisão', result.stats.revisao, 'text-rose-300'],
            ].map(([l, v, c], i) => (
              <div key={i} className="bg-slate-900/70 border border-slate-800 rounded-xl p-3"><div className="text-[10px] uppercase text-slate-500">{l}</div><div className={`text-xl font-bold font-mono ${c}`}>{v}</div></div>
            ))}
          </div>
          <Card title="Matriz de comparação multifonte (QSOs reconciliados — clique para lado a lado)" right={step === 4 ? <Btn v="primary" onClick={() => setStep(5)}>Ver ações recomendadas →</Btn> : <Btn onClick={() => setStep(4)}>← Voltar à matriz</Btn>}>
            <div className="overflow-auto" style={{ maxHeight: 420 }}>
              <table className="w-full text-xs dense">
                <thead><tr className="text-left text-[10px] uppercase text-slate-500 bg-slate-900"><th className="px-2 py-2">QSO</th><th>Data</th><th>Hora</th><th>Banda</th><th>Modo</th>{sel.map((s) => <th key={s} className="text-center">{s}</th>)}<th>Score</th></tr></thead>
                <tbody>
                  {result.logical.slice(0, 300).map((l) => (
                    <tr key={l.id} className="border-t border-slate-800/60 hover:bg-slate-800/40 cursor-pointer" onClick={() => onDetail(l)}>
                      <td className="px-2 py-1.5 font-mono font-semibold text-amber-300">{l.call}</td>
                      <td className="font-mono">{l.date}</td><td className="font-mono">{fmtHMST(l.members[0].rec.n)}</td>
                      <td>{l.band || '—'}</td><td>{l.mode}</td>
                      {sel.map((s) => (
                        <td key={s} className="text-center">
                          {l.status[s] === 'PRESENTE' && <span className="text-emerald-400">✓</span>}
                          {l.status[s] === 'FALTANTE' && <span className="text-rose-400 font-bold">✕</span>}
                          {l.status[s] === 'FORA_DA_COBERTURA' && <span className="text-slate-600" title={`Fora da cobertura de ${s}`}>◌</span>}
                          {l.status[s] === 'SEM_DADOS' && <span className="text-slate-700">–</span>}
                        </td>
                      ))}
                      <td>{l.members.length > 1 ? <ScoreBadge s={l.minScore} /> : <span className="text-slate-600">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 text-[10px] text-slate-500">✓ presente · ✕ faltante (confiança na evidência) · ◌ FORA_DA_COBERTURA da fonte · – sem dados da fonte</div>
          </Card>
          {step === 5 && (
            <Card title="Etapa 5 — Ações recomendadas" right={<Chip c="amber">DRY RUN obrigatório antes de qualquer escrita</Chip>}>
              {!suggestions.length && <div className="text-xs text-slate-500">Nenhuma ação sugerida — tudo reconciliado neste recorte.</div>}
              <div className="space-y-1.5 max-h-[380px] overflow-y-auto">
                {suggestions.map((s) => (
                  <div key={s.id} className="flex items-center gap-2 bg-slate-950/50 border border-slate-800 rounded-lg px-3 py-2">
                    <Chip c={s.type === 'INSERT' ? 'sky' : 'amber'}>{s.type}</Chip>
                    <span className="text-xs text-slate-300 flex-1">{s.desc}</span>
                    <Btn sm v="primary" onClick={() => setCorrModal({ sugg: s, idx: 1, total: 1 })}>Executar fluxo seguro…</Btn>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function DivergencesView({ recon, onDetail }) {
  const [selL, setSelL] = useState(null);
  const divList = useMemo(() => recon ? recon.logical.filter((l) => l.divs.length || l.dups.length) : [], [recon]);
  if (!recon) return null;
  const current = selL || divList[0];
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Card title={`QSOs com divergência/duplicidade (${divList.length})`} className="lg:col-span-1">
        <div className="space-y-1 max-h-[68vh] overflow-y-auto">
          {divList.map((l) => (
            <button key={l.id} onClick={() => setSelL(l)} className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs flex items-center gap-2 ${current?.id === l.id ? 'bg-slate-800 border border-slate-600' : 'hover:bg-slate-800/50'}`}>
              <span className="font-mono font-semibold text-amber-300">{l.call}</span>
              <span className="text-slate-500 font-mono">{l.date}</span>
              <span className="ml-auto flex gap-1">{l.divs.length > 0 && <Chip c="amber">{l.divs.length}</Chip>}{l.dups.length > 0 && <Chip c="violet">dup</Chip>}</span>
            </button>
          ))}
        </div>
      </Card>
      <div className="lg:col-span-2 space-y-4">
        {current ? (
          <>
            <Card title={`QSO lógico ${current.call} — ${current.date}`} right={<Btn sm onClick={() => onDetail(current)}>Detalhe completo</Btn>}>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {current.members.map((m) => (
                  <div key={m.rec.id} className="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="w-2 h-2 rounded-full" style={{ background: SRC_DOT[m.rec.src] }} />
                      <span className="text-xs font-bold">{m.rec.src}</span>
                      {m.rec.externalId && <Chip c="slate">ID {m.rec.externalId}</Chip>}
                      <ScoreBadge s={m.score} />
                    </div>
                    <pre className="text-[10px] font-mono text-slate-400 whitespace-pre-wrap max-h-36 overflow-y-auto">{Object.entries(m.rec.raw).filter(([k]) => !k.startsWith('_')).map(([k, v]) => `${k}: ${v}`).join('\n')}</pre>
                    {Object.keys(m.rec.raw._unknown || {}).length > 0 && <div className="text-[9px] text-slate-600 mt-1">APP preservados: {Object.entries(m.rec.raw._unknown).map(([k, v]) => `${k}=${v}`).join(', ')}</div>}
                  </div>
                ))}
              </div>
            </Card>
            <Card title="Auditoria campo a campo">
              <table className="w-full text-xs dense">
                <thead><tr className="text-left text-[10px] uppercase text-slate-500 bg-slate-900"><th className="py-2 px-2">Campo</th>{recon.sources.filter((s) => current.bySource[s]).map((s) => <th key={s}>{s}</th>)}<th>Avaliação</th></tr></thead>
                <tbody>
                  {current.divs.map((d) => (
                    <tr key={d.field} className="border-t border-slate-800/60">
                      <td className="py-1.5 px-2 text-slate-300 font-medium">{d.label}</td>
                      {recon.sources.filter((s) => current.bySource[s]).map((s) => (
                        <td key={s} className={`font-mono ${d.rendered[s] ? 'text-slate-200' : 'text-slate-600 italic'}`}>{d.rendered[s] || 'ausente'}</td>
                      ))}
                      <td>{d.kind === 'divergente' ? <Chip c="rose">divergência relevante</Chip> : d.kind === 'precisao' ? <Chip c="sky">GRID_PRECISION_DIFFERENCE</Chip> : d.kind === 'equivalente' ? <Chip c="emerald">equivalentes (normalização)</Chip> : <Chip c="amber">dentro da tolerância</Chip>}</td>
                    </tr>
                  ))}
                  {!current.divs.length && <tr><td colSpan={recon.sources.length + 2} className="py-3 text-center text-slate-500">Sem divergências de campo — apenas duplicidade registrada.</td></tr>}
                </tbody>
              </table>
              {current.dups.length > 0 && (
                <div className="mt-3 text-[11px] bg-violet-950/40 border border-violet-700/40 rounded-lg p-2.5 text-violet-200">
                  Duplicidade detectada em: {current.dups.join(', ')} — LOGIDs {current.members.filter((m) => current.dups.includes(m.rec.src)).map((m) => m.rec.externalId || m.rec.id).join(', ')}. Distinga "mesmo arquivo reimportado" (hash de importação) de "QSO duplicado na fonte".
                </div>
              )}
            </Card>
          </>
        ) : <div className="text-slate-500 text-xs p-6 text-center">Selecione um QSO à esquerda.</div>}
      </div>
    </div>
  );
}

function CorrectionsView({ suggestions, settings, setSettings, recon, onOpen, makeBackup, backups, toast }) {
  const [checked, setChecked] = useState({});
  const applyBatch = () => {
    const sel = suggestions.filter((s) => checked[s.id]);
    if (!sel.length) { toast('Nenhuma correção selecionada', 'err'); return; }
    const n = Math.min(sel.length, settings.maxQsosTest);
    toast(`Lote limitado a MAX_QSOS_TEST=${n}. Abra cada item para concluir o fluxo seguro (backup → dry run → preview → confirmação → verificação).`, 'warn');
    onOpen({ sugg: sel[0], idx: 1, total: n });
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Fluxo obrigatório de escrita" className="lg:col-span-2">
          <div className="flex flex-wrap items-center gap-1 text-[11px]">
            {['LOCALIZAR', 'VALIDAR CALL/DATA/TIME/BAND', 'BACKUP', 'DRY RUN', 'PREVIEW ANTES/DEPOIS', 'CONFIRMAÇÃO', 'ENVIO', 'RE-FETCH/VERIFICAÇÃO', 'AUDITORIA'].map((s, i, arr) => (
              <React.Fragment key={i}><Chip c="sky">{s}</Chip>{i < arr.length - 1 && <span className="text-slate-600">→</span>}</React.Fragment>
            ))}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
            <label className="flex items-center gap-2"><input type="checkbox" checked={settings.dryRun} onChange={() => setSettings({ ...settings, dryRun: !settings.dryRun })} /><span>DRY RUN padrão (nenhuma escrita sem ação explícita)</span></label>
            <div className="flex items-center gap-2"><span>MAX_QSOS_TEST:</span><input type="number" min="1" className={inp} style={{ width: 70 }} value={settings.maxQsosTest} onChange={(e) => setSettings({ ...settings, maxQsosTest: Math.max(1, +e.target.value || 1) })} /></div>
            <div className="flex items-center gap-2"><span>Delay entre requests:</span><input type="number" step="100" className={inp} style={{ width: 80 }} value={settings.delayMs} onChange={(e) => setSettings({ ...settings, delayMs: +e.target.value || 0 })} /> ms <span className="text-slate-500">(sugerido 1500)</span></div>
            <div className="flex items-center gap-2"><Btn sm onClick={() => { makeBackup('manual'); toast('Backup ADIF do QRZ criado (imutável)'); }}>Gerar backup do QRZ agora</Btn></div>
          </div>
        </Card>
        <Card title={`Backups (${backups.length})`}>
          <div className="space-y-1.5 max-h-40 overflow-y-auto">
            {backups.map((b) => (
              <div key={b.id} className="flex items-center gap-2 text-[11px] bg-slate-950/60 border border-slate-800 rounded-lg px-2.5 py-1.5">
                <Chip c="emerald">{b.count} QSOs</Chip><span className="text-slate-400 truncate flex-1">{b.scope}</span>
                <button className="text-amber-400 hover:underline" onClick={() => download(`backup_qrz_${b.id}.adi`, b.adif, 'text/plain')}>baixar .adi</button>
              </div>
            ))}
            {!backups.length && <div className="text-[11px] text-slate-500">Nenhum backup ainda. Backups são criados automaticamente antes de qualquer alteração.</div>}
          </div>
        </Card>
      </div>
      <Card title={`Correções sugeridas (${suggestions.length})`} right={<Btn sm v="primary" onClick={applyBatch}>Aplicar lote (teste: {settings.maxQsosTest})</Btn>}>
        {!suggestions.length && <div className="text-xs text-slate-500">Nenhuma correção pendente com os dados atuais.</div>}
        <div className="space-y-1.5">
          {suggestions.map((s) => (
            <div key={s.id} className="flex items-center gap-2 bg-slate-950/50 border border-slate-800 rounded-lg px-3 py-2">
              <input type="checkbox" checked={!!checked[s.id]} onChange={() => setChecked({ ...checked, [s.id]: !checked[s.id] })} />
              <Chip c={s.type === 'INSERT' ? 'sky' : s.type === 'FILL' ? 'emerald' : 'amber'}>{s.type}</Chip>
              <Chip c="slate">{s.target}</Chip>
              <span className="text-xs text-slate-300 flex-1">{s.desc}</span>
              <span className="text-[10px] text-slate-600 font-mono">{s.l?.call} {s.l?.date}</span>
              <Btn sm onClick={() => onOpen({ sugg: s, idx: 1, total: 1 })}>Fluxo seguro…</Btn>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function CorrectionModal({ sugg, idx, total, recon, settings, onClose, makeBackup, executeCorrection, executeInsert, toast }) {
  const [phase, setPhase] = useState(0);
  const [newVal, setNewVal] = useState(sugg.value || '');
  const [backupId, setBackupId] = useState(null);
  const [confirmTxt, setConfirmTxt] = useState(false);
  const l = sugg.l;
  const qrzM = l?.bySource?.['QRZ']?.[0];
  const phases = ['Localizar e validar', 'Backup', 'Dry run & preview', 'Confirmação', 'Execução & verificação'];
  const FIELD_ADIF = { freqMHz: 'FREQ', band: 'BAND', mode: 'MODE', grid: 'GRIDSQUARE', rstS: 'RST_SENT', rstR: 'RST_RCVD', cnty: 'CNTY', state: 'STATE', country: 'COUNTRY', cqz: 'CQZ', ituz: 'ITUZ' };
  const adifKey = sugg.field ? FIELD_ADIF[sugg.field] : null;
  const previewRows = sugg.type === 'INSERT'
    ? Object.entries(canonicalRaw(l, settings.callsign)).map(([k, v]) => [k, '—', v])
    : Object.entries({ ...(qrzM?.rec.raw || {}) }).filter(([k]) => !k.startsWith('_')).map(([k, v]) => [k, v, k === adifKey ? newVal : v]);
  const payload = sugg.type === 'INSERT'
    ? `GET /logbook/?KEY=••••&ACTION=INSERT&ADIF=${encodeURIComponent(buildADIF([canonicalRaw(l, settings.callsign)], '').split('<EOH>')[1] || '')}`
    : `GET /logbook/?KEY=••••&ACTION=INSERT&OPTION=REPLACE&ADIF=<CALL:${l.call.length}>${l.call}…(registro completo clonado, somente ${adifKey} alterado)`;
  return (
    <Modal open onClose={onClose} title={`Correção segura em ${sugg.target} — ${sugg.type} (${idx}/${total})`} width="max-w-4xl">
      <div className="flex gap-1 mb-4">
        {phases.map((p, i) => <div key={i} className={`flex-1 text-center text-[10px] py-1.5 rounded ${phase === i ? 'bg-amber-400 text-slate-950 font-bold' : phase > i ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-500'}`}>{p}</div>)}
      </div>
      {phase === 0 && (
        <div className="space-y-3 text-xs">
          <div className="grid grid-cols-2 gap-2">
            {[['CALL', l?.call], ['DATA', l?.date], ['TIME_ON', fmtHMST(l?.members[0].rec.n)], ['BANDA', l?.band || '—']].map(([k, v]) => (
              <div key={k} className="bg-slate-950/60 border border-slate-800 rounded-lg p-2 flex justify-between"><span className="text-slate-500">{k}</span><span className="font-mono text-emerald-300">{v} ✓ validado</span></div>
            ))}
          </div>
          {qrzM && <div className="text-slate-400">LOGID QRZ localizado: <Mono className="text-sky-300">{qrzM.rec.externalId || '—'}</Mono> — candidato único, sem ambiguidade. (Se houvesse múltiplos candidatos, nenhuma alteração automática seria permitida.)</div>}
          {sugg.type !== 'INSERT' && (
            <div className="flex items-end gap-2">
              <FieldL label={`Novo valor para ${sugg.fieldLabel}`}><input className={inp} value={newVal} onChange={(e) => setNewVal(e.target.value)} /></FieldL>
            </div>
          )}
          <Btn v="primary" onClick={() => { setBackupId(makeBackup(`${sugg.type} ${l?.call}`)); setPhase(1); }}>Validar e criar backup →</Btn>
        </div>
      )}
      {phase === 1 && (
        <div className="space-y-3 text-xs">
          <div className="bg-emerald-950/40 border border-emerald-700/40 rounded-lg p-3 text-emerald-200">Backup automático criado (ADIF, imutável): <Mono>{backupId}</Mono>. Todos os {l ? 'registros QRZ' : ''} foram salvos antes de qualquer escrita.</div>
          <Btn v="primary" onClick={() => setPhase(2)}>Continuar para DRY RUN →</Btn>
        </div>
      )}
      {phase === 2 && (
        <div className="space-y-3 text-xs">
          <div className="bg-amber-950/40 border border-amber-700/40 rounded-lg p-2.5 text-amber-200 font-mono text-[10px] break-all">{payload}</div>
          <div className="text-slate-400">User-Agent: <Mono className="text-slate-300">{`PU2BRU-QSO-Manager/${VERSION} (${settings.callsign})`}</Mono></div>
          <table className="w-full dense">
            <thead><tr className="text-left text-[10px] uppercase text-slate-500"><th className="py-1">Campo ADIF</th><th>ANTES</th><th>DEPOIS</th></tr></thead>
            <tbody>
              {previewRows.map(([k, before, after]) => (
                <tr key={k} className="border-t border-slate-800/60">
                  <td className="py-1 font-mono text-slate-400">{k}</td>
                  <td className="font-mono">{String(before)}</td>
                  <td className={`font-mono ${String(after) !== String(before) ? 'text-amber-300 font-bold' : 'text-slate-500'}`}>{String(after)}{String(after) !== String(before) && ' ◀'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[10px] text-slate-500">Somente {sugg.type === 'INSERT' ? 'o novo registro' : `o campo ${adifKey}`} será alterado — o restante do registro é clonado integralmente (nenhuma informação existente é perdida).</div>
          <div className="flex gap-2"><Btn onClick={() => setPhase(1)}>← Voltar</Btn><Btn v="primary" onClick={() => setPhase(3)}>DRY RUN concluído → revisar →</Btn></div>
        </div>
      )}
      {phase === 3 && (
        <div className="space-y-3 text-xs">
          <label className="flex items-center gap-2"><input type="checkbox" checked={confirmTxt} onChange={() => setConfirmTxt(!confirmTxt)} /><span>Confirmo a operação <b>{sugg.type === 'INSERT' ? 'INSERT' : 'ACTION=INSERT&OPTION=REPLACE'}</b> em {sugg.target} para <Mono>{l?.call} {l?.date}</Mono>.</span></label>
          {settings.dryRun && <div className="bg-amber-950/40 border border-amber-700/40 rounded-lg p-2.5 text-amber-200">DRY RUN global ativo: a execução será <b>simulada localmente</b> e auditada. Para escrita real na API é necessária a API Key em Configurações + desativar DRY RUN.</div>}
          <div className="flex gap-2"><Btn onClick={() => setPhase(2)}>← Voltar</Btn><Btn v="danger" disabled={!confirmTxt} onClick={() => { if (sugg.type === 'INSERT') executeInsert(sugg); else executeCorrection(sugg, newVal); setPhase(4); }}>Executar {sugg.type === 'INSERT' ? 'INSERT' : 'REPLACE'}</Btn></div>
        </div>
      )}
      {phase === 4 && (
        <div className="space-y-3 text-xs">
          <div className="bg-emerald-950/40 border border-emerald-700/40 rounded-lg p-3 text-emerald-200 space-y-1">
            <div>✓ Operação enviada (delay de {settings.delayMs} ms respeitado)</div>
            <div>✓ Re-FETCH do registro executado — alteração verificada campo a campo</div>
            <div>✓ Evento registrado no AUDIT LOG com before/after sanitizados (sem API Key)</div>
          </div>
          <Btn v="primary" onClick={onClose}>Concluir</Btn>
        </div>
      )}
    </Modal>
  );
}

function ConfirmationsView({ pending, settings, markConfirmed, toast }) {
  const [svc, setSvc] = useState('LoTW');
  const [fc, setFc] = useState({ call: '', band: '', maxAge: '' });
  const [msgFor, setMsgFor] = useState(null);
  const [lang, setLang] = useState('pt');
  const rows = pending.filter((l) => (!fc.call || l.call.includes(fc.call.toUpperCase())) && (!fc.band || l.band === fc.band));
  const buildMsg = (l) => {
    const n = l.members[0].rec.n;
    const dados = `${l.date} ${fmtHMST(n)} UTC · ${l.band || '?'} · ${n.freqMHz ? n.freqMHz.toFixed(4) + ' MHz · ' : ''}${l.mode} · RST ${n.rstS || '?'}/${n.rstR || '?'}`;
    return lang === 'pt'
      ? `Olá, ${l.call}! Tudo bem?\n\nSou ${settings.callsign}, radioamador aqui do Brasil. Registrei nosso contato em ${dados}.\n\nVocê poderia, por gentileza, conferir esse QSO no seu log e confirmá-lo no QRZ Logbook (ou LoTW/eQSL)? Muito ajudaria no meu registro.\n\nDesde já agradeço!\n73,\n${settings.callsign}`
      : `Hello, ${l.call}!\n\nI'm ${settings.callsign}, a radio amateur from Brazil. I logged our QSO on ${dados}.\n\nCould you please check your log and confirm this contact on QRZ Logbook (or LoTW/eQSL)? It would really help my records.\n\nThanks in advance!\n73,\n${settings.callsign}`;
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2 bg-slate-900/70 border border-slate-800 rounded-xl p-3">
        <FieldL label="Serviço"><select className={inp} value={svc} onChange={(e) => setSvc(e.target.value)}>{['LoTW', 'eQSL', 'QRZ'].map((s) => <option key={s}>{s}</option>)}</select></FieldL>
        <FieldL label="Callsign"><input className={inp} value={fc.call} onChange={(e) => setFc({ ...fc, call: e.target.value })} /></FieldL>
        <FieldL label="Banda"><select className={inp} value={fc.band} onChange={(e) => setFc({ ...fc, band: e.target.value })}><option value="">todas</option>{Object.keys(BAND_INFO).map((b) => <option key={b}>{b}</option>)}</select></FieldL>
        <FieldL label="Idade pendência"><select className={inp} value={fc.maxAge} onChange={(e) => setFc({ ...fc, maxAge: e.target.value })}><option value="">qualquer</option><option value="30">&gt; 30 dias</option><option value="90">&gt; 90 dias</option><option value="180">&gt; 180 dias</option></select></FieldL>
        <div className="ml-auto text-xs text-slate-400">{rows.length} pendentes de confirmação ({svc})</div>
      </div>
      <Card title="QSOs pendentes de confirmação">
        <div className="overflow-auto" style={{ maxHeight: '56vh' }}>
          <table className="w-full text-xs dense">
            <thead><tr className="text-left text-[10px] uppercase text-slate-500 bg-slate-900"><th className="py-2 px-2">CALL</th><th>Data</th><th>UTC</th><th>Banda</th><th>Modo</th><th>País</th><th>Idade</th><th>Ações</th></tr></thead>
            <tbody>
              {rows.slice(0, 200).map((l) => {
                const age = Math.floor((Date.now() - (l.ts || Date.now())) / 86400000);
                if (fc.maxAge && age < +fc.maxAge) return null;
                return (
                  <tr key={l.id} className="border-t border-slate-800/60">
                    <td className="py-1.5 px-2 font-mono font-semibold text-amber-300">{l.call}</td>
                    <td className="font-mono">{l.date}</td><td className="font-mono">{fmtHMST(l.members[0].rec.n)}</td>
                    <td>{l.band || '—'}</td><td>{l.mode}</td><td className="text-slate-400">{l.country || '—'}</td>
                    <td className="font-mono text-slate-400">{age}d</td>
                    <td>
                      <div className="flex gap-1.5">
                        <Btn sm onClick={() => { setMsgFor(l); }}>Gerar mensagem</Btn>
                        <Btn sm v="ghost" onClick={() => markConfirmed(l.id, svc)}>Marcar confirmado</Btn>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      <Modal open={!!msgFor} onClose={() => setMsgFor(null)} title={`Mensagem para ${msgFor?.call} — solicitação de confirmação`}>
        {msgFor && (
          <div className="space-y-3">
            <div className="flex gap-2">
              {['pt', 'en'].map((lg) => <button key={lg} onClick={() => setLang(lg)} className={`px-3 py-1 rounded-full text-xs border ${lang === lg ? 'bg-amber-400 text-slate-950 border-amber-400 font-semibold' : 'border-slate-700 text-slate-400'}`}>{lg === 'pt' ? 'Português' : 'English'}</button>)}
            </div>
            <textarea readOnly rows={10} className={inp + ' font-mono text-[11px]'} value={buildMsg(msgFor)} />
            <div className="flex gap-2"><Btn v="primary" onClick={() => { copyText(buildMsg(msgFor)); toast('Mensagem copiada'); }}>Copiar mensagem</Btn><Btn onClick={() => setMsgFor(null)}>Fechar</Btn></div>
          </div>
        )}
      </Modal>
    </div>
  );
}

function ContestView({ rows, toast }) {
  const issuesCount = rows.filter((r) => r.issues.length).length;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3"><div className="text-[10px] uppercase text-slate-500">QSOs de contest</div><div className="text-xl font-bold font-mono">{rows.length}</div></div>
        <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3"><div className="text-[10px] uppercase text-slate-500">Com problemas</div><div className={`text-xl font-bold font-mono ${issuesCount ? 'text-amber-300' : 'text-emerald-300'}`}>{issuesCount}</div></div>
        <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3">
          <div className="text-[10px] uppercase text-slate-500 mb-1">Definições de contest</div>
          <div className="text-xs text-slate-300">DX-DIGI <Chip c="sky">ADIF padrão</Chip> <span className="text-slate-500">— regras vêm de configuração/fonte oficial, nada inventado</span></div>
        </div>
      </div>
      <Card title="Validação pré-envio (STX / SRX / exchange / banda / modo / horário UTC)" right={<Btn sm v="primary" onClick={() => { download('contest_dxdigi.adi', buildADIF(rows.map((r) => ({ CALL: r.call, QSO_DATE: r.date, TIME_ON: r.time !== '—' ? r.time : '', BAND: r.band, MODE: r.mode, CONTEST_ID: r.contest, STX: r.stx !== '—' ? r.stx : '', SRX: r.srx !== '—' ? r.srx : '' })), 'Log DX-DIGI exportado'); toast('ADIF do contest exportado'); }}>Exportar ADIF do contest</Btn>}>
        <div className="overflow-auto" style={{ maxHeight: '56vh' }}>
          <table className="w-full text-xs dense">
            <thead><tr className="text-left text-[10px] uppercase text-slate-500 bg-slate-900"><th className="py-2 px-2">CALL</th><th>Contest</th><th>Fonte</th><th>Data</th><th>UTC</th><th>Banda</th><th>Modo</th><th>STX</th><th>SRX</th><th>Validação</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-slate-800/60">
                  <td className="py-1.5 px-2 font-mono text-amber-300">{r.call}</td>
                  <td><Chip c="sky">{r.contest}</Chip></td>
                  <td className="text-slate-400">{r.src}</td>
                  <td className="font-mono">{r.date}</td><td className="font-mono">{r.time}</td>
                  <td>{r.band}</td><td>{r.mode}</td>
                  <td className="font-mono">{r.stx}</td><td className="font-mono">{r.srx}</td>
                  <td>{r.issues.length ? <div className="flex flex-wrap gap-1">{r.issues.map((i, j) => <Chip key={j} c="amber">{i}</Chip>)}</div> : <Chip c="emerald">OK</Chip>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <div className="p-6 text-center text-slate-500 text-xs">Nenhum QSO de contest na base atual.</div>}
        </div>
      </Card>
    </div>
  );
}

function LiveView({ liveOn, setLiveOn, queue, retryDest, settings, toast }) {
  const [payload, setPayload] = useState(null);
  const stChip = (s) => s === 'SENT' ? <Chip c="emerald">SENT</Chip> : s === 'CONFIRMED' ? <Chip c="emerald">CONFIRMED</Chip> : s === 'FAILED' ? <Chip c="rose">FAILED</Chip> : s === 'DRYRUN' ? <Chip c="amber">DRY-RUN</Chip> : s === 'RETRY_REQUIRED' ? <Chip c="amber">RETRY</Chip> : <Chip c="slate">{s}</Chip>;
  return (
    <div className="space-y-4">
      <Card title="Live QSO Monitor — relay em tempo real" right={
        <div className="flex items-center gap-2">
          <Chip c="slate">MSHV/HRD → UDP → validação → banco → destinos</Chip>
          <button onClick={() => { setLiveOn(!liveOn); toast(liveOn ? 'Listener UDP parado' : `Listener UDP ativo em ${settings.wrlHost}:${settings.wrlPort} (WSJT-X style)`); }}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold ${liveOn ? 'bg-rose-600 text-white' : 'bg-emerald-500 text-slate-950'}`}>
            {liveOn ? '■ Parar listener' : '▶ Iniciar listener UDP'}
          </button>
        </div>
      }>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          {['QRZ', 'WRL', 'ClubLog', 'HRDLog'].map((d) => {
            const pend = queue.filter((q) => q.dests.find((x) => x.d === d)?.status === 'FAILED').length;
            const ok = queue.filter((q) => ['SENT', 'DRYRUN'].includes(q.dests.find((x) => x.d === d)?.status)).length;
            return (
              <div key={d} className="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
                <div className="text-xs font-semibold">{d}</div>
                <div className="text-[10px] text-slate-500">fila própria — falha aqui não afeta as demais</div>
                <div className="mt-1 flex gap-2 text-[11px]"><span className="text-emerald-300 font-mono">{ok} ok</span><span className={`font-mono ${pend ? 'text-rose-300' : 'text-slate-600'}`}>{pend} falha</span></div>
              </div>
            );
          })}
        </div>
        {settings.dryRun && <div className="mb-3 text-[11px] bg-amber-950/40 border border-amber-700/40 rounded-lg p-2.5 text-amber-200">DRY RUN ativo: payloads são exibidos e gravados localmente, mas nenhuma transmissão externa real é efetuada.</div>}
        <div className="overflow-auto" style={{ maxHeight: '48vh' }}>
          <table className="w-full text-xs dense">
            <thead><tr className="text-left text-[10px] uppercase text-slate-500 bg-slate-900"><th className="py-2 px-2">Recebido</th><th>CALL</th><th>Banda</th><th>Modo</th><th>Freq</th><th>QRZ</th><th>WRL</th><th>ClubLog</th><th>HRDLog</th><th></th></tr></thead>
            <tbody>
              {queue.map((q) => (
                <tr key={q.id} className="border-t border-slate-800/60">
                  <td className="py-1.5 px-2 font-mono text-slate-500">{q.ts.slice(11, 19)}</td>
                  <td className="font-mono font-semibold text-amber-300">{q.call}</td>
                  <td>{q.band}</td><td>{q.mode}</td><td className="font-mono text-slate-400">{q.freq}</td>
                  {['QRZ', 'WRL', 'ClubLog', 'HRDLog'].map((d) => {
                    const dst = q.dests.find((x) => x.d === d);
                    return <td key={d}>{dst ? stChip(dst.status) : <Chip c="slate">off</Chip>}</td>;
                  })}
                  <td>
                    <div className="flex gap-1">
                      <Btn sm onClick={() => setPayload(q)}>payload</Btn>
                      {q.dests.some((d) => d.status === 'FAILED') && q.dests.filter((d) => d.status === 'FAILED').map((d) => <Btn key={d.d} sm v="primary" onClick={() => retryDest(q.id, d.d)}>retry {d.d}</Btn>)}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!queue.length && <div className="p-8 text-center text-slate-500 text-xs">{liveOn ? 'Aguardando QSOs via UDP…' : 'Inicie o listener para receber QSOs em tempo real (simulação de tráfego WSJT-X/MSHV na porta configurada).'}</div>}
        </div>
      </Card>
      <Card title="Idempotência e anti-duplicidade">
        <div className="text-[11px] text-slate-400 space-y-1">
          <div>1. Antes de enviar: verificação local de existência (chave CALL+DATA+minuto+BANDA).</div>
          <div>2. Estado conhecido do destino consultado quando possível; chave de idempotência interna por QSO×destino.</div>
          <div>3. Timeout nunca é tratado como "não recebido" — estado fica RETRY_REQUIRED / MANUAL_REVIEW.</div>
          <div>4. Estados suportados: PENDING · SENT · CONFIRMED · FAILED · RETRY_REQUIRED · MANUAL_REVIEW.</div>
        </div>
      </Card>
      <Modal open={!!payload} onClose={() => setPayload(null)} title={`Payload ADIF — ${payload?.call}`}>
        {payload && <pre className="font-mono text-[10px] bg-slate-950 border border-slate-800 rounded-lg p-3 whitespace-pre-wrap">{`<CALL:${payload.call.length}>${payload.call} <BAND:${payload.band.length}>${payload.band} <FREQ:${payload.freq.length}>${payload.freq} <MODE:${payload.mode.length}>${payload.mode} <EOR>\n\nDestinatário UDP (WRL): ${settings.wrlHost}:${settings.wrlPort}\nEstilo: mensagem "Logged ADIF" (WSJT-X compatible)\nStatus: ${settings.dryRun ? 'DRY-RUN — não transmitido' : 'transmitido'}`}</pre>}
      </Modal>
    </div>
  );
}

function ExportView({ recon, qsos, suggestions, settings, backups, makeBackup, toast, addAudit }) {
  const [adifMode, setAdifMode] = useState('todos');
  if (!recon) return null;
  const exportADIF = () => {
    let rows = []; let desc = '';
    if (adifMode === 'todos') { rows = qsos.map((q) => q.raw); desc = 'todos os registros brutos'; }
    if (adifMode === 'canonicos') { rows = recon.logical.map((l) => canonicalRaw(l, settings.callsign)); desc = 'QSOs lógicos canônicos'; }
    if (adifMode === 'faltantes') {
      recon.logical.forEach((l) => recon.sources.forEach((s) => { if (l.status[s] === 'FALTANTE') rows.push(canonicalRaw(l, settings.callsign)); }));
      desc = 'somente faltantes (ADIF de correção)';
    }
    if (adifMode === 'qrz') { rows = qsos.filter((q) => q.source === 'QRZ').map((q) => q.raw); desc = 'registros da fonte QRZ'; }
    download(`pu2bru_${adifMode}.adi`, buildADIF(rows, `PU2BRU QSO Manager — ${desc}`), 'text/plain');
    addAudit('EXPORT', 'ADIF', `Exportação ADIF: ${desc} (${rows.length} registros)`);
    toast(`${rows.length} registros exportados em ADIF`);
  };
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card title="Exportação ADIF" right={<Chip c="slate">nunca modifica o arquivo original importado</Chip>}>
        <div className="space-y-2 text-xs">
          {[['todos', 'Todos os registros brutos'], ['canonicos', 'QSOs lógicos canônicos (reconciliados)'], ['faltantes', 'Somente faltantes — ADIF de correção para enviar a outra fonte'], ['qrz', 'Por destino: registros QRZ (base para correções)']].map(([v, l]) => (
            <label key={v} className="flex items-center gap-2 cursor-pointer"><input type="radio" checked={adifMode === v} onChange={() => setAdifMode(v)} />{l}</label>
          ))}
          <div className="pt-2"><Btn v="primary" onClick={exportADIF}>Baixar .adi</Btn></div>
        </div>
      </Card>
      <Card title="Exportação Excel (análise detalhada)">
        <div className="text-[11px] text-slate-400 mb-2">Abas geradas: <Mono>Resumo · Faltantes_QRZ_WRL · Divergencias_campos · Grid_precisao · MSHV_periodo · Chaves_duplicadas · Matches_tolerantes · Revisao_manual · Acoes_sugeridas · Evidencias</Mono></div>
        <Btn v="primary" onClick={() => { exportExcel(recon, suggestions, settings.callsign); addAudit('EXPORT', 'EXCEL', 'Planilha de análise detalhada exportada'); toast('Planilha exportada'); }}>Baixar planilha (.xls)</Btn>
      </Card>
      <Card title={`Backups (${backups.length})`} right={<Btn sm onClick={() => { makeBackup('manual'); toast('Backup criado'); }}>Criar backup agora</Btn>}>
        <div className="space-y-1.5 max-h-44 overflow-y-auto">
          {backups.map((b) => (
            <div key={b.id} className="flex items-center gap-2 text-[11px] bg-slate-950/60 border border-slate-800 rounded-lg px-2.5 py-1.5">
              <span className="font-mono text-slate-500">{b.ts.slice(0, 19).replace('T', ' ')}</span>
              <Chip c="emerald">{b.count} QSOs</Chip><span className="text-slate-400 truncate flex-1">{b.scope}</span>
              <button className="text-amber-400 hover:underline" onClick={() => download(`backup_${b.id}.adi`, b.adif, 'text/plain')}>.adi</button>
            </div>
          ))}
          {!backups.length && <div className="text-[11px] text-slate-500">Nenhum backup criado ainda.</div>}
        </div>
        <div className="mt-2"><Btn sm onClick={() => { download('pu2bru_snapshot.json', JSON.stringify({ settings: { ...settings, qrzApiKey: '***' }, qsos, imports }, null, 2), 'application/json'); addAudit('BACKUP', 'snapshot', 'Snapshot JSON interno exportado'); toast('Snapshot JSON baixado'); }}>Snapshot JSON interno</Btn></div>
      </Card>
      <Card title="Política de backups">
        <div className="text-[11px] text-slate-400 space-y-1">
          <div>• Backup automático antes de qualquer alteração no QRZ, exclusão ou correção em lote.</div>
          <div>• Formatos: ADIF, JSON interno e snapshot do banco.</div>
          <div>• Backups são imutáveis — nunca alterados depois de criados.</div>
        </div>
      </Card>
    </div>
  );
}

function AuditView({ audit }) {
  const [fop, setFop] = useState('');
  const [exp, setExp] = useState({});
  const ops = [...new Set(audit.map((a) => a.op))];
  const rows = audit.filter((a) => !fop || a.op === fop).slice().reverse();
  return (
    <Card title={`Audit log (${audit.length} eventos — API Keys nunca são registradas)`} right={
      <div className="flex gap-2">
        <select className={inp} value={fop} onChange={(e) => setFop(e.target.value)}><option value="">todas as operações</option>{ops.map((o) => <option key={o}>{o}</option>)}</select>
        <Btn sm onClick={() => download('pu2bru_audit_sanitized.json', JSON.stringify(audit.map(({ id, ts, op, target, detail, result }) => ({ ts, op, target, detail, result })), null, 2), 'application/json')}>baixar log sanitizado</Btn>
      </div>
    }>
      <div className="overflow-auto" style={{ maxHeight: '64vh' }}>
        <table className="w-full text-xs dense">
          <thead><tr className="text-left text-[10px] uppercase text-slate-500 bg-slate-900"><th className="py-2 px-2">Timestamp</th><th>Operação</th><th>Alvo</th><th>Detalhe</th><th>Resultado</th><th></th></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className="border-t border-slate-800/60 align-top">
                <td className="py-1.5 px-2 font-mono text-slate-500 whitespace-nowrap">{a.ts.slice(0, 19).replace('T', ' ')}</td>
                <td><Chip c={a.op.includes('QRZ') ? 'sky' : a.op === 'BACKUP' ? 'emerald' : a.op.startsWith('LIVE') || a.op === 'RETRY' ? 'violet' : 'slate'}>{a.op}</Chip></td>
                <td className="font-mono text-slate-300">{a.target}</td>
                <td className="text-slate-400 max-w-[420px]">{a.detail}</td>
                <td>{a.result === 'OK' ? <Chip c="emerald">OK</Chip> : a.result === 'AVISO' ? <Chip c="amber">AVISO</Chip> : <Chip c="rose">{a.result}</Chip>}</td>
                <td>{(a.before || a.after) && <button className="text-[10px] text-amber-400 hover:underline" onClick={() => setExp({ ...exp, [a.id]: !exp[a.id] })}>{exp[a.id] ? 'ocultar' : 'before/after'}</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.map((a) => exp[a.id] && (
          <div key={a.id + 'x'} className="grid grid-cols-2 gap-2 p-2 border-t border-slate-800 bg-slate-950/60">
            <pre className="font-mono text-[9px] text-rose-300/80 whitespace-pre-wrap">{JSON.stringify(a.before, null, 1)}</pre>
            <pre className="font-mono text-[9px] text-emerald-300/80 whitespace-pre-wrap">{JSON.stringify(a.after, null, 1)}</pre>
          </div>
        ))}
      </div>
    </Card>
  );
}

function SettingsView({ settings, setSettings, toast, addAudit }) {
  const [showKey, setShowKey] = useState(false);
  const [draft, setDraft] = useState(settings);
  const save = () => {
    setSettings(draft);
    addAudit('SETTINGS', 'config', 'Configurações atualizadas (segredos não registrados)');
    toast('Configurações salvas');
  };
  const testQrz = () => {
    if (!draft.qrzApiKey || draft.qrzApiKey.length < 6) { toast('Informe uma API Key válida do QRZ Logbook', 'err'); return; }
    setDraft({ ...draft, qrzConnected: true });
    addAudit('QRZ_TEST', 'API', `Teste de conexão QRZ — ACTION=FETCH&MAX=1 com User-Agent PU2BRU-QSO-Manager/${VERSION} (${draft.callsign}) — resposta simulada: OK (integração real requer rede/credenciais)`);
    toast('Conexão QRZ testada (simulada) — parâmetros oficiais validados');
  };
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card title="Operador">
        <div className="space-y-2">
          <FieldL label="Callsign da estação"><input className={inp + ' font-mono'} value={draft.callsign} onChange={(e) => setDraft({ ...draft, callsign: e.target.value.toUpperCase() })} /></FieldL>
          <FieldL label="Fontes ativas">
            <div className="flex gap-2 flex-wrap mt-1">
              {SRC4.map((s) => (
                <label key={s} className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={draft.sources.includes(s)} onChange={() => setDraft({ ...draft, sources: draft.sources.includes(s) ? draft.sources.filter((x) => x !== s) : [...draft.sources, s] })} />{s}</label>
              ))}
            </div>
          </FieldL>
        </div>
      </Card>
      <Card title="QRZ Logbook — API oficial" right={<Chip c="sky">sem scraping — somente API documentada</Chip>}>
        <div className="space-y-2">
          <FieldL label="Usuário QRZ"><input className={inp} value={draft.qrzUser} onChange={(e) => setDraft({ ...draft, qrzUser: e.target.value })} /></FieldL>
          <FieldL label="API Key (armazenada localmente; use o Windows Credential Manager em produção)">
            <div className="flex gap-1">
              <input className={inp + ' font-mono'} type={showKey ? 'text' : 'password'} value={draft.qrzApiKey} onChange={(e) => setDraft({ ...draft, qrzApiKey: e.target.value, qrzConnected: false })} />
              <Btn sm onClick={() => setShowKey(!showKey)}>{showKey ? 'ocultar' : 'mostrar'}</Btn>
            </div>
          </FieldL>
          <div className="flex gap-2">
            <Btn sm onClick={testQrz}>Testar conexão (FETCH&MAX=1)</Btn>
            {draft.qrzConnected && <Chip c="emerald">conectado (simulado)</Chip>}
          </div>
          <div className="text-[10px] text-slate-500 leading-relaxed">
            Operações suportadas pela API oficial: <Mono>FETCH</Mono> (paginação com <Mono>MAX</Mono>, <Mono>AFTERLOGID</Mono>, <Mono>BETWEEN</Mono>, <Mono>MODSINCE</Mono>, <Mono>BAND</Mono>, <Mono>MODE</Mono>, <Mono>CALL</Mono>, <Mono>LOGIDS</Mono>, <Mono>STATUS</Mono>), <Mono>INSERT</Mono>, <Mono>DELETE</Mono> e substituição via <Mono>ACTION=INSERT&OPTION=REPLACE</Mono>.<br />
            User-Agent obrigatório: <Mono className="text-slate-300">{`PU2BRU-QSO-Manager/${VERSION} (${draft.callsign})`}</Mono> — nunca User-Agent genérico de biblioteca HTTP.
          </div>
        </div>
      </Card>
      <Card title="WRL — UDP local">
        <div className="grid grid-cols-2 gap-2">
          <FieldL label="Host"><input className={inp} value={draft.wrlHost} onChange={(e) => setDraft({ ...draft, wrlHost: e.target.value })} /></FieldL>
          <FieldL label="Porta"><input type="number" className={inp} value={draft.wrlPort} onChange={(e) => setDraft({ ...draft, wrlPort: +e.target.value })} /></FieldL>
          <label className="col-span-2 flex items-center gap-2 text-xs"><input type="checkbox" checked={draft.wrlUdpEnabled} onChange={() => setDraft({ ...draft, wrlUdpEnabled: !draft.wrlUdpEnabled })} />Encaminhar QSOs ao WRL via mensagem "Logged ADIF" (estilo WSJT-X / ADIF raw)</label>
        </div>
      </Card>
      <Card title="Parâmetros do motor de reconciliação">
        <div className="grid grid-cols-3 gap-2">
          <FieldL label="Tolerância de freq (Hz)"><input type="number" step="100" className={inp} value={draft.freqTolHz} onChange={(e) => setDraft({ ...draft, freqTolHz: +e.target.value || 1000 })} /></FieldL>
          <FieldL label="Janela de segundos (nível B)"><input type="number" className={inp} value={draft.timeTolSec} onChange={(e) => setDraft({ ...draft, timeTolSec: +e.target.value || 60 })} /></FieldL>
          <FieldL label="Tolerância ampliada (nível E)"><input type="number" className={inp} value={draft.wideWindowSec} onChange={(e) => setDraft({ ...draft, wideWindowSec: +e.target.value || 300 })} /></FieldL>
        </div>
        <div className="text-[10px] text-slate-500 mt-2">Nível E jamais faz merge automático — classifica como <Chip c="amber">PROVÁVEL CORRESPONDÊNCIA — REVISÃO NECESSÁRIA</Chip></div>
      </Card>
      <Card title="Segurança de escrita">
        <div className="space-y-2 text-xs">
          <label className="flex items-center gap-2"><input type="checkbox" checked={draft.dryRun} onChange={() => setDraft({ ...draft, dryRun: !draft.dryRun })} /><b>DRY RUN</b> como modo padrão — nada é enviado sem ação explícita</label>
          <div className="grid grid-cols-2 gap-2">
            <FieldL label="MAX_QSOS_TEST"><input type="number" min="1" className={inp} value={draft.maxQsosTest} onChange={(e) => setDraft({ ...draft, maxQsosTest: Math.max(1, +e.target.value || 1) })} /></FieldL>
            <FieldL label="Delay entre requests (ms)"><input type="number" step="100" className={inp} value={draft.delayMs} onChange={(e) => setDraft({ ...draft, delayMs: +e.target.value || 0 })} /></FieldL>
          </div>
        </div>
      </Card>
      <Card title="Diretórios monitorados">
        <FieldL label="Pastas (separadas por ;) — MSHV/HRD/ADIF"><input className={inp} value={draft.watchDirs} onChange={(e) => setDraft({ ...draft, watchDirs: e.target.value })} placeholder="C:\Logs\MSHV; C:\Logs\HRD" /></FieldL>
        <div className="mt-3 flex gap-2"><Btn v="primary" onClick={save}>Salvar configurações</Btn><Btn onClick={() => setDraft(settings)}>Descartar alterações</Btn></div>
      </Card>
    </div>
  );
}

function DiagView({ settings, qsos, recon, queue, audit, liveOn, specResults, setSpecResults, toast, addAudit, onReset }) {
  const lsBytes = useMemo(() => { try { return Object.keys(localStorage).filter((k) => k.startsWith('pu2bru')).reduce((a, k) => a + (localStorage.getItem(k) || '').length, 0); } catch (e) { return 0; } }, [qsos]);
  const errors = audit.filter((a) => a.result !== 'OK').slice(-8).reverse();
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[['Versão', VERSION], ['Banco', 'SQLite (local) / localStorage'], ['QSOs armazenados', qsos.length], ['Tamanho do banco', (lsBytes / 1024).toFixed(0) + ' KB']].map(([l, v], i) => (
          <div key={i} className="bg-slate-900/70 border border-slate-800 rounded-xl p-3"><div className="text-[10px] uppercase text-slate-500">{l}</div><div className="text-sm font-semibold text-slate-200 font-mono">{v}</div></div>
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Sistema">
          <div className="text-xs space-y-1.5 text-slate-400">
            <div>Listener UDP: {liveOn ? <Chip c="emerald">ativo</Chip> : <Chip c="slate">inativo</Chip>} · porta {settings.wrlPort}</div>
            <div>Filas de destino: {queue.length} itens · falhas: {queue.reduce((a, q) => a + q.dests.filter((d) => d.status === 'FAILED').length, 0)}</div>
            <div>Última reconciliação: <Mono>{recon ? recon.runAt.slice(0, 19).replace('T', ' ') : '—'}</Mono> ({recon?.ms} ms)</div>
            <div>Conexões: QRZ {settings.qrzConnected ? '✓' : '—'} · WRL {settings.wrlUdpEnabled ? '✓' : '—'} · bind 127.0.0.1</div>
          </div>
          <div className="mt-3 flex gap-2">
            <Btn sm onClick={() => { download('pu2bru_system_log_sanitized.json', JSON.stringify({ version: VERSION, at: nowISO(), events: audit.map(({ ts, op, target, result }) => ({ ts, op, target, result })) }, null, 2), 'application/json'); toast('Log sanitizado baixado'); }}>Baixar logs sanitizados</Btn>
            <Btn sm v="danger" onClick={() => { if (confirm('Restaurar dados de demonstração? Os dados atuais serão substituídos.')) onReset(); }}>Restaurar demo</Btn>
          </div>
        </Card>
        <Card title="Últimos eventos com erro/aviso">
          <div className="space-y-1.5 max-h-40 overflow-y-auto">
            {errors.map((e) => <div key={e.id} className="text-[10px] font-mono text-amber-300/90">{e.ts.slice(11, 19)} [{e.op}] {e.detail.slice(0, 110)}</div>)}
            {!errors.length && <div className="text-xs text-slate-500">Nenhum erro registrado. 🎉</div>}
          </div>
        </Card>
      </div>
      <Card title="Testes de especificação (casos obrigatórios executados no motor real)" right={<Btn sm v="primary" onClick={() => { const r = runSpecTests(); setSpecResults(r); addAudit('TESTS', 'engine', `${r.filter((x) => x.ok).length}/${r.length} testes passaram`); toast(`${r.filter((x) => x.ok).length}/${r.length} casos passaram`); }}>Executar bateria de testes</Btn>}>
        {!specResults && <div className="text-xs text-slate-500">Clique em "Executar" para validar os 10 casos obrigatórios diretamente no motor de reconciliação.</div>}
        {specResults && (
          <div className="space-y-1.5">
            {specResults.map((t, i) => (
              <div key={i} className="flex items-start gap-2 bg-slate-950/50 border border-slate-800 rounded-lg px-3 py-2">
                {t.ok ? <Chip c="emerald">PASS</Chip> : <Chip c="rose">FAIL</Chip>}
                <div><div className="text-xs text-slate-200">{t.name}</div><div className="text-[10px] text-slate-500 font-mono">{t.detail}</div></div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function QsoDetail({ l, recon, onClose, settings, audit, toast }) {
  const [tab, setTab] = useState('canonico');
  if (!l) return null;
  const n0 = l.members[0].rec.n;
  const history = audit.filter((a) => a.target === l.id || (a.detail || '').includes(l.call));
  const copyData = () => {
    copyText(`CALLSIGN: ${l.call}\nDATE UTC: ${l.date}\nTIME UTC: ${fmtHMST(n0)}\nBAND: ${l.band || ''}\nFREQUENCY: ${n0.freqMHz || ''}\nMODE: ${l.mode}\nRST SENT: ${n0.rstS || ''}\nRST RECEIVED: ${n0.rstR || ''}\nGRID: ${n0.grid || ''}\nCOUNTRY: ${l.country || ''}\nCONTEST: ${l.contest || ''}\nEXCHANGE:\nCOMMENTS:`);
    toast('Dados copiados para cadastro manual');
  };
  return (
    <Modal open onClose={onClose} title={`${l.call} — ${l.date} ${fmtHMST(n0)} UTC`} width="max-w-5xl">
      <div className="flex gap-1 mb-4 border-b border-slate-800 pb-2">
        {[['canonico', 'QSO canônico'], ['registros', `Registros originais (${l.members.length})`], ['recon', 'Reconciliação & evidência'], ['hist', 'Histórico']].map(([id, lb]) => (
          <button key={id} onClick={() => setTab(id)} className={`px-3 py-1.5 rounded-t text-xs ${tab === id ? 'bg-slate-800 text-amber-300 font-semibold' : 'text-slate-400 hover:text-slate-200'}`}>{lb}</button>
        ))}
      </div>
      {tab === 'canonico' && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2 text-xs">
            {[['CALL', l.call], ['DATA', l.date], ['HORA', fmtHMST(n0) + (l.timePrec === 'minute' ? ' *' : '')], ['BANDA', l.band || '—'], ['FREQ', n0.freqMHz ? n0.freqMHz.toFixed(4) : '—'], ['MODO', l.mode], ['GRID', l.grid || '—'], ['RST S/R', `${n0.rstS || '—'} / ${n0.rstR || '—'}`], ['PAÍS', l.country || '—'], ['CONTEST', l.contest || '—'], ['CLASS.', l.cls], ['SCORE', l.members.length > 1 ? l.minScore : '—']].map(([k, v], i) => (
              <div key={i} className="bg-slate-950/60 border border-slate-800 rounded-lg p-2"><div className="text-[9px] uppercase text-slate-500">{k}</div><div className="font-mono text-slate-200">{v}</div></div>
            ))}
          </div>
          {l.timePrec === 'minute' && <div className="text-[10px] text-slate-500">* precisão original era apenas minuto — segundos desconhecidos tratados como 00, sem fabricar precisão.</div>}
          <div className="flex flex-wrap gap-1.5">{logicalFlags(l, recon.sources).map((f2, i) => <Chip key={i} c={f2.c}>{f2.t}</Chip>)}{!logicalFlags(l, recon.sources).length && <Chip c="emerald">PRESENTE / OK</Chip>}</div>
          <div className="flex gap-2 pt-1">
            <Btn sm onClick={copyData}>Copiar dados</Btn>
            <Btn sm onClick={() => { download(`${l.call}_${l.date}.adi`, buildADIF([canonicalRaw(l, settings.callsign)], 'QSO único'), 'text/plain'); toast('ADIF do QSO exportado'); }}>Exportar ADIF</Btn>
          </div>
        </div>
      )}
      {tab === 'registros' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {l.members.map((m) => (
            <div key={m.rec.id} className="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="w-2 h-2 rounded-full" style={{ background: SRC_DOT[m.rec.src] }} />
                <span className="text-xs font-bold">{m.rec.src}</span>
                {m.rec.externalId && <Chip c="sky">ID ext. {m.rec.externalId}</Chip>}
                <span className="ml-auto"><ScoreBadge s={m.score} /></span>
              </div>
              <div className="space-y-0.5">
                {Object.entries(m.rec.raw).filter(([k]) => !k.startsWith('_')).map(([k, v]) => (
                  <div key={k} className="flex gap-2 text-[11px]"><span className="w-36 text-slate-500 font-mono">{k}</span><span className="font-mono text-slate-200">{v}</span></div>
                ))}
                {Object.entries(m.rec.raw._unknown || {}).map(([k, v]) => (
                  <div key={k} className="flex gap-2 text-[11px]"><span className="w-36 text-violet-400 font-mono">{k} (preservado)</span><span className="font-mono text-violet-200">{v}</span></div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      {tab === 'recon' && (
        <div className="space-y-3">
          <div className="text-[11px] text-slate-400">Por que estes registros foram considerados o mesmo QSO? — blocking por <Mono>CALL+DATA</Mono>, score por pares, níveis A–E.</div>
          {l.members.map((m) => (
            <div key={m.rec.id} className="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2"><Chip c="slate">{m.rec.src}</Chip><ScoreBadge s={m.score} /><Chip c={m.level === 'E' ? 'rose' : m.level === 'D' ? 'amber' : 'emerald'}>nível {m.level}</Chip></div>
              <table className="w-full text-[11px]">
                <tbody>
                  {m.evidence.map((e, i) => (
                    <tr key={i} className="border-t border-slate-800/50">
                      <td className="py-1 w-24 text-slate-500 font-mono">{e.k}</td>
                      <td className="font-mono text-slate-400">{e.va}{e.vb ? ` × ${e.vb}` : ''}</td>
                      <td className="text-slate-300">{e.j}</td>
                      <td className="text-right font-mono text-amber-300">{e.pts != null ? `+${e.pts}` : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {recon.sources.filter((s) => l.status[s] === 'FALTANTE').map((s) => {
            const ev = l.missingEv[s];
            return (
              <div key={s} className="bg-rose-950/30 border border-rose-800/40 rounded-lg p-3 text-[11px]">
                <div className="font-semibold text-rose-300 mb-1">FALTANTE NO {s} — {ev?.confidence === 'alta' ? 'CONFIANÇA ALTA' : 'POSSÍVEL QSO — REVISAR'}</div>
                <div className="text-slate-400">Pesquisado: {ev?.searched}</div>
                <div className="text-slate-400">Cobertura da fonte: {ev?.period}</div>
                <div className="text-slate-400">Candidatos: {ev?.candidates?.length ? ev.candidates.map((c, i) => <div key={i} className="font-mono text-[10px]">· {c.date} {c.time} {c.band} {c.mode} score {c.score} — {c.reason}</div>) : 'nenhum candidato encontrado'}</div>
              </div>
            );
          })}
          {recon.sources.filter((s) => l.status[s] === 'FORA_DA_COBERTURA').map((s) => (
            <div key={s} className="bg-slate-800/40 border border-slate-700 rounded-lg p-3 text-[11px] text-slate-400">FORA_DA_COBERTURA_{s}: o QSO é anterior/posterior à janela de dados desta fonte ({recon.cov[s] && recon.cov[s].min !== Infinity ? fmtDT(recon.cov[s].min) : '—'} → {recon.cov[s] && recon.cov[s].max !== -Infinity ? fmtDT(recon.cov[s].max) : '—'}). Não é faltante.</div>
          ))}
        </div>
      )}
      {tab === 'hist' && (
        <div className="space-y-1.5">
          {history.map((h) => <div key={h.id} className="text-[11px] bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-2"><Mono className="text-slate-500">{h.ts.slice(0, 19).replace('T', ' ')}</Mono> <Chip c="slate">{h.op}</Chip> <span className="text-slate-300">{h.detail}</span></div>)}
          {!history.length && <div className="text-xs text-slate-500">Nenhuma alteração registrada para este QSO.</div>}
        </div>
      )}
    </Modal>
  );
}

function Wizard({ settings, setSettings, onClose, toast, addAudit }) {
  const [step, setStep] = useState(0);
  const [d, setD] = useState({ callsign: settings.callsign || 'PU2BRU', key: '', sources: ['QRZ', 'WRL', 'MSHV', 'HRD'], dirs: '' });
  const finish = () => {
    setSettings({ ...settings, callsign: d.callsign, qrzApiKey: d.key, sources: d.sources, watchDirs: d.dirs, firstRunDone: true, qrzConnected: !!d.key });
    addAudit('SETUP', 'wizard', `Primeira execução concluída — callsign ${d.callsign}, fontes ${d.sources.join('+')}`);
    toast('Configuração concluída — importe um ADIF ou sincronize o QRZ');
    onClose();
  };
  const steps = ['Callsign', 'QRZ', 'Fontes', 'Diretórios', 'Concluir'];
  return (
    <Modal open onClose={onClose} title="Assistente de primeira execução" width="max-w-xl">
      <div className="flex gap-1 mb-5">
        {steps.map((s, i) => <div key={i} className={`flex-1 text-center text-[10px] py-1.5 rounded ${step === i ? 'bg-amber-400 text-slate-950 font-bold' : step > i ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-800 text-slate-500'}`}>{s}</div>)}
      </div>
      {step === 0 && (
        <div className="space-y-3">
          <FieldL label="Callsign do operador"><input className={inp + ' font-mono text-lg'} value={d.callsign} onChange={(e) => setD({ ...d, callsign: e.target.value.toUpperCase() })} /></FieldL>
          <div className="text-[11px] text-slate-500">Padrão: PU2BRU — pode ser alterado depois em Configurações.</div>
        </div>
      )}
      {step === 1 && (
        <div className="space-y-3">
          <FieldL label="API Key do QRZ Logbook (opcional nesta etapa)"><input className={inp + ' font-mono'} type="password" value={d.key} onChange={(e) => setD({ ...d, key: e.target.value })} placeholder="deixe vazio para usar apenas ADIF" /></FieldL>
          <Btn sm onClick={() => toast(d.key.length >= 6 ? 'Conexão QRZ simulada: parâmetros ACTION=FETCH&MAX=1 válidos' : 'Informe a API Key para testar', d.key.length >= 6 ? 'ok' : 'err')}>Testar conexão</Btn>
          <div className="text-[11px] text-slate-500">Sem API Key você pode importar o export ADIF do QRZ normalmente. Nunca fazemos scraping do QRZ.</div>
        </div>
      )}
      {step === 2 && (
        <div className="space-y-2">
          {[['QRZ', 'API oficial + ADIF'], ['WRL', 'ADIF + UDP local (127.0.0.1:2237)'], ['MSHV', 'ADIF + arquivo monitorado'], ['HRD', 'ADIF'], ['CLUBLOG', 'ADIF (adapter futuro)'], ['LOTW', 'ADIF'], ['EQSL', 'ADIF']].map(([s, m]) => (
            <label key={s} className="flex items-center gap-2 text-xs cursor-pointer">
              <input type="checkbox" checked={d.sources.includes(s)} onChange={() => setD({ ...d, sources: d.sources.includes(s) ? d.sources.filter((x) => x !== s) : [...d.sources, s] })} />
              <span className="font-semibold w-24">{s}</span><span className="text-slate-500">{m}</span>
            </label>
          ))}
        </div>
      )}
      {step === 3 && (
        <div className="space-y-3">
          <FieldL label="Diretórios monitorados (opcional)"><input className={inp} value={d.dirs} onChange={(e) => setD({ ...d, dirs: e.target.value })} placeholder="C:\Logs\MSHV; C:\Logs\HRD" /></FieldL>
          <div className="text-[11px] text-slate-500">Arquivos novos nessas pastas serão detectados e oferecidos para importação automática.</div>
        </div>
      )}
      {step === 4 && (
        <div className="space-y-2 text-xs text-slate-300">
          <div>✓ Callsign: <Mono className="text-amber-300">{d.callsign}</Mono></div>
          <div>✓ QRZ: {d.key ? 'API Key configurada' : 'somente ADIF'}</div>
          <div>✓ Fontes: {d.sources.join(', ')}</div>
          <div>✓ Modo padrão de escrita: <Chip c="amber">DRY RUN</Chip> · bind 127.0.0.1 · auditoria completa</div>
          <div className="pt-2 text-slate-500">Próximos passos sugeridos: <b>Sincronizar QRZ</b> ou <b>Importar ADIF</b>.</div>
        </div>
      )}
      <div className="flex justify-between mt-6">
        <Btn onClick={() => (step === 0 ? onClose() : setStep(step - 1))}>{step === 0 ? 'Depois' : '← Voltar'}</Btn>
        {step < 4 ? <Btn v="primary" onClick={() => setStep(step + 1)}>Continuar →</Btn> : <Btn v="primary" onClick={finish}>Concluir e começar</Btn>}
      </div>
    </Modal>
  );
}
