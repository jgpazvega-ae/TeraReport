# -*- coding: utf-8 -*-
"""Modelo de datos de v2, con edición no destructiva.

La diferencia de fondo con v1 está aquí. En v1 el texto de una viñeta era un
solo campo: aplicar las reglas de reemplazo lo sobrescribía, así que volver a
aplicarlas obligaba a releer el archivo de Plaud y se perdía todo lo editado a
mano. En v2 cada viñeta guarda tres capas:

    original  lo que dijo Plaud, inmutable
    auto      original + reglas de reemplazo, recalculable cuando se quiera
    manual    lo que el usuario escribió encima, o None si no tocó nada

El texto que sale al reporte es `manual` si existe y `auto` si no. Cambiar una
regla recalcula únicamente la capa `auto`, así que las ediciones sobreviven.

La identidad de cada elemento es su `uid`, derivado del texto original y no de
su posición. Eso permite volver a leer el mismo export de Plaud y reencontrar
las viñetas aunque se hayan reordenado, para reaplicar sobre ellas lo editado.
"""

import hashlib
import re

# Procedencia de un elemento: sirve para explicar en la interfaz de dónde
# salió cada línea y para no confundir criterio del experto con texto de Plaud.
ORIGIN_PLAUD = 'plaud'
ORIGIN_MANUAL = 'manual'
ORIGIN_LIBRARY = 'biblioteca'


def _norm(text):
    return re.sub(r'\s+', ' ', (text or '')).strip()


def make_uid(prefix, text, seen):
    """Identificador estable, derivado del contenido y no de la posición.

    `seen` es un diccionario que cuenta repeticiones: dos viñetas con el mismo
    texto dentro del mismo reporte reciben sufijos distintos y estables.
    """
    digest = hashlib.sha1(_norm(text).lower().encode('utf-8')).hexdigest()[:10]
    key = '%s-%s' % (prefix, digest)
    index = seen.get(key, 0)
    seen[key] = index + 1
    return key if index == 0 else '%s.%d' % (key, index)


class Bullet(object):
    """Una viñeta: etiqueta en negrita opcional más texto."""

    __slots__ = ('uid', 'original_label', 'original_text', 'auto_label',
                 'auto_text', 'manual_label', 'manual_text', 'enabled',
                 'origin', 'note')

    def __init__(self, label='', text='', uid='', origin=ORIGIN_PLAUD,
                 enabled=True, note=''):
        self.uid = uid
        self.original_label = label
        self.original_text = text
        # Antes de aplicar reglas, la capa automática es igual a la original.
        self.auto_label = label
        self.auto_text = text
        self.manual_label = None
        self.manual_text = None
        self.enabled = enabled
        self.origin = origin
        self.note = note

    # -- texto efectivo ---------------------------------------------------
    @property
    def label(self):
        return self.auto_label if self.manual_label is None else self.manual_label

    @property
    def text(self):
        return self.auto_text if self.manual_text is None else self.manual_text

    @property
    def edited(self):
        return self.manual_label is not None or self.manual_text is not None

    @property
    def full_text(self):
        label, text = self.label, self.text
        if label and text:
            return '%s %s' % (label, text)
        return label or text

    # -- edición ----------------------------------------------------------
    def edit(self, label, text):
        """Fija la capa manual. Si coincide con la automática, no marca edición."""
        label, text = _norm(label), _norm(text)
        self.manual_label = None if label == _norm(self.auto_label) else label
        self.manual_text = None if text == _norm(self.auto_text) else text

    def revert(self):
        """Descarta la edición manual y vuelve al resultado de las reglas."""
        self.manual_label = None
        self.manual_text = None

    def apply_auto(self, transform_text):
        """Recalcula la capa automática desde el original. No toca lo manual."""
        self.auto_label = transform_text(self.original_label)
        self.auto_text = transform_text(self.original_text)

    # -- serialización ----------------------------------------------------
    def to_dict(self):
        data = {'uid': self.uid, 'original_label': self.original_label,
                'original_text': self.original_text, 'enabled': self.enabled,
                'origin': self.origin}
        if self.manual_label is not None:
            data['manual_label'] = self.manual_label
        if self.manual_text is not None:
            data['manual_text'] = self.manual_text
        if self.note:
            data['note'] = self.note
        return data

    @classmethod
    def from_dict(cls, data):
        bullet = cls(label=data.get('original_label', ''),
                     text=data.get('original_text', ''),
                     uid=data.get('uid', ''),
                     origin=data.get('origin', ORIGIN_PLAUD),
                     enabled=bool(data.get('enabled', True)),
                     note=data.get('note', ''))
        bullet.manual_label = data.get('manual_label')
        bullet.manual_text = data.get('manual_text')
        return bullet


class Section(object):
    """Una sección dentro de una estación, con sus viñetas."""

    __slots__ = ('uid', 'original_title', 'auto_title', 'manual_title',
                 'bullets', 'enabled')

    def __init__(self, title='', uid='', enabled=True, bullets=None):
        self.uid = uid
        self.original_title = title
        self.auto_title = title
        self.manual_title = None
        self.bullets = bullets if bullets is not None else []
        self.enabled = enabled

    @property
    def title(self):
        return self.auto_title if self.manual_title is None else self.manual_title

    @property
    def edited(self):
        return self.manual_title is not None

    @property
    def key(self):
        """Título normalizado, para comparar contra la lista canónica."""
        return _norm(self.title).rstrip(':').lower()

    def edit(self, title):
        title = _norm(title)
        self.manual_title = None if title == _norm(self.auto_title) else title

    def apply_auto(self, transform_text):
        self.auto_title = transform_text(self.original_title)
        for bullet in self.bullets:
            bullet.apply_auto(transform_text)

    def active_bullets(self):
        return [b for b in self.bullets if b.enabled and (b.label or b.text)]

    def to_dict(self):
        data = {'uid': self.uid, 'original_title': self.original_title,
                'enabled': self.enabled,
                'bullets': [b.to_dict() for b in self.bullets]}
        if self.manual_title is not None:
            data['manual_title'] = self.manual_title
        return data

    @classmethod
    def from_dict(cls, data):
        section = cls(title=data.get('original_title', ''),
                      uid=data.get('uid', ''),
                      enabled=bool(data.get('enabled', True)),
                      bullets=[Bullet.from_dict(b) for b in data.get('bullets', [])])
        section.manual_title = data.get('manual_title')
        return section


class Photo(object):
    """Una foto del recorrido, con su pie y la sección donde se ancla."""

    __slots__ = ('path', 'caption', 'after_section', 'enabled')

    def __init__(self, path='', caption='', after_section='', enabled=True):
        self.path = path
        self.caption = caption
        # uid de la sección tras la que va la foto; vacío = al final de la estación.
        self.after_section = after_section
        self.enabled = enabled

    def to_dict(self):
        return {'path': self.path, 'caption': self.caption,
                'after_section': self.after_section, 'enabled': self.enabled}

    @classmethod
    def from_dict(cls, data):
        return cls(path=data.get('path', ''), caption=data.get('caption', ''),
                   after_section=data.get('after_section', ''),
                   enabled=bool(data.get('enabled', True)))


class Station(object):
    """Una estación del levantamiento."""

    __slots__ = ('uid', 'original_name', 'auto_name', 'manual_name',
                 'sections', 'photos', 'enabled')

    def __init__(self, name='', uid='', enabled=True, sections=None, photos=None):
        self.uid = uid
        self.original_name = name
        self.auto_name = name
        self.manual_name = None
        self.sections = sections if sections is not None else []
        self.photos = photos if photos is not None else []
        self.enabled = enabled

    @property
    def name(self):
        return self.auto_name if self.manual_name is None else self.manual_name

    @property
    def edited(self):
        return self.manual_name is not None

    def edit(self, name):
        name = _norm(name)
        self.manual_name = None if name == _norm(self.auto_name) else name

    def apply_auto(self, transform_text):
        self.auto_name = transform_text(self.original_name)
        for section in self.sections:
            section.apply_auto(transform_text)

    def section(self, title):
        """Busca una sección por título, ignorando mayúsculas y dos puntos."""
        wanted = _norm(title).rstrip(':').lower()
        for section in self.sections:
            if section.key == wanted:
                return section
        return None

    def field(self, label):
        """Valor de una viñeta con esa etiqueta, en cualquier sección.

        Es el acceso que usan la matriz ejecutiva y las validaciones para leer
        campos como "Modelo de Robot Recomendado" sin saber en qué sección cayó.
        """
        wanted = _norm(label).rstrip(':').lower()
        for section in self.sections:
            for bullet in section.bullets:
                if _norm(bullet.label).rstrip(':').lower() == wanted:
                    return bullet
        return None

    def active_sections(self):
        result = []
        for section in self.sections:
            if not section.enabled:
                continue
            bullets = section.active_bullets()
            if bullets:
                result.append((section, bullets))
        return result

    def to_dict(self):
        data = {'uid': self.uid, 'original_name': self.original_name,
                'enabled': self.enabled,
                'sections': [s.to_dict() for s in self.sections],
                'photos': [p.to_dict() for p in self.photos]}
        if self.manual_name is not None:
            data['manual_name'] = self.manual_name
        return data

    @classmethod
    def from_dict(cls, data):
        station = cls(name=data.get('original_name', ''),
                      uid=data.get('uid', ''),
                      enabled=bool(data.get('enabled', True)),
                      sections=[Section.from_dict(s) for s in data.get('sections', [])],
                      photos=[Photo.from_dict(p) for p in data.get('photos', [])])
        station.manual_name = data.get('manual_name')
        return station


class RobotLine(object):
    """Un renglón del listado de robots de Plaud."""

    __slots__ = ('model', 'count', 'note')

    def __init__(self, model='', count=0, note=''):
        self.model = model
        self.count = count
        self.note = note

    def to_dict(self):
        return {'model': self.model, 'count': self.count, 'note': self.note}

    @classmethod
    def from_dict(cls, data):
        return cls(model=data.get('model', ''), count=int(data.get('count', 0)),
                   note=data.get('note', ''))


class Report(object):
    """El reporte completo."""

    def __init__(self, stations=None, robots=None, detected=None,
                 source_path='', warnings=None, notes=None):
        self.stations = stations if stations is not None else []
        self.robots = robots if robots is not None else []
        self.detected = detected if detected is not None else {}
        self.source_path = source_path
        self.warnings = warnings if warnings is not None else []
        # Contenido informativo que Plaud emite fuera de las estaciones (p.ej.
        # "Notas de Descarte / Pendientes de Levantamiento"): no es una
        # estación ni un robot, así que no va al reporte final, pero tampoco
        # se descarta en silencio — queda aquí para que el usuario lo revise.
        self.notes = notes if notes is not None else []
        # Diagnóstico del parser: qué se reconoció y qué quedó sin clasificar.
        self.diagnostics = []

    def apply_auto(self, transform_text):
        """Recalcula la capa automática de todo el reporte."""
        for station in self.stations:
            station.apply_auto(transform_text)

    def active_stations(self):
        return [s for s in self.stations if s.enabled]

    def all_bullets(self):
        for station in self.stations:
            for section in station.sections:
                for bullet in section.bullets:
                    yield station, section, bullet

    def find(self, uid):
        """Localiza un elemento por uid. Devuelve (estación, sección, viñeta)."""
        for station in self.stations:
            if station.uid == uid:
                return station, None, None
            for section in station.sections:
                if section.uid == uid:
                    return station, section, None
                for bullet in section.bullets:
                    if bullet.uid == uid:
                        return station, section, bullet
        return None, None, None

    def edit_count(self):
        return sum(1 for _, _, b in self.all_bullets() if b.edited)

    def to_dict(self):
        return {'stations': [s.to_dict() for s in self.stations],
                'robots': [r.to_dict() for r in self.robots],
                'detected': dict(self.detected),
                'source_path': self.source_path,
                'notes': list(self.notes)}

    @classmethod
    def from_dict(cls, data):
        return cls(stations=[Station.from_dict(s) for s in data.get('stations', [])],
                   robots=[RobotLine.from_dict(r) for r in data.get('robots', [])],
                   detected=dict(data.get('detected', {})),
                   source_path=data.get('source_path', ''),
                   notes=list(data.get('notes', [])))
