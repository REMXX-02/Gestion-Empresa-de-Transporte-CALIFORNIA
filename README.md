# Panel administrativo de Nuevo California

Panel Django para el Sistema Integral de Gestión y Monitoreo de Transporte Público. Implementa el alcance web administrativo descrito en el informe; la aplicación móvil de pasajeros y la API Spring Boot son componentes externos.

## Módulos

- **Resumen:** indicadores del día, turnos próximos, vehículos en ruta y alertas de licencias y documentos.
- **Flota y conductores:** altas, consultas y edición; control de SOAT, revisión técnica y brevete. No se puede asignar a turnos una unidad o un conductor con documentación vencida.
- **Rutas y paraderos:** administración de líneas y paraderos ordenados, con coordenadas opcionales para ver el recorrido en el mapa.
- **Turnos:** programación diaria de ruta, conductor, unidad y hora. Los turnos se cancelan antes de despacharse y se cierran cuando sus vueltas han finalizado.
- **Despacho:** registro de vueltas, salidas y llegadas reales, y controles de paso por los paraderos de la ruta.
- **Incidencias:** registro, clasificación y seguimiento; se exige una nota de resolución para cerrarlas.
- **Reportes:** resumen mensual por ruta, estado de flota, alertas de licencia y descarga CSV de despachos del año en curso.

Los módulos requieren una sesión iniciada. Los cambios se guardan en la base SQLite local configurada en `appweb/settings.py`. Las pantallas de mapa usan Leaflet y OpenStreetMap.

## Puesta en marcha (Windows / PowerShell)

Desde la carpeta del proyecto:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abre `http://127.0.0.1:8000/`, inicia sesión con el superusuario y registra las rutas, unidades y conductores. El administrador de Django está disponible en `http://127.0.0.1:8000/admin/`.
