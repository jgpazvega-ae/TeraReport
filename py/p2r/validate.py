# -*- coding: utf-8 -*-
"""Verificaciones de calidad antes de entregar el reporte.

Cada verificador recorre el reporte y produce Finding(s) con severidad. Nada
aquí bloquea la generación por sí solo: la interfaz decide si avisa o si deja
generar de todos modos. El objetivo es que un reporte con "No especificado en
el contenido", un payload incoherente con el robot recomendado, o una palabra
duplicada por un reemplazo, no llegue al cliente por descuido.
"""

import io
import json
import os
import re

from . import textutil

SEVERITY_ERROR = 'error'
SEVERITY_WARNING = 'advertencia'
SEVERITY_INFO = 'sugerencia'

_FILLER_PATTERNS = [
    re.compile(r'no especificado en el contenido', re.IGNORECASE),
    re.compile(r'\bprobablemente\b', re.IGNORECASE),
    re.compile(r'\bse infiere\b', re.IGNORECASE),
    re.compile(r'\bposiblemente\b', re.IGNORECASE),
]

_WEIGHT_KG = re.compile(r'(\d+(?:[.,]\d+)?)\s*kg', re.IGNORECASE)
_MODEL_TOKEN = re.compile(r'\b(UR\s?\d{1,2}e?|MiR\s?\d{2,4}|MC\s?\d{2,4})\b',
                          re.IGNORECASE)


class Finding(object):
    __slots__ = ('severity', 'code', 'message', 'station_uid', 'target_uid',
                 'station_name')

    def __init__(self, severity, code, message, station_uid='', target_uid='',
                station_name=''):
        self.severity = severity
        self.code = code
        self.message = message
        self.station_uid = station_uid
        self.target_uid = target_uid
        self.station_name = station_name

    def to_dict(self):
        return {'severity': self.severity, 'code': self.code,
                'message': self.message, 'station_uid': self.station_uid,
                'target_uid': self.target_uid, 'station_name': self.station_name}


def load_robot_catalog(path):
    with io.open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    by_model = {}
    for entry in data.get('brazos', []) + data.get('amr', []):
        by_model[textutil.key(entry['modelo'])] = entry
    return by_model


# ---------------------------------------------------------------------------
# verificadores individuales; cada uno recibe (report, catalog) y produce
# una lista de Finding. Se registran al final en CHECKS.
# ---------------------------------------------------------------------------

def is_filler(text):
    """True si `text` es (o consiste en) un relleno de Plaud tipo "No
    especificado en el contenido...", incluida su forma con explicación entre
    paréntesis. Se expone para que otras partes de la app (p.ej. el prellenado
    del formulario) no traten esto como un valor real detectado."""
    text = (text or '').strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _FILLER_PATTERNS)


def check_filler_text(report, catalog):
    findings = []
    for station, section, bullet in report.all_bullets():
        if not bullet.enabled:
            continue
        for pattern in _FILLER_PATTERNS:
            if pattern.search(bullet.text):
                findings.append(Finding(
                    SEVERITY_WARNING, 'texto-de-relleno',
                    'Texto de relleno en "%s": "%s"' % (
                        section.title.rstrip(':'), bullet.text[:90]),
                    station.uid, bullet.uid, station.name))
                break
    return findings


def check_missing_robot_model(report, catalog):
    findings = []
    for station in report.active_stations():
        field = station.field('Modelo de Robot Recomendado')
        if field is None or not textutil.clean(field.text).rstrip('.'):
            findings.append(Finding(
                SEVERITY_ERROR, 'sin-modelo-de-robot',
                'La estación no declara "Modelo de Robot Recomendado".',
                station.uid, '', station.name))
    return findings


def check_payload_coherence(report, catalog):
    """El peso declarado de la pieza no debe superar el payload del robot citado."""
    findings = []
    for station in report.active_stations():
        peso_field = station.field('Peso de la Pieza / Carga útil del Robot')
        modelo_field = station.field('Modelo de Robot Recomendado')
        if peso_field is None or modelo_field is None:
            continue

        weight_match = _WEIGHT_KG.search(peso_field.text)
        model_match = _MODEL_TOKEN.search(modelo_field.text)
        if not weight_match or not model_match:
            continue

        weight = float(weight_match.group(1).replace(',', '.'))
        model_key = textutil.key(model_match.group(1)).replace(' ', '')
        entry = catalog.get(model_key)
        if entry is None or 'payload_kg' not in entry:
            continue

        payload = entry['payload_kg']
        if weight > payload:
            findings.append(Finding(
                SEVERITY_WARNING, 'payload-insuficiente',
                'La pieza pesa ~%.1f kg pero %s soporta %.0f kg (sin contar '
                'el gripper). Confirmar si el cálculo ya lo incluye.'
                % (weight, entry['modelo'], payload),
                station.uid, peso_field.uid, station.name))
    return findings


def check_difficulty_range(report, catalog):
    findings = []
    pattern = re.compile(r'(\d)\s*(?:de|/)\s*5|nivel de dificultad\D*(\d)', re.IGNORECASE)
    for station in report.active_stations():
        field = station.field('Nivel de dificultad')
        if field is None:
            continue
        text = field.label + ' ' + field.text
        digits = re.findall(r'\d', text)
        if digits and not (1 <= int(digits[0]) <= 5):
            findings.append(Finding(
                SEVERITY_WARNING, 'dificultad-fuera-de-rango',
                'Nivel de dificultad fuera de la escala 1–5: "%s"' % text[:60],
                station.uid, field.uid, station.name))
    return findings


def check_empty_station_name(report, catalog):
    findings = []
    for station in report.active_stations():
        if not textutil.clean(station.name):
            findings.append(Finding(
                SEVERITY_ERROR, 'estacion-sin-nombre',
                'Hay una estación sin nombre.', station.uid, '', station.name))
    return findings


def check_robot_count_matches_body(report, catalog):
    """El total del listado de robots debería coincidir con lo citado en el
    cuerpo. Una diferencia grande suele significar un modelo mal contado tras
    aplicar los reemplazos de terminología."""
    findings = []
    if not report.robots:
        return findings

    cited = {}
    for station in report.active_stations():
        field = station.field('Modelo de Robot Recomendado')
        if field is None:
            continue
        match = _MODEL_TOKEN.search(field.text)
        if match:
            key = textutil.key(match.group(1)).replace(' ', '')
            cited[key] = cited.get(key, 0) + 1

    listed = dict((textutil.key(r.model).replace(' ', ''), r.count)
                 for r in report.robots)

    for key, count in cited.items():
        if key not in listed:
            findings.append(Finding(
                SEVERITY_INFO, 'modelo-no-listado',
                'El modelo citado en el cuerpo no aparece en el listado de robots '
                '(revisar tras los reemplazos de terminología).',
                '', '', ''))
    return findings


def check_confidential_terms_leaked(report, rules, catalog=None):
    """Un término que una regla debía reemplazar (p.ej. anonimizar el nombre
    de un equipo del cliente) pero sigue apareciendo, es una fuga real."""
    findings = []
    active = [r for r in (rules or [])
              if r.get('activo', True) and r.get('anonimiza', False)]
    if not active:
        return findings

    for rule in active:
        needle = textutil.key(rule['buscar'])
        for station in report.active_stations():
            haystack = textutil.key(station.name) + ' ' + ' '.join(
                textutil.key(b.full_text) for sec in station.sections
                for b in sec.bullets)
            if needle in haystack:
                findings.append(Finding(
                    SEVERITY_ERROR, 'fuga-de-confidencialidad',
                    'El término "%s" debía anonimizarse y sigue apareciendo.'
                    % rule['buscar'], station.uid, '', station.name))
    return findings


_DUP_WORD = re.compile(r'\b(\w{3,})\b(?:\s*\((\1)\)|\s+(\1)\b)', re.IGNORECASE)


def check_duplicated_adjacent_word(report, catalog):
    """Palabra inmediatamente repetida: 'Sputtering (Sputtering)', 'el el'..."""
    findings = []
    for station, section, bullet in report.all_bullets():
        if not bullet.enabled:
            continue
        for text, where in ((bullet.text, 'texto'), (station.name, 'nombre')):
            m = _DUP_WORD.search(text)
            if m:
                findings.append(Finding(
                    SEVERITY_WARNING, 'palabra-duplicada',
                    'Palabra repetida por un reemplazo, en el %s: "%s"'
                    % (where, text[max(0, m.start() - 20):m.end() + 5]),
                    station.uid, bullet.uid, station.name))
    return findings


def suggest_fix_duplicated_word(text):
    """Arreglo de un clic para 'X (X)' / 'X X': deja una sola aparición.

    Función pura reutilizable desde la interfaz para un botón "Arreglar" sobre
    cualquier texto, no solo sobre lo que generó un reemplazo.
    """
    def collapse(match):
        return match.group(1)
    return _DUP_WORD.sub(collapse, text)


_AMR_MENTION = re.compile(r'\bamr\b|\bmir\b', re.IGNORECASE)


def check_amr_without_model(report, catalog):
    """Si la estación habla de un AMR pero no dice cuál se recomienda, es
    justo el hueco que hoy se llena a mano (ver p2r/library.py)."""
    findings = []
    for station in report.active_stations():
        mentions_amr = _AMR_MENTION.search(station.name) or any(
            _AMR_MENTION.search(b.text) or _AMR_MENTION.search(b.label)
            for sec in station.sections for b in sec.bullets if b.enabled)
        if not mentions_amr:
            continue
        field = station.field('Modelo de Robot AMR Recomendado')
        if field is None or not textutil.clean(field.text).rstrip('.'):
            findings.append(Finding(
                SEVERITY_INFO, 'amr-sin-modelo',
                'La estación menciona un AMR pero no especifica el modelo '
                'recomendado. Revisa las sugerencias de la biblioteca.',
                station.uid, '', station.name))
    return findings


def check_missing_photo_files(report, catalog):
    """Una foto cuyo archivo ya no existe se descarta en silencio al generar
    (se movió el USB, se borró la carpeta...); mejor avisar antes."""
    findings = []
    for station in report.active_stations():
        for photo in station.photos:
            if photo.enabled and not os.path.isfile(photo.path):
                findings.append(Finding(
                    SEVERITY_WARNING, 'foto-no-encontrada',
                    'No se encuentra el archivo de una foto: %s' % photo.path,
                    station.uid, '', station.name))
    return findings


def check_required_fields(report, datos):
    """Cliente y ubicación son los únicos datos que de verdad hacen falta
    para que la portada tenga sentido; el resto tiene un valor por defecto
    razonable."""
    findings = []
    for key, label in (('cliente', 'Cliente'), ('ubicacion', 'Ubicación')):
        if not textutil.clean((datos or {}).get(key, '')):
            findings.append(Finding(
                SEVERITY_ERROR, 'campo-obligatorio-vacio',
                '"%s" está vacío y aparece en la portada del reporte.' % label))
    return findings


CHECKS = [
    check_empty_station_name,
    check_missing_robot_model,
    check_payload_coherence,
    check_difficulty_range,
    check_filler_text,
    check_duplicated_adjacent_word,
    check_robot_count_matches_body,
    check_amr_without_model,
    check_missing_photo_files,
]


def run(report, catalog=None, rules=None, datos=None):
    """Corre todos los verificadores y devuelve los hallazgos, más severos primero."""
    findings = []
    for check in CHECKS:
        findings.extend(check(report, catalog or {}))
    if rules:
        findings.extend(check_confidential_terms_leaked(report, rules))
    if datos is not None:
        findings.extend(check_required_fields(report, datos))

    order = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}
    findings.sort(key=lambda f: order.get(f.severity, 9))
    return findings
