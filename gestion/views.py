import csv
from datetime import date, datetime, time, timedelta
from functools import reduce
from operator import or_

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    DispatchForm,
    DriverForm,
    IncidentForm,
    PassageRecordForm,
    RouteForm,
    ShiftForm,
    StopForm,
    VehicleForm,
)
from .models import Dispatch, Driver, Incident, Route, Shift, Stop, Vehicle


def _value_for_column(record, path):
    value = record
    for part in path.split("__"):
        value = getattr(value, part, "")
        if callable(value):
            value = value()
        if value is None:
            return "—"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return str(value)


def _status_class(status):
    return {
        "active": "success",
        "Activa": "success",
        "Activo": "success",
        "completed": "success",
        "Completado": "success",
        "Finalizado": "success",
        "resolved": "success",
        "Resuelta": "success",
        "in_progress": "primary",
        "En curso": "primary",
        "En ruta": "primary",
        "reviewing": "warning",
        "En revisión": "warning",
        "maintenance": "warning",
        "En mantenimiento": "warning",
        "medium": "warning",
        "Media": "warning",
        "suspended": "danger",
        "Brevete vencido": "danger",
        "Documentación vencida": "danger",
        "Inactiva": "secondary",
        "inactive": "secondary",
        "cancelled": "secondary",
        "Cancelado": "secondary",
        "open": "danger",
        "Abierta": "danger",
        "high": "danger",
        "Alta": "danger",
        "critical": "dark",
        "Crítica": "dark",
        "scheduled": "info",
        "Programado": "info",
        "Pendiente": "info",
        "low": "secondary",
        "Baja": "secondary",
    }.get(status, "secondary")


def _record_list(request, *, model, section, columns, search_fields, url_prefix):
    search_term = request.GET.get("q", "").strip()
    records = model.objects.all()
    if search_term:
        query = reduce(or_, (Q(**{f"{field}__icontains": search_term}) for field in search_fields))
        records = records.filter(query)
    related_fields = {
        Stop: ("route",),
        Shift: ("route", "driver", "vehicle"),
        Dispatch: ("shift__route", "shift__driver", "shift__vehicle"),
        Incident: ("dispatch__shift__route", "reported_by"),
    }
    records = records.select_related(*related_fields.get(model, ()))
    if model is Shift:
        records = records.prefetch_related("dispatches")
    elif model is Dispatch:
        records = records.prefetch_related("passages__stop")
    paginator = Paginator(records, 15)
    page = paginator.get_page(request.GET.get("page"))
    rows = []
    for record in page:
        label = str(record)
        status_getter = getattr(record, "get_operational_status", None)
        if status_getter is None:
            status_getter = getattr(record, "get_status_display", None)
        status = status_getter() if status_getter else ""
        row = {
            "cells": [_value_for_column(record, field) for _, field in columns],
            "label": label,
            "status": status,
            "status_class": _status_class(status),
            "edit_url": reverse(f"{url_prefix}_edit", args=[record.pk]),
            "delete_url": reverse(f"{url_prefix}_delete", args=[record.pk]),
        }
        if isinstance(record, Dispatch):
            row["dispatch"] = record
            row["passage_url"] = reverse(
                "passage_create", args=[record.pk]
            )
        if isinstance(record, Shift):
            dispatches = list(record.dispatches.all())
            row["shift"] = record
            row["can_close_shift"] = (
                record.status == Shift.Status.IN_PROGRESS
                and bool(dispatches)
                and all(item.status == Dispatch.Status.COMPLETED for item in dispatches)
            )
            row["can_cancel_shift"] = (
                record.status == Shift.Status.SCHEDULED and not dispatches
            )
        rows.append(row)

    template_name = {
        Driver: "gestion/conductores.html",
        Dispatch: "gestion/despacho.html",
    }.get(model, "gestion/records.html")
    return render(
        request,
        template_name,
        {
            "section": section,
            "columns": [label for label, _ in columns],
            "rows": rows,
            "search_term": search_term,
            "page_obj": page,
            "create_url": reverse(f"{url_prefix}_create"),
            "list_url": reverse(f"{url_prefix}_list"),
            "url_prefix": url_prefix,
        },
    )


def _record_form(request, *, model, form_class, section, url_prefix, pk=None):
    record = get_object_or_404(model, pk=pk) if pk else None
    form = form_class(request.POST or None, instance=record)
    if request.method == "POST" and form.is_valid():
        instance = form.save(commit=False)
        if isinstance(instance, Incident) and not instance.pk:
            instance.reported_by = request.user
        if isinstance(instance, Incident):
            instance.resolved_at = (
                timezone.now()
                if instance.status == Incident.Status.RESOLVED
                else None
            )
        try:
            with transaction.atomic():
                instance.save()
                form.save_m2m()
        except IntegrityError:
            form.add_error(
                None,
                "No se pudo guardar porque ya existe un registro con esos datos.",
            )
        else:
            messages.success(
                request,
                f"{section} {'actualizado' if record else 'registrado'} correctamente.",
            )
            return redirect(f"{url_prefix}_list")
    return render(
        request,
        "gestion/form.html",
        {
            "section": section,
            "form": form,
            "record": record,
            "list_url": reverse(f"{url_prefix}_list"),
        },
    )


def _record_delete(request, *, model, section, url_prefix, pk):
    record = get_object_or_404(model, pk=pk)
    if request.method == "POST":
        label = str(record)
        try:
            record.delete()
        except IntegrityError:
            messages.error(
                request,
                "No se puede eliminar este registro porque está asociado a la operación.",
            )
        else:
            messages.success(request, f"{section} «{label}» eliminado correctamente.")
        return redirect(f"{url_prefix}_list")
    return render(
        request,
        "gestion/confirm_delete.html",
        {
            "section": section,
            "record": record,
            "list_url": reverse(f"{url_prefix}_list"),
        },
    )


@login_required
def dashboard_view(request):
    today = timezone.localdate()
    context = {
        "today": today,
        "vehicle_count": Vehicle.objects.filter(
            status=Vehicle.Status.ACTIVE,
            soat_expiry__gte=today,
            technical_review_expiry__gte=today,
        ).count(),
        "driver_count": Driver.objects.filter(
            status=Driver.Status.ACTIVE, license_expiry__gte=today
        ).count(),
        "today_shifts": Shift.objects.filter(service_date=today).count(),
        "today_dispatches": Dispatch.objects.filter(
            shift__service_date=today
        ).count(),
        "open_incidents": Incident.objects.filter(
            status__in=[Incident.Status.OPEN, Incident.Status.REVIEWING]
        ).count(),
        "active_dispatches": Dispatch.objects.filter(
            status=Dispatch.Status.IN_PROGRESS
        ).select_related("shift__route", "shift__driver", "shift__vehicle")[:5],
        "recent_shifts": Shift.objects.filter(service_date__gte=today).select_related(
            "route", "driver", "vehicle"
        ).exclude(
            status__in=[Shift.Status.COMPLETED, Shift.Status.CANCELLED]
        )[:6],
        "document_alerts": Vehicle.objects.filter(
            Q(soat_expiry__lte=today + timedelta(days=30))
            | Q(technical_review_expiry__lte=today + timedelta(days=30))
        ).exclude(status=Vehicle.Status.INACTIVE)[:5],
        "maintenance_alerts": Vehicle.objects.filter(
            maintenance_due__lte=today + timedelta(days=30),
            status=Vehicle.Status.ACTIVE,
        )[:5],
        "license_alerts": Driver.objects.filter(
            license_expiry__lte=today + timedelta(days=30),
            status=Driver.Status.ACTIVE,
        )[:5],
    }
    return render(request, "gestion/dashboard.html", context)


@login_required
def fleet_list(request):
    return _record_list(
        request,
        model=Vehicle,
        section="Flota",
        columns=[
            ("Unidad", "unit_code"),
            ("Placa", "plate"),
            ("Marca y modelo", "brand_model"),
            ("SOAT vence", "soat_expiry"),
            ("Rev. técnica vence", "technical_review_expiry"),
            ("Estado", "get_operational_status"),
        ],
        search_fields=["unit_code", "plate", "brand_model"],
        url_prefix="fleet",
    )


@login_required
def fleet_create(request):
    return _record_form(
        request, model=Vehicle, form_class=VehicleForm, section="Unidad", url_prefix="fleet"
    )


@login_required
def fleet_edit(request, pk):
    return _record_form(
        request,
        model=Vehicle,
        form_class=VehicleForm,
        section="Unidad",
        url_prefix="fleet",
        pk=pk,
    )


@login_required
def fleet_delete(request, pk):
    return _record_delete(
        request, model=Vehicle, section="Unidad", url_prefix="fleet", pk=pk
    )


@login_required
def drivers_list(request):
    return _record_list(
        request,
        model=Driver,
        section="Conductores",
        columns=[
            ("Conductor", "full_name"),
            ("DNI", "document_number"),
            ("Brevete", "license_number"),
            ("Vencimiento", "license_expiry"),
            ("Estado", "get_operational_status"),
        ],
        search_fields=["full_name", "document_number", "license_number"],
        url_prefix="drivers",
    )


@login_required
def drivers_create(request):
    return _record_form(
        request, model=Driver, form_class=DriverForm, section="Conductor", url_prefix="drivers"
    )


@login_required
def drivers_edit(request, pk):
    return _record_form(
        request,
        model=Driver,
        form_class=DriverForm,
        section="Conductor",
        url_prefix="drivers",
        pk=pk,
    )


@login_required
def drivers_delete(request, pk):
    return _record_delete(
        request, model=Driver, section="Conductor", url_prefix="drivers", pk=pk
    )


@login_required
def routes_list(request):
    routes = Route.objects.prefetch_related("stops")
    selected_id = request.GET.get("route")
    selected_route = (
        routes.filter(pk=int(selected_id)).first()
        if selected_id and selected_id.isdecimal()
        else routes.first()
    )
    map_stops = []
    if selected_route:
        map_stops = [
            {
                "name": stop.name,
                "sequence": stop.sequence,
                "latitude": float(stop.latitude),
                "longitude": float(stop.longitude),
            }
            for stop in selected_route.stops.all()
            if stop.latitude is not None and stop.longitude is not None
        ]
    return render(
        request,
        "gestion/rutas.html",
        {
            "routes": routes,
            "selected_route": selected_route,
            "map_stops": map_stops,
        },
    )


@login_required
def route_create(request):
    return _record_form(
        request, model=Route, form_class=RouteForm, section="Ruta", url_prefix="routes"
    )


@login_required
def route_edit(request, pk):
    return _record_form(
        request,
        model=Route,
        form_class=RouteForm,
        section="Ruta",
        url_prefix="routes",
        pk=pk,
    )


@login_required
def route_delete(request, pk):
    return _record_delete(
        request, model=Route, section="Ruta", url_prefix="routes", pk=pk
    )


@login_required
def stops_list(request):
    return _record_list(
        request,
        model=Stop,
        section="Paraderos",
        columns=[
            ("Ruta", "route__code"),
            ("Paradero", "name"),
            ("Orden", "sequence"),
            ("Dirección o referencia", "address"),
            ("Latitud", "latitude"),
            ("Longitud", "longitude"),
        ],
        search_fields=["name", "address", "route__code", "route__name"],
        url_prefix="stops",
    )


@login_required
def stops_create(request):
    return _record_form(
        request, model=Stop, form_class=StopForm, section="Paradero", url_prefix="stops"
    )


@login_required
def stops_edit(request, pk):
    return _record_form(
        request,
        model=Stop,
        form_class=StopForm,
        section="Paradero",
        url_prefix="stops",
        pk=pk,
    )


@login_required
def stops_delete(request, pk):
    return _record_delete(
        request, model=Stop, section="Paradero", url_prefix="stops", pk=pk
    )


@login_required
def shifts_list(request):
    return _record_list(
        request,
        model=Shift,
        section="Turnos",
        columns=[
            ("Fecha", "service_date"),
            ("Salida", "planned_departure"),
            ("Ruta", "route__code"),
            ("Conductor", "driver__full_name"),
            ("Unidad", "vehicle__plate"),
            ("Estado", "get_status_display"),
        ],
        search_fields=[
            "route__code",
            "route__name",
            "driver__full_name",
            "vehicle__plate",
        ],
        url_prefix="shifts",
    )


@login_required
def shifts_create(request):
    return _record_form(
        request, model=Shift, form_class=ShiftForm, section="Turno", url_prefix="shifts"
    )


@login_required
def shifts_edit(request, pk):
    return _record_form(
        request,
        model=Shift,
        form_class=ShiftForm,
        section="Turno",
        url_prefix="shifts",
        pk=pk,
    )


@login_required
def shifts_delete(request, pk):
    return _record_delete(
        request, model=Shift, section="Turno", url_prefix="shifts", pk=pk
    )


@login_required
def shift_action(request, pk, action):
    if request.method != "POST":
        return redirect("shifts_list")
    try:
        with transaction.atomic():
            shift = Shift.objects.select_for_update().get(pk=pk)
            dispatches = list(shift.dispatches.select_for_update())
            if action == "close" and shift.status == Shift.Status.IN_PROGRESS:
                if not dispatches or any(
                    item.status != Dispatch.Status.COMPLETED for item in dispatches
                ):
                    raise ValidationError(
                        "Finaliza todas las vueltas antes de cerrar el turno."
                    )
                shift.status = Shift.Status.COMPLETED
                shift.save(update_fields=["status"])
                messages.success(request, "Turno cerrado correctamente.")
            elif (
                action == "cancel"
                and shift.status == Shift.Status.SCHEDULED
                and not dispatches
            ):
                shift.status = Shift.Status.CANCELLED
                shift.save(update_fields=["status"])
                messages.success(request, "Turno cancelado.")
            else:
                raise ValidationError(
                    "La acción no está permitida para el estado actual del turno."
                )
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return redirect("shifts_list")


@login_required
def dispatch_list(request):
    return _record_list(
        request,
        model=Dispatch,
        section="Despacho",
        columns=[
            ("Fecha", "shift__service_date"),
            ("Vuelta", "sequence"),
            ("Ruta", "shift__route__code"),
            ("Conductor", "shift__driver__full_name"),
            ("Unidad", "shift__vehicle__plate"),
            ("Salida real", "departure_at"),
            ("Llegada real", "arrival_at"),
            ("Controles", "control_summary"),
            ("Estado", "get_status_display"),
        ],
        search_fields=[
            "shift__route__code",
            "shift__driver__full_name",
            "shift__vehicle__plate",
        ],
        url_prefix="dispatch",
    )


@login_required
def dispatch_create(request):
    return _record_form(
        request,
        model=Dispatch,
        form_class=DispatchForm,
        section="Despacho",
        url_prefix="dispatch",
    )


@login_required
def dispatch_edit(request, pk):
    return _record_form(
        request,
        model=Dispatch,
        form_class=DispatchForm,
        section="Despacho",
        url_prefix="dispatch",
        pk=pk,
    )


@login_required
def dispatch_delete(request, pk):
    return _record_delete(
        request, model=Dispatch, section="Despacho", url_prefix="dispatch", pk=pk
    )


@login_required
def dispatch_action(request, pk, action):
    if request.method != "POST":
        return redirect("dispatch_list")
    try:
        with transaction.atomic():
            dispatch = Dispatch.objects.select_for_update().select_related("shift").get(pk=pk)
            shift = Shift.objects.select_for_update().get(pk=dispatch.shift_id)
            if action == "depart" and dispatch.status == Dispatch.Status.SCHEDULED:
                if shift.status in (Shift.Status.CANCELLED, Shift.Status.COMPLETED):
                    raise ValidationError("No se puede despachar un turno cerrado.")
                dispatch.status = Dispatch.Status.IN_PROGRESS
                dispatch.departure_at = timezone.now()
                dispatch.save(update_fields=["status", "departure_at"])
                shift.status = Shift.Status.IN_PROGRESS
                shift.save(update_fields=["status"])
                messages.success(request, "Salida registrada. La vuelta está en ruta.")
            elif action == "arrive" and dispatch.status == Dispatch.Status.IN_PROGRESS:
                dispatch.status = Dispatch.Status.COMPLETED
                dispatch.arrival_at = timezone.now()
                dispatch.save(update_fields=["status", "arrival_at"])
                messages.success(request, "Llegada registrada y vuelta finalizada.")
            else:
                raise ValidationError("La acción no está permitida para el estado actual.")
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return redirect("dispatch_list")


@login_required
def passage_create(request, dispatch_pk):
    dispatch = get_object_or_404(
        Dispatch.objects.select_related("shift__route"), pk=dispatch_pk
    )
    if dispatch.status != Dispatch.Status.IN_PROGRESS:
        messages.error(request, "Solo puedes registrar controles de una vuelta en ruta.")
        return redirect("dispatch_list")
    form = PassageRecordForm(
        request.POST or None, dispatch=dispatch
    )
    if request.method == "POST" and form.is_valid():
        passage = form.save(commit=False)
        passage.dispatch = dispatch
        passage.recorded_by = request.user
        passage.save()
        messages.success(request, "Paso por paradero registrado correctamente.")
        return redirect("dispatch_list")
    return render(
        request,
        "gestion/form.html",
        {
            "section": "Control de paso",
            "form": form,
            "record": None,
            "list_url": reverse("dispatch_list"),
            "subtitle": str(dispatch),
        },
    )


@login_required
def incidents_list(request):
    return _record_list(
        request,
        model=Incident,
        section="Incidencias",
        columns=[
            ("Fecha", "created_at"),
            ("Tipo", "get_category_display"),
            ("Prioridad", "get_severity_display"),
            ("Descripción", "description"),
            ("Ubicación", "location"),
            ("Estado", "get_status_display"),
        ],
        search_fields=["description", "location", "dispatch__shift__vehicle__plate"],
        url_prefix="incidents",
    )


@login_required
def incidents_create(request):
    return _record_form(
        request,
        model=Incident,
        form_class=IncidentForm,
        section="Incidencia",
        url_prefix="incidents",
    )


@login_required
def incidents_edit(request, pk):
    return _record_form(
        request,
        model=Incident,
        form_class=IncidentForm,
        section="Incidencia",
        url_prefix="incidents",
        pk=pk,
    )


@login_required
def incidents_delete(request, pk):
    return _record_delete(
        request, model=Incident, section="Incidencia", url_prefix="incidents", pk=pk
    )


@login_required
def reports_view(request):
    today = timezone.localdate()
    month_start = today.replace(day=1)
    context = {
        "vehicle_status": Vehicle.objects.values("status").annotate(total=Count("id")),
        "drivers_available": Driver.objects.filter(
            status=Driver.Status.ACTIVE, license_expiry__gte=today
        ).count(),
        "drivers_expiring": Driver.objects.filter(
            status=Driver.Status.ACTIVE,
            license_expiry__lte=today + timedelta(days=30),
        ).count(),
        "dispatches_month": Dispatch.objects.filter(
            shift__service_date__gte=month_start, shift__service_date__lte=today
        ).count(),
        "completed_month": Dispatch.objects.filter(
            shift__service_date__gte=month_start,
            shift__service_date__lte=today,
            status=Dispatch.Status.COMPLETED,
        ).count(),
        "incidents_open": Incident.objects.filter(
            status__in=[Incident.Status.OPEN, Incident.Status.REVIEWING]
        ).count(),
        "route_usage": Route.objects.annotate(
            shift_count=Count(
                "shifts",
                filter=Q(shifts__service_date__gte=month_start)
                & Q(shifts__service_date__lte=today),
            )
        ).order_by("-shift_count", "code"),
        "report_date": today,
    }
    return render(request, "gestion/reports.html", context)


@login_required
def export_report(request):
    today = timezone.localdate()
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="despachos-{today:%Y-%m-%d}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        ["Fecha", "Salida programada", "Ruta", "Vuelta", "Conductor", "Unidad", "Estado", "Salida real", "Llegada real"]
    )
    dispatches = Dispatch.objects.select_related(
        "shift__route", "shift__driver", "shift__vehicle"
    ).filter(shift__service_date__year=today.year).order_by(
        "shift__service_date", "shift__planned_departure", "sequence"
    )

    def safe_cell(value):
        value = str(value)
        return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value

    for item in dispatches.iterator():
        writer.writerow(
            [
                item.shift.service_date,
                item.shift.planned_departure,
                safe_cell(item.shift.route.code),
                item.sequence,
                safe_cell(item.shift.driver.full_name),
                safe_cell(item.shift.vehicle.plate),
                safe_cell(item.get_status_display()),
                item.departure_at.strftime("%d/%m/%Y %H:%M") if item.departure_at else "",
                item.arrival_at.strftime("%d/%m/%Y %H:%M") if item.arrival_at else "",
            ]
        )
    return response
