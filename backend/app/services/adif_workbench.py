"""Persistent named ADIF sources and read-only confirmation proposals.

Original ADIF text is retained. Correction export patches only approved receipt
fields in that text, including unknown/typed tags and header preservation.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import threading
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..adapters.cloud_logs import records_to_adif
from ..adif.parser import ADIFParser
from ..core.runtime import user_data_root
from .cloud_snapshot_store import CloudSnapshotStore
from .fast_adif_comparison_service import FastADIFComparisonService

KINDS = {'LOG', 'EQSL_RECEIVED', 'LOTW', 'PAPER'}
COVERAGES = {'FULL_EXPORT', 'PARTIAL_EXPORT'}
CHANNELS = {
    'EQSL': ('EQSL_QSL_RCVD', 'EQSL_QSLRDATE', 'EQSL_QSL_SENT', 'EQSL_QSLSDATE'),
    'LOTW': ('LOTW_QSL_RCVD', 'LOTW_QSLRDATE', 'LOTW_QSL_SENT', 'LOTW_QSLSDATE'),
    'PAPER': ('QSL_RCVD', 'QSLRDATE', 'QSL_SENT', 'QSLSDATE'),
    'QRZ': ('APP_QRZLOG_QSL_RCVD', None, 'APP_QRZLOG_QSL_SENT', None),
}
YES = {'Y', 'V'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def scan_adif(content):
    """Length-aware scanner; tag-looking text inside values is never executed."""
    pos, fields, records, start = 0, [], [], 0
    while pos < len(content):
        opening = content.find('<', pos)
        if opening < 0:
            break
        end = content.find('>', opening)
        if end < 0:
            raise ValueError('ADIF contém tag sem fechamento')
        tag = content[opening + 1:end]
        if tag.upper() in {'EOH', 'EOR'}:
            if tag.upper() == 'EOH':
                if records:
                    raise ValueError('Cabeçalho ADIF fora de posição')
                fields, start = [], end + 1
            else:
                if fields:
                    records.append({'fields': fields, 'start': start, 'end': end + 1, 'eor': opening})
                fields, start = [], end + 1
            pos = end + 1
            continue
        match = re.fullmatch(r'([A-Za-z][A-Za-z0-9_]*):(\d+)(?::[A-Za-z])?', tag)
        if not match:
            raise ValueError(f'Tag ADIF inválida: {tag[:80]}')
        stop = end + 1 + int(match[2])
        if stop > len(content):
            raise ValueError(f'Comprimento inválido no campo {match[1]}')
        name = match[1].upper()
        if any(f['name'] == name for f in fields):
            raise ValueError(f'Campo repetido no mesmo registro: {name}')
        fields.append({'name': name, 'value': content[end + 1:stop], 'start': opening, 'end': stop})
        pos = stop
    if fields:
        raise ValueError('Último registro sem <EOR>; corrija o arquivo antes de importar')
    if not records:
        raise ValueError('Nenhum QSO encontrado no ADIF')
    raw = [{f['name']: f['value'] for f in r['fields']} for r in records]
    for index, record in enumerate(raw):
        if not record.get('CALL') or not date_value(record.get('QSO_DATE')):
            raise ValueError(f'Registro {index + 1} sem CALL ou com QSO_DATE inválida')
    return raw, records


def patch_adif(content, changes):
    _, spans = scan_adif(content)
    edits = []
    for index, values in changes.items():
        span = spans[index]
        fields = {f['name']: f for f in span['fields']}
        for key, value in values.items():
            text = f'<{key}:{len(value)}>{value}'
            field = fields.get(key)
            edits.append((field['start'], field['end'], text) if field else (span['eor'], span['eor'], text))
    for start, end, text in sorted(edits, reverse=True):
        content = content[:start] + text + content[end:]
    return content


def date_value(value):
    if not value:
        return None
    value = str(value).strip().replace('-', '')
    try:
        if not re.fullmatch(r'\d{8}', value):
            return None
        datetime.strptime(value, '%Y%m%d')
        return value
    except ValueError:
        return None


def csv_report(rows):
    fields = list(dict.fromkeys(k for r in rows for k in r)) or ['resultado']
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, delimiter=';')
    writer.writeheader()
    for row in rows:
        clean = {}
        for key, value in row.items():
            text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value if value is not None else '')
            # Open safely in Excel even when a callsign/comment resembles a formula.
            clean[key] = "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text
        writer.writerow(clean)
    return '\ufeff' + stream.getvalue()


class ADIFWorkbench:
    _lock = threading.RLock()
    REMOTE_IDS = ('QRZ', 'WRL', 'CLUBLOG', 'EQSL', 'HRD')

    def __init__(self, root=None):
        self.root = Path(root or user_data_root())
        self.directory = self.root / 'adif_sources'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.snapshots = CloudSnapshotStore(self.root)
        self.comparator = FastADIFComparisonService()

    def _path(self, source_id):
        if not re.fullmatch(r'[a-f0-9]{32}', source_id):
            raise ValueError('Identificador de fonte inválido')
        return self.directory / f'{source_id}.json'

    def load(self, source_id):
        if source_id.startswith('snapshot:'):
            provider = source_id.split(':', 1)[1]
            if provider not in self.REMOTE_IDS:
                raise ValueError('Fonte desconhecida')
            snap = self.snapshots.load(provider)
            if not snap.get('downloaded_at'):
                raise ValueError('Atualize a fonte antes de analisar')
            text = records_to_adif(snap['records'])
            records, _ = scan_adif(text)
            coverage = snap.get('metadata', {}).get('coverage', 'PARTIAL_EXPORT')
            return {'id': source_id, 'name': provider, 'kind': 'LOG', 'coverage': coverage,
                    'content': text, 'records': records, 'revision': digest(snap), 'updated_at': snap['downloaded_at'],
                    'filename': provider + '.adi', 'readonly': True}
        path = self._path(source_id)
        if not path.exists():
            raise ValueError('Fonte não encontrada; atualize a lista')
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def summary(source):
        return {**{k: v for k, v in source.items() if k not in {'records', 'content'}}, 'count': len(source['records'])}

    def sources(self):
        local = [self.summary(json.loads(p.read_text(encoding='utf-8'))) for p in self.directory.glob('*.json')]
        for provider in self.REMOTE_IDS:
            if self.snapshots.summary(provider).get('downloaded_at'):
                local.append(self.summary(self.load('snapshot:' + provider)))
        return sorted(local, key=lambda s: s['name'].casefold())

    def save(self, name, kind, coverage, content, filename, source_id=None):
        name = name.strip()
        if not name or len(name) > 100 or kind not in KINDS or coverage not in COVERAGES:
            raise ValueError('Informe nome, tipo e cobertura válidos')
        records, _ = scan_adif(content)
        with self._lock:
            if source_id:
                previous = self.load(source_id)
                if previous.get('readonly'):
                    raise ValueError('Snapshots online são atualizados em Fontes & dados')
                archive = self.directory / 'backups'
                archive.mkdir(exist_ok=True)
                (archive / f'{source_id}-{uuid.uuid4().hex}.json').write_text(json.dumps(previous, ensure_ascii=False), encoding='utf-8')
            source_id = source_id or uuid.uuid4().hex
            path = self._path(source_id)
            payload = {'id': source_id, 'name': name, 'kind': kind, 'coverage': coverage,
                       'filename': Path(filename).name, 'content': content, 'records': records,
                       'updated_at': datetime.now(timezone.utc).isoformat(),
                       'revision': digest([content, kind, coverage]), 'readonly': False}
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            temp.replace(path)
        return self.summary(payload)

    def delete(self, source_id):
        with self._lock:
            source = self.load(source_id)
            if source.get('readonly'):
                raise ValueError('Gerencie snapshots online em Fontes & dados')
            archive = self.directory / 'backups'
            archive.mkdir(exist_ok=True)
            self._path(source_id).replace(archive / f'{source_id}-{uuid.uuid4().hex}.json')
        return {'removed': True}

    def compare(self, base_id, source_ids):
        base = self.load(base_id)
        if not source_ids or base_id in source_ids:
            raise ValueError('Selecione uma base e ao menos outra fonte')
        comparisons, findings = [], []
        for sid in dict.fromkeys(source_ids):
            other = self.load(sid)
            # Source labels must remain distinct even for two versions with same name.
            a, b = base['name'] + ' [base]', other['name'] + ' [' + sid[-6:] + ']'
            result = self.comparator.compare(records_to_adif(base['records']), records_to_adif(other['records']), a, b,
                base['coverage'] if base['kind'] == 'LOG' else 'PARTIAL_EXPORT',
                other['coverage'] if other['kind'] == 'LOG' else 'PARTIAL_EXPORT',
                base['filename'], other['filename'])
            comparisons.append({'source_id': sid, 'name': other['name'], **result})
            for category in ('missing_in_a', 'missing_in_b', 'field_differences', 'tolerated_differences', 'probable_duplicates'):
                findings.extend({'category': category, 'comparison': other['name'], **item} for item in result[category])
        return {'base': self.summary(base), 'comparisons': comparisons, 'findings': findings}

    @staticmethod
    def matrix(record):
        return {channel: {'received': record.get(fields[0], ''), 'received_date': record.get(fields[1], '') if fields[1] else '',
                          'sent': record.get(fields[2], ''), 'sent_date': record.get(fields[3], '') if fields[3] else ''}
                for channel, fields in CHANNELS.items()}

    @staticmethod
    def evidence(record, kind):
        result = []
        for channel in ('EQSL', 'LOTW', 'PAPER'):
            received, date, _, _ = CHANNELS[channel]
            flag = str(record.get(received, '')).upper()
            implied = (kind == 'EQSL_RECEIVED' and channel == 'EQSL' and not flag)
            if flag in YES or implied:
                # eQSL Inbox exports can use generic QSLRDATE. Never infer from QSO_DATE.
                raw_date = record.get(date) or (record.get('QSLRDATE') if kind == 'EQSL_RECEIVED' and channel == 'EQSL' else None)
                result.append((channel, raw_date, flag or 'Y'))
        # Generic QSL_RCVD in an explicitly eQSL/LoTW export is not paper evidence.
        if kind in {'EQSL_RECEIVED', 'LOTW'}:
            result = [e for e in result if e[0] != 'PAPER']
        return result

    def normalized(self, records, side):
        parser = ADIFParser()
        values = [{**r, "TIME_ON": parser._normalize_field("TIME_ON", r.get("TIME_ON", ""))} for r in records]
        for record in values:
            value = str(record.get('TIME_ON') or '')
            if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d', value):
                record['TIME_ON'] = None
        return self.comparator._normalize(values, side)

    def qsl(self, target_id, source_ids, tolerance=300):
        if not source_ids or target_id in source_ids:
            raise ValueError('Selecione a base e fontes de confirmação distintas')
        target = self.load(target_id)
        if target['kind'] != 'LOG':
            raise ValueError('A base deve ser um log; arquivos de recebidos não são o log de destino')
        sources = [self.load(s) for s in dict.fromkeys(source_ids)]
        revision = digest([target['revision'], [(s['id'], s['revision']) for s in sources], tolerance])
        norm = self.normalized(target['records'], 'target')
        buckets = defaultdict(list)
        for q in norm:
            buckets[(q.call, q.date.replace('-', ''))].append(q)
        groups, unmatched = {}, []
        for source in sources:
            normalized = self.normalized(source['records'], source['id'])
            for q in normalized:
                evidences = self.evidence(source['records'][q.index], source['kind'])
                if not evidences:
                    continue
                candidates = []
                for t in buckets.get((q.call, q.date.replace('-', '')), []):
                    if not q.band or not t.band or q.band != t.band or not q.operating_mode or not t.operating_mode:
                        continue
                    if not self.comparator._mode_compatible(q, t) or q.seconds is None or t.seconds is None:
                        continue
                    delta = abs(q.seconds - t.seconds)
                    if delta > tolerance:
                        continue
                    station_a = str(q.raw.get('STATION_CALLSIGN') or '').upper()
                    station_b = str(t.raw.get('STATION_CALLSIGN') or '').upper()
                    if station_a and station_b and station_a != station_b:
                        continue
                    if q.freq_hz and t.freq_hz and abs(q.freq_hz-t.freq_hz) > self.comparator._freq_tolerance(q,t):
                        continue
                    candidates.append((t, delta))
                if len(candidates) != 1:
                    unmatched.append({'status': 'AMBIGUOUS' if candidates else 'UNMATCHED', 'call': q.call, 'date': q.date,
                                      'time': q.time, 'band': q.band, 'mode': q.operating_mode, 'source': source['name'],
                                      'reason': 'Mais de um QSO candidato' if candidates else 'Sem pareamento seguro; banda, modo e horário são necessários',
                                      'candidates': [{'index': t.index, 'time': t.time, 'delta_seconds': d} for t,d in candidates]})
                    continue
                t, delta = candidates[0]
                for channel, raw_date, flag in evidences:
                    key = (t.index, channel)
                    if key not in groups:
                        groups[key] = {'target_index': t.index, 'call': t.call, 'date': t.date, 'time': t.time,
                            'band': t.band, 'mode': t.operating_mode, 'logid': t.raw.get('APP_QRZLOG_LOGID', ''),
                            'channel': channel, 'evidence': []}
                    groups[key]['evidence'].append({'source': source['name'], 'source_id': source['id'], 'source_index': q.index,
                        'source_time': q.time, 'target_time': t.time, 'delta_seconds': delta, 'date_raw': raw_date,
                        'received_date': date_value(raw_date), 'received': flag})
        proposals = []
        for key, row in groups.items():
            record = target['records'][row['target_index']]
            flag_field, date_field, _, _ = CHANNELS[row['channel']]
            dates = {e['received_date'] for e in row['evidence'] if e['received_date']}
            invalid = any(e['date_raw'] and not e['received_date'] for e in row['evidence'])
            old_flag, old_date = record.get(flag_field, ''), record.get(date_field, '')
            qso_date = date_value(record.get('QSO_DATE'))
            status, reason, changes = 'READY', 'Pareamento único por indicativo, data, banda, modo e horário', {}
            if invalid or len(dates) > 1 or (dates and qso_date and min(dates) < qso_date):
                status, reason = 'REVIEW', 'Datas inválidas, divergentes ou anteriores ao contato'
            elif old_date and (not date_value(old_date) or (dates and date_value(old_date) not in dates)):
                status, reason = 'REVIEW', 'Data existente no destino diverge da evidência'
            elif str(old_flag).upper() in {'I', 'X'}:
                status, reason = 'REVIEW', 'Destino possui estado de confirmação que exige revisão'
            else:
                if str(old_flag).upper() not in YES:
                    changes[flag_field] = 'Y'
                if dates and not old_date:
                    changes[date_field] = next(iter(dates))
                if not changes:
                    status, reason = 'UNCHANGED', 'Confirmação já representada no destino'
                elif not dates:
                    reason += '; data de recebimento não informada, será preservada sem inventar'
            row.update({'id': digest([revision, key])[:24], 'status': status, 'reason': reason,
                        'before': {flag_field: old_flag, date_field: old_date}, 'changes': changes,
                        'received_date': next(iter(dates)) if len(dates) == 1 else None})
            proposals.append(row)
        matrix = [{'index': q.index, 'call': q.call, 'date': q.date, 'time': q.time, 'band': q.band,
                   'mode': q.operating_mode, 'channels': self.matrix(target['records'][q.index])} for q in norm]
        return {'revision': revision, 'target': self.summary(target), 'sources': [self.summary(s) for s in sources],
                'proposals': proposals, 'unmatched': unmatched, 'matrix': matrix,
                'summary': dict(Counter(r['status'] for r in proposals + unmatched))}

    def export_qsl(self, target_id, source_ids, tolerance, revision, selected):
        with self._lock:
            result = self.qsl(target_id, source_ids, tolerance)
            if result['revision'] != revision:
                raise ValueError('As fontes mudaram. Execute a análise novamente antes de exportar')
            proposals = {p['id']: p for p in result['proposals'] if p['status'] == 'READY'}
            if not selected or any(s not in proposals for s in selected):
                raise ValueError('Selecione apenas propostas prontas da análise atual')
            changes = defaultdict(dict)
            for sid in set(selected):
                p = proposals[sid]
                changes[p['target_index']].update(p['changes'])
            source = self.load(target_id)
            if source['revision'] != result['target']['revision']:
                raise ValueError('O destino mudou durante a exportação. Analise novamente')
            original = source['content']
            corrected = patch_adif(original, changes)
            return corrected, original, [proposals[s] for s in dict.fromkeys(selected)]
