# -*- coding: utf-8 -*-
"""Lector del reporte que emite Plaud, dirigido por el perfil declarativo.

Diferencias de fondo respecto al parser de v1:

  - El reconocimiento de estaciones/secciones/campos viene de `profile.Profile`
    (data/perfil_plaud.json), no de expresiones regulares fijas en código. Si
    el usuario ajusta su prompt de Plaud y cambia un título, basta con agregar
    un alias al perfil.
  - Cada estación/sección/viñeta recibe un `uid` estable (model.make_uid), así
    que releer el mismo export tras editar el perfil permite reencontrar y
    conservar las ediciones manuales ya hechas.
  - El resultado trae un `Report.diagnostics`: qué se reconoció como qué y qué
    quedó sin clasificar, para que el usuario ajuste su prompt de Plaud con
    evidencia en vez de a ciegas.
  - Las secciones se reordenan al orden canónico del perfil al terminar de
    leer, independientemente del orden en que Plaud las haya emitido.
"""

import os
import re

from . import profile as profile_mod
from . import textutil
from .model import Bullet, Report, RobotLine, Section, Station, make_uid

_ROBOT_LINE = re.compile(
    # "MiR MC250" es un Mobile Cobot: MiR seguido, opcionalmente, de "MC" y
    # dígitos. Sin el "(?:MC\s?)?" esta línea nunca matchea "MiR MC250: 1",
    # solo "MiR250: 1" o "MC250: 1" por separado.
    # El "(?:\s+[A-Za-z]+){0,2}" final cubre variantes de nombre con palabras,
    # como "MiR1200 Pallet Jack": sin él, esa línea no matchea nada y además
    # desactiva _in_robots, perdiendo también las líneas de robot que vengan
    # después de ella en el mismo listado.
    r'^\s*(?P<model>UR\s?[0-9]{1,2}[A-Za-z ]{0,4}?|MiR\s?(?:MC\s?)?[0-9]{2,4}(?:\s+[A-Za-z]+){0,2}'
    r'|MC\s?[0-9]{2,4})'
    r'\s*:\s*(?P<count>\d+)\s*(?:\((?P<note>.*)\))?\s*\.?\s*$',
    re.IGNORECASE)

_URL = re.compile(r'^[a-z][a-z0-9+.-]*://', re.IGNORECASE)
_MAX_LABEL_LEN = 70

_MD_HEADING = re.compile(r'^(#{1,6})\s+(.*)$')
_MD_BULLET = re.compile(r'^\s*(?:[-*•]|\d+[.)])\s+(.*)$')
_BARE_LABEL = re.compile(r'^[^:]{2,70}:\s*$')


def split_label(text):
    """Parte "Etiqueta: resto" en ("Etiqueta:", "resto"), o ('', text) si no aplica."""
    text = text.strip()
    if not text or _URL.match(text):
        return '', text
    idx = text.find(':')
    if idx <= 0 or idx > _MAX_LABEL_LEN:
        return '', text
    label, rest = text[:idx].strip(), text[idx + 1:].strip()
    if '. ' in label or not rest:
        return '', text
    return label + ':', rest


class Diagnostic(object):
    __slots__ = ('texto', 'clasificacion', 'detalle')

    def __init__(self, texto, clasificacion, detalle=''):
        self.texto = texto
        self.clasificacion = clasificacion  # estacion/seccion/campo/vineta/ignorado
        self.detalle = detalle


class _Builder(object):
    """Acumula estaciones/secciones/viñetas usando el perfil para clasificar."""

    def __init__(self, prof):
        self.profile = prof
        self.report = Report()
        self._station = None
        self._section = None
        self._in_robots = False
        self._in_notes = False
        self._uid_seen = {}
        self._section_titles_seen = set()

    def _uid(self, prefix, text):
        return make_uid(prefix, text, self._uid_seen)

    # -- estructura ---------------------------------------------------------
    def start_station(self, name):
        self._in_robots = False
        self._in_notes = False
        name = textutil.clean(name)
        self._station = Station(name=name, uid=self._uid('e', name))
        self._section = None
        self.report.stations.append(self._station)
        self.report.diagnostics.append(Diagnostic(name, 'estacion'))

    def start_section(self, raw_title, via='estilo'):
        if self._station is None:
            self.start_station('General')
        canonical = self.profile.find_section(raw_title) if raw_title else None
        title = canonical or textutil.clean(raw_title)
        # Toda sección reconocida termina en ':' (así vienen las canónicas);
        # se mantiene la convención también para las que no se reconocieron,
        # para que el resto del código no tenga que distinguir los dos casos.
        if title and not title.endswith(':'):
            title += ':'
        self._section = Section(title=title, uid=self._uid('s', title))
        self._station.sections.append(self._section)
        if raw_title:
            if canonical == textutil.clean(raw_title):
                detalle = '' if via == 'estilo' else 'reconocida por contenido (no por estilo Word)'
            else:
                detalle = 'reconocida por alias/parecido' if canonical else 'sin reconocer, se usa tal cual'
            self.report.diagnostics.append(Diagnostic(raw_title, 'seccion', detalle))

    def start_robots(self):
        self._in_robots = True
        self._in_notes = False
        self._section = None

    def start_notes(self):
        self._in_notes = True
        self._in_robots = False
        self._section = None

    def add_line(self, text):
        text = textutil.clean(text)
        if not text:
            return

        if self._in_notes:
            self.report.notes.append(text)
            self.report.diagnostics.append(Diagnostic(text, 'nota'))
            return

        if self._in_robots:
            m = _ROBOT_LINE.match(text)
            if m:
                self.report.robots.append(RobotLine(
                    model=textutil.clean(m.group('model')).replace(' ', ''),
                    count=int(m.group('count')),
                    note=textutil.clean(m.group('note') or '')))
                return
            self._in_robots = False

        if self._station is None:
            field, value = self.profile.metadata_field_for(text)
            if field and field not in self.report.detected:
                self.report.detected[field] = value
                self.report.diagnostics.append(Diagnostic(text, 'metadato', field))
                return
            self.report.diagnostics.append(Diagnostic(text, 'ignorado', 'preámbulo'))
            return

        if self._section is None:
            self.start_section('')

        label, rest = split_label(text)
        if label:
            canonical_label = self.profile.canonicalize_field(label)
            label = canonical_label if canonical_label.endswith(':') else canonical_label + ':'
        uid = self._uid('b', label + rest)
        self._section.bullets.append(Bullet(label=label, text=rest, uid=uid))
        self.report.diagnostics.append(Diagnostic(text, 'vineta'))

    def finish(self):
        for station in self.report.stations:
            station.sections = [s for s in station.sections if s.title or s.bullets]
            # Orden canónico del perfil, sin importar cómo las emitió Plaud;
            # lo no reconocido se queda al final, en el orden en que llegó.
            station.sections.sort(key=lambda s: self.profile.section_rank(s.title))
        self.report.stations = [s for s in self.report.stations if s.name or s.sections]
        if not self.report.stations:
            self.report.warnings.append(
                'No se detectó ninguna estación. Revisa el modo diagnóstico para '
                'ver cómo se interpretó el documento y ajusta data/perfil_plaud.json '
                'o el prompt de Plaud.')
        return self.report


def _heading_level(style_name):
    if not style_name:
        return None
    m = re.match(r'^\s*(?:heading|t[ií]tulo|encabezado)\s*(\d+)\s*$', style_name,
                re.IGNORECASE)
    return int(m.group(1)) if m else None


def parse_docx(path, prof):
    import docx

    doc = docx.Document(path)
    builder = _Builder(prof)

    for para in doc.paragraphs:
        text = textutil.clean(para.text)
        if not text:
            continue
        try:
            style_name = para.style.name or ''
        except Exception:
            style_name = ''
        level = _heading_level(style_name)

        # Se revisan antes que nada y a cualquier nivel de encabezado: si el
        # prompt de Plaud cambia y este título deja de ser Heading 1/2, seguir
        # exigiendo un nivel fijo haría que el listado de robots o el bloque
        # de notas se leyeran como una estación más, en silencio.
        if prof.is_robots_heading(text):
            builder.start_robots()
            continue

        if prof.is_notes_heading(text):
            builder.start_notes()
            continue

        if level is not None and level <= 1:
            continue

        station_name = prof.strip_station_prefix(text)
        if level == 2 or station_name is not None:
            builder.start_station(station_name if station_name is not None else text)
            continue

        if level is not None and level >= 3:
            builder.start_section(text)
            continue

        # Plaud no siempre usa un estilo de encabezado para el título de
        # sección: si el prompt cambia, puede emitirlo con un estilo de
        # párrafo normal (visto en la práctica: "First Paragraph" en vez de
        # "Heading 3"). Por eso, cuando el estilo no lo delata, se reconoce
        # por CONTENIDO: una línea corta terminada en ":" cuyo texto coincide
        # con una sección conocida del perfil (exacta, alias o muy parecida)
        # también abre sección, sin importar su estilo Word. Esto es lo que
        # permite que el perfil siga absorbiendo cambios de prompt sin tocar
        # código, incluso cuando el cambio afecta el estilo y no solo el texto.
        if _BARE_LABEL.match(text) and prof.find_section(text) is not None:
            builder.start_section(text, via='contenido')
            continue

        builder.add_line(text)

    report = builder.finish()
    report.source_path = path
    return report


def parse_text(path, prof):
    with open(path, 'rb') as fh:
        raw = fh.read()
    content = None
    for encoding in ('utf-8-sig', 'utf-8', 'cp1252'):
        try:
            content = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if content is None:
        content = raw.decode('latin-1')

    builder = _Builder(prof)
    for line in content.splitlines():
        text = textutil.clean(line)
        if not text:
            continue

        m = _MD_HEADING.match(text)
        if m:
            level, body = len(m.group(1)), textutil.clean(m.group(2))
            if not body:
                continue
            if prof.is_robots_heading(body):
                builder.start_robots()
                continue
            if prof.is_notes_heading(body):
                builder.start_notes()
                continue
            if level <= 1:
                continue
            station_name = prof.strip_station_prefix(body)
            if level == 2 or station_name is not None:
                builder.start_station(station_name if station_name is not None else body)
            else:
                builder.start_section(body, via='contenido')
            continue

        station_name = prof.strip_station_prefix(text)
        if station_name is not None:
            builder.start_station(station_name)
            continue

        if prof.is_robots_heading(text) and len(text) < 200:
            builder.start_robots()
            continue

        if prof.is_notes_heading(text) and len(text) < 200:
            builder.start_notes()
            continue

        m = _MD_BULLET.match(text)
        if m:
            builder.add_line(m.group(1))
            continue

        if _BARE_LABEL.match(text):
            builder.start_section(text, via='contenido')
            continue

        builder.add_line(text)

    report = builder.finish()
    report.source_path = path
    return report


def parse(path, prof=None):
    """Lee un reporte de Plaud desde .docx, .txt o .md, usando `prof` (o el
    perfil embebido de emergencia si no se indica ninguno)."""
    prof = prof or profile_mod.default_profile()
    ext = os.path.splitext(path)[1].lower()
    if ext == '.docx':
        return parse_docx(path, prof)
    if ext in ('.txt', '.md', '.markdown'):
        return parse_text(path, prof)
    raise ValueError(
        'Formato no soportado: %s. Exporta el reporte de Plaud como .docx, '
        '.txt o .md.' % (ext or 'sin extensión'))


def diagnostics_report(report):
    """Texto legible del modo diagnóstico: qué se reconoció como qué."""
    lines = ['Cómo se interpretó el documento', '=' * 40, '']
    counts = {}
    for d in report.diagnostics:
        counts[d.clasificacion] = counts.get(d.clasificacion, 0) + 1
    for kind in ('estacion', 'seccion', 'metadato', 'vineta', 'nota', 'ignorado'):
        if kind in counts:
            lines.append('%-12s: %d' % (kind, counts[kind]))
    lines.append('')
    for d in report.diagnostics:
        if d.clasificacion in ('ignorado', 'seccion') and d.detalle:
            lines.append('[%s] %s  (%s)' % (d.clasificacion, d.texto[:70], d.detalle))
    return '\n'.join(lines)
