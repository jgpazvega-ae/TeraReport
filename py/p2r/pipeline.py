# -*- coding: utf-8 -*-
"""Une lectura, transformación, biblioteca, validación y generación en un solo
flujo, para que la interfaz y la línea de comandos compartan exactamente el
mismo comportamiento.
"""

import datetime
import os
import re

from . import docx_builder, library, parser, profile, rules, settings, validate

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
         'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

_DATE_LONG = re.compile(
    r'(\d{1,2})\s*(?:de|del)?\s*(' + '|'.join(MESES) + r')\w*\s*(?:de|del)?\s*(\d{4})',
    re.IGNORECASE)
_DATE_NUMERIC = re.compile(r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})')
_INVALID_FILENAME = re.compile(r'[\\/:*?"<>|]+')


def parse_date(text):
    if not text:
        return None
    m = _DATE_LONG.search(text)
    if m:
        try:
            return datetime.date(int(m.group(3)), MESES.index(m.group(2).lower()) + 1,
                                 int(m.group(1)))
        except ValueError:
            return None
    m = _DATE_NUMERIC.search(text)
    if m:
        year = int(m.group(3))
        if year < 100:
            year += 2000
        try:
            return datetime.date(year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def format_short(date):
    return date.strftime('%d/%m/%Y') if date else ''


def format_long(date):
    if not date:
        return ''
    return '%d de %s del %d' % (date.day, MESES[date.month - 1], date.year)


class Environment(object):
    """Agrupa el perfil, catálogo y biblioteca ya cargados, para no releer
    estos archivos en cada operación."""

    def __init__(self):
        settings.ensure_profile_copy()
        self.profile = profile.load(settings.profile_path())
        self.catalog = validate.load_robot_catalog(settings.catalog_path())
        self.library = library.Library.load(settings.library_path())
        self._seeded_library()

    def _seeded_library(self):
        """Siembra la biblioteca con la de fábrica la primera vez que se usa."""
        if self.library.fragments:
            return
        seed = settings.library_seed_path()
        if os.path.isfile(seed):
            self.library.import_seed(seed)
            self.library.save(settings.library_path())


def load_report(path, config, env):
    """Lee el reporte de Plaud y le aplica las reglas de la configuración."""
    report = parser.parse(path, env.profile)
    rules.apply_to_report(report, config.get('reemplazos'))
    apply_section_exclusions(report, config.get('secciones_a_eliminar'))
    return report


def apply_section_exclusions(report, titles_to_drop):
    """Desactiva (sin borrar) las secciones cuyo título esté en la lista."""
    targets = set()
    for title in titles_to_drop or []:
        if title.strip():
            targets.add(title.strip().rstrip(':').lower())
    if not targets:
        return 0
    count = 0
    for station in report.stations:
        for section in station.sections:
            if section.title.strip().rstrip(':').lower() in targets:
                section.enabled = False
                count += 1
    return count


def prefill(report, config):
    """Rellena los datos del formulario con lo detectado, sin pisar lo que el
    usuario ya haya capturado."""
    datos = config.setdefault('datos', {})
    detected = report.detected or {}

    # Cuando Plaud no identifica el dato, a veces contesta con una frase
    # explicativa ("No especificado en el contenido, se menciona referencia
    # a..."). Eso no es un cliente ni una ubicación reales: meterlo tal cual
    # en mayúsculas a la portada produciría un encabezado absurdo. Se deja el
    # campo vacío para que el usuario lo capture a mano, que es lo correcto
    # cuando Plaud mismo no tiene un dato claro que ofrecer.
    if detected.get('cliente') and not datos.get('cliente') \
            and not validate.is_filler(detected['cliente']):
        datos['cliente'] = detected['cliente'].upper()
    if detected.get('ubicacion') and not datos.get('ubicacion') \
            and not validate.is_filler(detected['ubicacion']):
        datos['ubicacion'] = detected['ubicacion']

    raw_visit = detected.get('fecha_visita', '')
    # Igual que con cliente/ubicación: si Plaud no supo la fecha y contestó con
    # una frase explicativa, no se le busca una fecha adentro (podría contener
    # una mención incidental como "se habló de mayo de 2026" y confundirse con
    # la fecha real de la visita).
    visit = parse_date(raw_visit) if not validate.is_filler(raw_visit) else None
    if visit:
        if not datos.get('fecha_visita'):
            datos['fecha_visita'] = format_short(visit)
        if not datos.get('fecha_reporte'):
            datos['fecha_reporte'] = format_long(visit)
        if not datos.get('fecha_firma'):
            datos['fecha_firma'] = format_short(visit)
    else:
        today = datetime.date.today()
        if not datos.get('fecha_reporte'):
            datos['fecha_reporte'] = format_long(today)
        if not datos.get('fecha_firma'):
            datos['fecha_firma'] = format_short(today)
    return datos


def suggest_filename(config):
    datos = config.get('datos') or {}
    parts = [datos.get('tipo_reporte') or 'Reporte']
    if datos.get('cliente'):
        parts.append(datos['cliente'].title())
    name = ' - '.join(p.strip() for p in parts if p.strip())
    return _INVALID_FILENAME.sub('', name).strip() + '.docx'


def run_quality_checks(report, config, env):
    return validate.run(report, catalog=env.catalog,
                        rules=config.get('reemplazos'), datos=config.get('datos'))


def suggest_fragments(report, env, top_per_station=5):
    """Sugerencias de biblioteca por estación, como {station_uid: [Fragment]}."""
    result = {}
    for station in report.active_stations():
        suggestions = env.library.suggest(station, top=top_per_station)
        if suggestions:
            result[station.uid] = suggestions
    return result


def build(report, config, output_path, workdir=None):
    return docx_builder.build(report, config, output_path,
                              template=settings.template_path(), workdir=workdir)


def run_cli(source, output=None, config=None, env=None):
    """Conversión de un tirón, sin interfaz. Devuelve (report, resultado)."""
    config = config or settings.load()
    env = env or Environment()
    report = load_report(source, config, env)
    prefill(report, config)
    if not output:
        folder = config.get('ultima_carpeta_salida') or os.path.dirname(
            os.path.abspath(source))
        output = os.path.join(folder, suggest_filename(config))
    return report, build(report, config, output)
