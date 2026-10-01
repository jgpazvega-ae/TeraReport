# TeraReport

Convierte el reporte que emite **Plaud** en un reporte profesional de
**levantamiento en planta** (Plant Assessment / Line Walk) — desde el
navegador de cualquier celular o computadora, sin instalar nada.

**[Abrir TeraReport](https://jgpazvega-ae.github.io/TeraReport/)**
*(el enlace funciona una vez que GitHub Pages esté activado — ver abajo)*

## Qué es esto

Es la versión web de [Plaud2Report](../Plaud2Report_v2): la misma
herramienta que ya corre como aplicación de escritorio, pero pensada para
usarse desde el celular. No hay servidor: todo el motor (lectura del
reporte de Plaud, reglas de reemplazo, generación del .docx final) corre
**dentro del navegador**, vía [Pyodide](https://pyodide.org/) (Python
compilado a WebAssembly). Los reportes de tus clientes nunca salen de tu
dispositivo — no se sube nada a ningún servidor.

Ventaja sobre la app de escritorio: no depende de tener la laptop prendida
ni de estar en la misma red. Una vez que la página cargó por primera vez,
el navegador la guarda en caché y funciona sin internet.

## Cómo usarlo

1. Abre el enlace de arriba desde tu celular o computadora.
2. Espera a que cargue (unos segundos la primera vez; instantáneo después).
3. Sube el `.docx` que exporta Plaud, o prueba con el ejemplo incluido.
4. Completa los datos que el audio no trae (cliente, ubicación, firmas).
5. Revisa el contenido: incluye/excluye secciones, edita el texto que haga falta.
6. Genera el reporte y descárgalo — desde ahí lo compartes por correo, Teams, etc.

## Arquitectura

```
index.html          página única: arranque de Pyodide + interfaz + lógica de UI
py/p2r/              el motor real, copiado de Plaud2Report_v2/src/p2r
  webapi.py            único archivo nuevo: puente JSON entre JS y el motor
  settings.py          único archivo adaptado: rutas de /app y /data en vez
                        de %LOCALAPPDATA% (ver el docstring del archivo)
  model.py, parser.py, rules.py, docx_builder.py, docx_xml.py,
  validate.py, library.py, profile.py, textutil.py, jpeg_fix.py,
  summary.py, pipeline.py, __init__.py
                        idénticos a la app de escritorio, sin cambios
templates/plant_assessment.docx   machote corporativo (portada, estilos, bloques fijos)
data/                perfil de lectura, catálogo de robots, biblioteca de
                      fragmentos, y un reporte de ejemplo para probar
```

**Por qué casi no hubo que tocar el motor:** todo el paquete `p2r` ya es
Python puro, sin nada de interfaz de escritorio mezclado — `parser.py`,
`rules.py`, `docx_builder.py`, etc. no saben ni les importa si una ruta de
archivo es real o virtual. Pyodide ofrece un sistema de archivos virtual
(Emscripten FS) con un punto de montaje persistente respaldado por
IndexedDB (**IDBFS**), así que el código de lectura/escritura por ruta que
ya existía simplemente funciona, montando `/data` (configuración, perfil,
biblioteca del usuario — persiste entre visitas) y `/app` (recursos de
solo lectura, se reescriben en cada carga de página).

## Mantenimiento

### Si el motor de escritorio cambia

Este repo es una copia (no un enlace) de `Plaud2Report_v2/src/p2r`. Si se
corrige un bug o se agrega algo en la app de escritorio y aplica aquí
también, hay que volver a copiar los archivos afectados a `py/p2r/` — con
la única excepción de `settings.py` (tiene una versión propia, ver su
docstring) y `webapi.py` (exclusivo de la web).

### Actualizar la plantilla, el perfil o el catálogo de robots

Reemplaza el archivo correspondiente en `templates/` o `data/` y sube el
cambio — no hace falta tocar ningún código.

### Probar cambios localmente antes de subirlos

GitHub Pages sirve archivos estáticos por HTTPS; abrir `index.html`
directamente (`file://`) no funciona porque el navegador bloquea módulos y
`fetch()` bajo ese esquema. Sirve la carpeta con cualquier servidor local:

```bash
python -m http.server 8080
# abrir http://localhost:8080/index.html
```

### Depuración

La consola del navegador (F12) tiene `window.pyodide`, `window.webapi` y
`window.callPy(nombreDeFuncion, ...args)` expuestos para probar cualquier
función del motor directamente, por ejemplo:

```js
callPy('get_report')                 // el reporte cargado ahora mismo
callPy('run_quality')                // hallazgos de calidad
```

## Activar GitHub Pages (una sola vez)

1. En este repositorio: **Settings → Pages**.
2. En "Build and deployment" → **Source**: `Deploy from a branch`.
3. **Branch**: `main`, carpeta `/ (root)`. Guardar.
4. GitHub tarda uno o dos minutos en publicar. El enlace queda en
   `https://jgpazvega-ae.github.io/TeraReport/`.

## Qué cubre ya

Además del flujo esencial (cargar, completar datos, editar contenido,
generar y descargar), ya están:

- **Fotos por estación** — botón "Tomar o elegir foto" (usa la cámara
  trasera del celular vía `capture="environment"`, o el selector de
  archivos en computadora), con miniatura, pie de foto editable y opción
  de quitarla. Los archivos viven en `/data/fotos` (el punto de montaje
  IDBFS), así que sobreviven a cerrar la pestaña o quedarse sin batería a
  medio recorrido — ver "Autoguardado" abajo.
- **Autoguardado y recuperación** — el reporte en curso (estaciones,
  ediciones, fotos) se respalda en el navegador después de cada cambio. Si
  la página se recarga o el navegador se cierra a medio trabajo, al volver
  a abrir TeraReport se ofrece recuperarlo tal como quedó; al recuperar, se
  reaplican las reglas de reemplazo vigentes (por si cambiaron mientras
  tanto) sin tocar ninguna edición manual. Cargar un reporte distinto o
  darle a "Nuevo reporte" descarta el respaldo anterior y limpia las fotos
  huérfanas.
- **Panel de calidad** — botón "Verificar" que corre las mismas
  validaciones que la app de escritorio (texto de relleno, robot sin
  modelo recomendado, campos obligatorios vacíos...) y lista los
  hallazgos por severidad; tocar uno abre y resalta esa estación en el
  árbol. También corre automáticamente antes de generar: si hay errores,
  pide confirmación antes de continuar (se puede desactivar con
  `validar_antes_de_generar: false` en la configuración).
- **Sugerencias de biblioteca** — cada estación muestra, si aplica,
  fragmentos de criterio de experto ya guardados (de la biblioteca
  sembrada en `data/biblioteca_semilla.json`); un clic en "Agregar" los
  inserta como viñeta real en la sección correspondiente.

## Qué falta (siguiente fase)

- **Editor y vista previa de reglas de reemplazo** — hoy las reglas se
  aplican con lo que ya esté guardado en la configuración; falta una
  pantalla para editarlas desde el celular (en escritorio ya existe).
- **Límite de espacio de fotos** — hoy no hay tope ni aviso si el
  almacenamiento del navegador se llena tras muchos reportes con fotos;
  vale la pena un indicador de uso y un botón para vaciar fotos viejas.
- **Service worker** para que la app cargue instantáneo y funcione sin
  conexión incluso la primera vez que se visita un sitio nuevo.
- **Sincronizar `Plaud2Report_v2` y `TeraReport`** — son dos copias del
  mismo motor (`py/p2r/` aquí, `src/p2r/` en el de escritorio); un cambio
  en una no llega solo a la otra.
