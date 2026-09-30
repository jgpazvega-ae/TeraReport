# -*- coding: utf-8 -*-
"""Motor de reemplazos de terminología.

Tres propiedades que lo distinguen del motor de v1:

1. **Una sola pasada.** Todas las reglas se resuelven contra el texto original
   a la vez, así que una regla nunca alimenta a otra: con "UR10e → UR12e" y
   "UR12e → UR15" activas, un UR10e termina en UR12e y ahí se queda.

2. **Sin duplicar palabras.** v1 convertía
   "Alimentación de Máquinas de Sputtering (Axela)" en
   "…de Sputtering (Sputtering)". Aquí, cuando el reemplazo repetiría lo que ya
   dice el texto justo al lado, se colapsa la redundancia en vez de crearla.

3. **Vista previa.** Cada cambio se puede inspeccionar antes de aplicarlo:
   qué regla lo produjo, qué texto entra y sale, y de qué tipo es.

Lo que el motor NO hace es decidir por el usuario: si un cambio concreto no le
gusta, edita esa viñeta a mano y la capa manual del modelo lo respeta para
siempre (ver p2r/model.py).
"""

import re

# Tipos de cambio, para explicarlos en la vista previa.
KIND_REPLACE = 'reemplazo'
KIND_COLLAPSE = 'colapso'   # se eliminó un paréntesis que habría quedado repetido
KIND_SKIP = 'omitido'       # el reemplazo habría duplicado la palabra vecina

# Caracteres que separan palabras para efectos de la guarda de redundancia.
_SEP = ' \t -–—/,;:.'


class Change(object):
    """Un cambio concreto detectado en un texto."""

    __slots__ = ('start', 'end', 'old', 'new', 'rule_id', 'kind')

    def __init__(self, start, end, old, new, rule_id, kind):
        self.start = start
        self.end = end
        self.old = old
        self.new = new
        self.rule_id = rule_id
        self.kind = kind

    def __repr__(self):  # pragma: no cover - ayuda al depurar
        return '<Change %s %r -> %r (%s)>' % (self.kind, self.old, self.new,
                                              self.rule_id)


def rule_id(rule, index=0):
    return rule.get('id') or '%s->%s#%d' % (rule.get('buscar', ''),
                                            rule.get('reemplazar', ''), index)


class Replacer(object):
    """Aplica un conjunto de reglas en una sola pasada."""

    def __init__(self, rules):
        self._replacements = []
        self._rules = []
        self._ids = []
        parts = []

        # Términos largos primero: así "AMRs" gana sobre "AMR".
        active = [r for r in (rules or [])
                  if r.get('activo', True) and r.get('buscar')]
        ordered = sorted(active, key=lambda r: len(r['buscar']), reverse=True)

        for index, rule in enumerate(ordered):
            needle = rule['buscar']
            pattern = re.escape(needle)
            if rule.get('palabra_completa', True):
                # \b solo aporta si el término empieza/termina en carácter de palabra.
                if needle[:1].isalnum() or needle[:1] == '_':
                    pattern = r'\b' + pattern
                if needle[-1:].isalnum() or needle[-1:] == '_':
                    pattern = pattern + r'\b'
            if not rule.get('distingue_mayusculas', True):
                pattern = '(?i:%s)' % pattern
            parts.append('(?P<r%d>%s)' % (index, pattern))
            self._replacements.append(rule.get('reemplazar', ''))
            self._rules.append(rule)
            self._ids.append(rule_id(rule, index))

        self._regex = re.compile('|'.join(parts)) if parts else None

    def __bool__(self):
        return self._regex is not None

    __nonzero__ = __bool__

    # -- guarda de redundancia --------------------------------------------
    @staticmethod
    def _word_before(text, position):
        """Última palabra antes de `position`, con el índice donde empieza."""
        end = position
        while end > 0 and text[end - 1] in _SEP + '(':
            end -= 1
        start = end
        while start > 0 and text[start - 1] not in _SEP + '(':
            start -= 1
        return text[start:end], start

    @staticmethod
    def _word_after(text, position):
        start = position
        while start < len(text) and text[start] in _SEP + ')':
            start += 1
        end = start
        while end < len(text) and text[end] not in _SEP + ')':
            end += 1
        return text[start:end], end

    def _redundancy(self, text, start, end, replacement):
        """¿El reemplazo repetiría una palabra vecina? Devuelve (inicio, fin, tipo).

        Cubre los dos casos que se dan en la práctica:
          "Máquinas de Sputtering (Axela)"  -> se borra el paréntesis entero
          "equipo Sputtering Axela"         -> se borra el término y su separador
        """
        target = replacement.strip().lower()
        if not target:
            return None

        before, before_start = self._word_before(text, start)
        if before.strip().lower() != target:
            return None

        # Caso paréntesis: el término está encerrado y lo previo ya lo dice.
        open_paren = text.rfind('(', before_start, start)
        if open_paren != -1 and not text[open_paren + 1:start].strip():
            close_paren = text.find(')', end)
            if close_paren != -1 and not text[end:close_paren].strip():
                cut = open_paren
                while cut > 0 and text[cut - 1] in ' \t ':
                    cut -= 1
                return cut, close_paren + 1, KIND_COLLAPSE

        # Caso adyacente sin paréntesis: se elimina el término y su separador.
        cut = start
        while cut > 0 and text[cut - 1] in ' \t ':
            cut -= 1
        return cut, end, KIND_SKIP

    # -- API ---------------------------------------------------------------
    def changes(self, text):
        """Cambios que se aplicarían a `text`, en orden de aparición."""
        if not text or self._regex is None:
            return []
        result = []
        for match in self._regex.finditer(text):
            index = int(match.lastgroup[1:])
            replacement = self._replacements[index]
            rid = self._ids[index]
            start, end = match.start(), match.end()

            redundant = None
            if self._rules[index].get('colapsar_redundancia', True):
                redundant = self._redundancy(text, start, end, replacement)

            if redundant:
                cut_start, cut_end, kind = redundant
                result.append(Change(cut_start, cut_end, text[cut_start:cut_end],
                                     '', rid, kind))
            else:
                result.append(Change(start, end, match.group(), replacement,
                                     rid, KIND_REPLACE))
        return result

    def text(self, value):
        """Devuelve `value` con todas las reglas aplicadas."""
        changes = self.changes(value)
        if not changes:
            return value
        out = []
        cursor = 0
        for change in changes:
            # Una colapsada puede empezar antes de donde terminó la anterior.
            if change.start < cursor:
                continue
            out.append(value[cursor:change.start])
            out.append(change.new)
            cursor = change.end
        out.append(value[cursor:])
        return ''.join(out)


def preview(report, rules, limit_per_rule=0):
    """Resume qué haría cada regla sobre el reporte completo.

    Devuelve una lista de diccionarios, uno por regla que produce cambios, con
    el conteo y ejemplos concretos (estación, texto antes y después). Es lo que
    alimenta el panel de vista previa de la interfaz.
    """
    replacer = Replacer(rules)
    if not replacer:
        return []

    summary = {}

    def note(rid, kind, station_name, before, after):
        entry = summary.setdefault(rid, {'regla': rid, 'total': 0,
                                         'por_tipo': {}, 'ejemplos': []})
        entry['total'] += 1
        entry['por_tipo'][kind] = entry['por_tipo'].get(kind, 0) + 1
        if not limit_per_rule or len(entry['ejemplos']) < limit_per_rule:
            entry['ejemplos'].append({'estacion': station_name, 'tipo': kind,
                                      'antes': before, 'despues': after})

    def scan(station_name, value):
        for change in replacer.changes(value):
            note(change.rule_id, change.kind, station_name,
                 value, replacer.text(value))

    for station in report.stations:
        scan(station.original_name, station.original_name)
        for section in station.sections:
            scan(station.original_name, section.original_title)
            for bullet in section.bullets:
                scan(station.original_name, bullet.original_label)
                scan(station.original_name, bullet.original_text)

    for robot in report.robots:
        scan('(listado de robots)', robot.model)
        scan('(listado de robots)', robot.note)

    return sorted(summary.values(), key=lambda e: -e['total'])


def apply_to_report(report, rules):
    """Recalcula la capa automática del reporte. No toca las ediciones manuales."""
    replacer = Replacer(rules)
    transform = replacer.text if replacer else (lambda t: t)
    report.apply_auto(transform)
    for robot in report.robots:
        robot.model = transform(robot.model)
        robot.note = transform(robot.note)
    report.robots = merge_robots(report.robots)
    return report


def merge_robots(robots):
    """Suma los conteos de modelos repetidos tras los reemplazos.

    Si "UR12e" pasa a ser "UR15" y el listado ya traía un renglón "UR15",
    quedarían dos renglones para el mismo modelo.
    """
    merged = []
    index = {}
    for robot in robots:
        key = robot.model.replace(' ', '').lower()
        if key in index:
            target = merged[index[key]]
            target.count += robot.count
            notes = [n for n in (target.note, robot.note) if n]
            target.note = ' + '.join(notes)
        else:
            index[key] = len(merged)
            merged.append(robot)
    return merged
