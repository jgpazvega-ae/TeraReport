# -*- coding: utf-8 -*-
"""Puente entre la interfaz web (JavaScript, en index.html) y el motor real
de TeraReport (pipeline.py y el resto del paquete p2r).

Cada función pública devuelve un STRING JSON (nunca un objeto Python), con la
forma {"ok": true, "data": ...} o {"ok": false, "error": "..."}. Esto evita
toda ambigüedad de conversión Python↔JS de Pyodide: JavaScript solo necesita
JSON.parse() sobre lo que devuelve cada llamada, igual que si fuera una API
HTTP normal — nada más que aquí no hay red de por medio, todo corre en el
mismo proceso del navegador.

El estado de trabajo (reporte cargado, configuración) vive en variables de
módulo, igual que gui.py lo guarda en atributos de self: solo hay una
"sesión" por pestaña del navegador, así que no hace falta nada más elaborado.
"""

import io
import json
import os

from . import pipeline, profile, rules, settings, validate
from .model import Photo, Report

# Campos de 'datos' propios de UN cliente/visita concreto. Ver la nota en
# gui.py (PER_REPORT_FIELDS): cargar un reporte nuevo debe limpiarlos antes de
# prefill(), porque prefill() solo rellena lo que esté vacío y si no se
# limpian, el cliente/ubicación/fechas de un reporte anterior se quedan
# pegados en el siguiente. Aquí aplica exactamente el mismo defecto y la
# misma corrección que ya se validó en la app de escritorio.
PER_REPORT_FIELDS = ('cliente', 'ubicacion', 'fecha_visita', 'fecha_reporte', 'fecha_firma')

_state = {'env': None, 'config': None, 'report': None, 'source_path': ''}

# Carpeta de fotos DENTRO de /data (el punto de montaje IDBFS de index.html):
# cualquier archivo escrito aquí sobrevive a cerrar la pestaña, porque el
# bootstrap sincroniza TODO /data a IndexedDB en cada persist(). Las fotos en
# /tmp (memoria pura, sin respaldo) se perderían al recargar.
def photos_dir():
    path = os.path.join(settings.user_data_dir(), 'fotos')
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def clear_photos():
    """Borra los archivos de fotos huérfanos de un reporte anterior.

    Se llama al cargar un reporte nuevo y al reiniciar: las fotos viven
    aparte del modelo (son archivos en /data/fotos, el Report solo guarda la
    ruta), así que sin esto se acumularían para siempre en el navegador cada
    vez que se carga un reporte distinto — el mismo defecto que ya se
    corrigió para los campos del formulario, aplicado a archivos.
    """
    folder = photos_dir()
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        if os.path.isfile(full):
            os.remove(full)


# ---------------------------------------------------------------------------
# autoguardado del reporte en progreso
#
# El reporte cargado vive solo en memoria (variable de módulo _state): si se
# recarga la página o el navegador se cierra a medio trabajo, se perdía todo
# (el mismo problema que las fotos en /tmp, pero del reporte completo). Esto
# lo guarda en /data (persistente via IDBFS) después de cada cambio, y lo
# ofrece de vuelta la próxima vez que arranca la página.
# ---------------------------------------------------------------------------

_AUTOSAVE_NAME = 'reporte_en_progreso.json'


def _autosave_path():
    return os.path.join(settings.user_data_dir(), _AUTOSAVE_NAME)


def _discard_autosave_file():
    path = _autosave_path()
    if os.path.isfile(path):
        os.remove(path)


def autosave():
    """Guarda el reporte en progreso. index.html la llama justo antes de
    sincronizar /data a IndexedDB (ver persist() en el bootstrap), así que
    cada cambio real queda respaldado."""
    try:
        if _state['report'] is None:
            _discard_autosave_file()
            return _ok(None)
        payload = {'source_path': _state['source_path'],
                  'report': _state['report'].to_dict()}
        with io.open(_autosave_path(), 'w', encoding='utf-8') as fh:
            fh.write(json.dumps(payload, ensure_ascii=False))
        return _ok(None)
    except Exception as exc:
        return _err(exc)


def has_pending_report():
    return _ok(os.path.isfile(_autosave_path()))


def resume_pending_report():
    """Recupera el reporte autoguardado de una sesión anterior.

    to_dict()/from_dict() no conservan la capa automática (se recalcula a
    propósito al recargar, ver model.py), así que se vuelven a aplicar las
    reglas de reemplazo vigentes — si cambiaron desde que se guardó, el
    reporte recuperado ya las refleja en vez de quedarse con terminología
    vieja. Las ediciones manuales no se tocan, igual que siempre.
    """
    try:
        with io.open(_autosave_path(), encoding='utf-8') as fh:
            payload = json.load(fh)
        report = Report.from_dict(payload.get('report', {}))
        rules.apply_to_report(report, _config().get('reemplazos'))
        _state['report'] = report
        _state['source_path'] = payload.get('source_path', '')
        bullets = sum(len(s.bullets) for st in report.stations for s in st.sections)
        return _ok({
            'reporte': _report_view(report),
            'resumen': {'estaciones': len(report.stations), 'vinetas': bullets,
                       'robots': len(report.robots), 'notas': len(report.notes)},
        })
    except Exception as exc:
        return _err(exc)


def discard_pending_report():
    try:
        _discard_autosave_file()
        clear_photos()
        return _ok(None)
    except Exception as exc:
        return _err(exc)


def _ok(data=None):
    return json.dumps({'ok': True, 'data': data}, ensure_ascii=False)


def _err(exc):
    return json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False)


def _config():
    if _state['config'] is None:
        _state['config'] = settings.load()
    return _state['config']


def _env():
    if _state['env'] is None:
        _state['env'] = pipeline.Environment()
    return _state['env']


def _report():
    if _state['report'] is None:
        raise ValueError('No hay ningún reporte cargado todavía.')
    return _state['report']


def _find_or_raise(uid):
    station, section, bullet = _report().find(uid)
    if station is None:
        raise ValueError('No encuentro el elemento %r (¿el reporte se recargó?).' % uid)
    return station, section, bullet


# ---------------------------------------------------------------------------
# serialización "de vista": to_dict() del modelo solo guarda lo necesario
# para reabrir un proyecto (original + edición manual, sin la capa
# automática, que se recalcula al recargar). La interfaz necesita además el
# texto EFECTIVO — el que de verdad saldría en el .docx — así que estas
# funciones envuelven to_dict() agregando los valores ya resueltos
# (label/text/title/name, y si la edición manual está activa).
# ---------------------------------------------------------------------------

def _bullet_view(b):
    data = b.to_dict()
    data['label_efectivo'] = b.label
    data['text_efectivo'] = b.text
    data['editado'] = b.edited
    return data


def _section_view(s):
    data = s.to_dict()
    data['bullets'] = [_bullet_view(b) for b in s.bullets]
    data['title_efectivo'] = s.title
    data['editado'] = s.edited
    return data


def _station_view(st):
    data = st.to_dict()
    data['sections'] = [_section_view(s) for s in st.sections]
    data['name_efectivo'] = st.name
    data['editado'] = st.edited
    return data


def _report_view(r):
    data = r.to_dict()
    data['stations'] = [_station_view(st) for st in r.stations]
    return data


# ---------------------------------------------------------------------------
# arranque
# ---------------------------------------------------------------------------

def startup():
    """Se llama una sola vez, después de montar /data (IDBFS) y /app.

    Siembra el perfil y la biblioteca de fábrica si es la primera vez que se
    usa esta app en este navegador (idéntico a pipeline.Environment.__init__
    en escritorio), y devuelve la configuración + un resumen del entorno.
    """
    try:
        env = _env()
        config = _config()
        return _ok({
            'config': config,
            'perfil': env.profile.nombre,
            'secciones_canonicas': len(env.profile.sections),
            'modelos_catalogo': len(env.catalog) if env.catalog else 0,
            'fragmentos_biblioteca': len(env.library.fragments),
        })
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# configuración / datos del formulario
# ---------------------------------------------------------------------------

def get_config():
    return _ok(_config())


def update_datos(patch_json):
    """Actualiza campos de config['datos'] (cliente, ubicación, firmas...)."""
    try:
        patch = json.loads(patch_json)
        config = _config()
        config.setdefault('datos', {}).update(patch)
        settings.save(config)
        return _ok(config['datos'])
    except Exception as exc:
        return _err(exc)


def update_config(patch_json):
    """Actualiza claves de nivel superior de config (bloques, opciones...).

    `patch_json` es un objeto plano; para 'bloques' (un sub-diccionario) se
    hace merge en vez de reemplazo, igual que _collect_config() en gui.py.
    """
    try:
        patch = json.loads(patch_json)
        config = _config()
        for key, value in patch.items():
            if key == 'bloques' and isinstance(value, dict):
                config.setdefault('bloques', {}).update(value)
            else:
                config[key] = value
        settings.save(config)
        return _ok(config)
    except Exception as exc:
        return _err(exc)


def save_defaults():
    try:
        path = settings.save(_config())
        return _ok(path)
    except Exception as exc:
        return _err(exc)


def reset_rules_to_default():
    try:
        config = _config()
        config['reemplazos'] = [dict(r) for r in settings.DEFAULT_REPLACEMENTS]
        settings.save(config)
        return _ok(config['reemplazos'])
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# perfil de lectura
# ---------------------------------------------------------------------------

def restore_profile():
    try:
        settings.restore_profile_from_seed()
        env = _env()
        env.profile = profile.load(settings.profile_path())
        return _ok(env.profile.nombre)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# cargar / reiniciar el reporte
# ---------------------------------------------------------------------------

def load_report_from_path(path):
    """Lee el archivo de Plaud ya escrito en `path` (JS lo escribió antes en
    el FS virtual de Pyodide, p.ej. /tmp/upload.docx) y lo prepara para editar.
    """
    try:
        env = _env()
        config = _config()

        # Ver PER_REPORT_FIELDS arriba: se limpian ANTES de prefill() para
        # que un reporte nuevo no herede el cliente/ubicación/fechas del
        # anterior. Las fotos del reporte previo (si lo había) se limpian por
        # la misma razón: son archivos aparte del modelo, y sin esto se
        # acumularían en /data/fotos cada vez que se carga un reporte distinto.
        for key in PER_REPORT_FIELDS:
            config.setdefault('datos', {})[key] = ''
        clear_photos()
        _discard_autosave_file()

        report = pipeline.load_report(path, config, env)
        pipeline.prefill(report, config)

        _state['report'] = report
        _state['source_path'] = path
        settings.push_recent(config, path)
        settings.save(config)

        bullets = sum(len(s.bullets) for st in report.stations for s in st.sections)
        return _ok({
            'reporte': _report_view(report),
            'datos': config['datos'],
            'resumen': {
                'estaciones': len(report.stations),
                'vinetas': bullets,
                'robots': len(report.robots),
                'notas': len(report.notes),
            },
            'avisos': list(report.warnings),
        })
    except Exception as exc:
        return _err(exc)


def get_report():
    try:
        if _state['report'] is None:
            return _ok(None)
        return _ok(_report_view(_state['report']))
    except Exception as exc:
        return _err(exc)


def reset_report():
    """Limpia el reporte cargado y los datos propios del cliente/visita.

    Mismo comportamiento que App.reset_report() en la app de escritorio: solo
    los campos de PER_REPORT_FIELDS vuelven a lo guardado en disco (o vacío);
    firma, tipo de reporte, encabezados y demás preferencias no se tocan.
    """
    try:
        config = _config()
        saved_defaults = settings.load().get('datos', {})
        for key in PER_REPORT_FIELDS:
            config.setdefault('datos', {})[key] = saved_defaults.get(key, '')
        settings.save(config)
        clear_photos()
        _discard_autosave_file()

        _state['report'] = None
        _state['source_path'] = ''
        return _ok({'datos': config['datos']})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# edición del árbol de contenido
# ---------------------------------------------------------------------------

def set_enabled(uid, enabled):
    try:
        station, section, bullet = _find_or_raise(uid)
        target = bullet if bullet is not None else (section if section is not None else station)
        target.enabled = bool(enabled)
        return _ok(None)
    except Exception as exc:
        return _err(exc)


def edit_bullet(uid, label, text):
    try:
        _, _, bullet = _find_or_raise(uid)
        if bullet is None:
            raise ValueError('%r no es una viñeta.' % uid)
        bullet.edit(label, text)
        return _ok(_bullet_view(bullet))
    except Exception as exc:
        return _err(exc)


def revert_bullet(uid):
    try:
        _, _, bullet = _find_or_raise(uid)
        if bullet is None:
            raise ValueError('%r no es una viñeta.' % uid)
        bullet.revert()
        return _ok(_bullet_view(bullet))
    except Exception as exc:
        return _err(exc)


def edit_section_title(uid, title):
    try:
        _, section, _ = _find_or_raise(uid)
        if section is None:
            raise ValueError('%r no es una sección.' % uid)
        section.edit(title)
        return _ok(None)
    except Exception as exc:
        return _err(exc)


def edit_station_name(uid, name):
    try:
        station, _, _ = _find_or_raise(uid)
        station.edit(name)
        return _ok(None)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# fotos (JS ya escribió los bytes en el FS virtual antes de llamar esto)
# ---------------------------------------------------------------------------

def add_photo(station_uid, path, caption='', after_section=''):
    try:
        station, _, _ = _find_or_raise(station_uid)
        station.photos.append(Photo(path=path, caption=caption,
                                    after_section=after_section))
        return _ok(_station_view(station))
    except Exception as exc:
        return _err(exc)


def set_photo_caption(station_uid, path, caption):
    try:
        station, _, _ = _find_or_raise(station_uid)
        for p in station.photos:
            if p.path == path:
                p.caption = caption
                return _ok(_station_view(station))
        raise ValueError('No encuentro esa foto en la estación (¿ya se quitó?).')
    except Exception as exc:
        return _err(exc)


def remove_photo(station_uid, path):
    try:
        station, _, _ = _find_or_raise(station_uid)
        station.photos = [p for p in station.photos if p.path != path]
        return _ok(_station_view(station))
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# reglas de reemplazo
# ---------------------------------------------------------------------------

def preview_rules():
    try:
        preview = rules.preview(_report(), _config().get('reemplazos'))
        return _ok(preview)
    except Exception as exc:
        return _err(exc)


def apply_rules():
    """Recalcula la capa automática con las reglas actuales, sin tocar las
    ediciones manuales (ver model.Bullet.apply_auto / rules.apply_to_report)."""
    try:
        rules.apply_to_report(_report(), _config().get('reemplazos'))
        return _ok(_report_view(_report()))
    except Exception as exc:
        return _err(exc)


def update_rules(rules_json):
    try:
        config = _config()
        config['reemplazos'] = json.loads(rules_json)
        settings.save(config)
        return _ok(config['reemplazos'])
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# calidad y biblioteca
# ---------------------------------------------------------------------------

def run_quality():
    try:
        env = _env()
        config = _config()
        findings = validate.run(_report(), catalog=env.catalog,
                                rules=config.get('reemplazos'), datos=config.get('datos'))
        return _ok([f.to_dict() for f in findings])
    except Exception as exc:
        return _err(exc)


def get_suggestions():
    try:
        env = _env()
        suggestions = pipeline.suggest_fragments(_report(), env)
        return _ok(dict((uid, [f.to_dict() for f in frags])
                        for uid, frags in suggestions.items()))
    except Exception as exc:
        return _err(exc)


def apply_suggestion(station_uid, fragment_id):
    try:
        env = _env()
        station, _, _ = _find_or_raise(station_uid)
        fragment = next((f for f in env.library.fragments if f.id == fragment_id), None)
        if fragment is None:
            raise ValueError('No encuentro el fragmento %r.' % fragment_id)
        bullet = env.library.apply(station, fragment, {}, profile=env.profile)
        env.library.save(settings.library_path())
        return _ok(_bullet_view(bullet) if bullet is not None else None)
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# generación del .docx final
# ---------------------------------------------------------------------------

def generate(output_path):
    """Genera el .docx en `output_path` (dentro del FS virtual). JS lee los
    bytes resultantes con pyodide.FS.readFile() y dispara la descarga."""
    try:
        result = pipeline.build(_report(), _config(), output_path)
        return _ok(result)
    except Exception as exc:
        return _err(exc)
