from django.contrib import admin

from .models import Dispatch, Driver, Incident, PassageRecord, Route, Shift, Stop, Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("unit_code", "plate", "brand_model", "status", "soat_expiry")
    list_filter = ("status",)
    search_fields = ("unit_code", "plate", "brand_model")


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ("full_name", "document_number", "license_number", "license_expiry", "status")
    list_filter = ("status",)
    search_fields = ("full_name", "document_number", "license_number")


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "origin", "destination", "active")
    list_filter = ("active",)
    search_fields = ("code", "name", "origin", "destination")


@admin.register(Stop)
class StopAdmin(admin.ModelAdmin):
    list_display = ("name", "route", "sequence", "latitude", "longitude")
    list_filter = ("route",)
    search_fields = ("name", "address", "route__code", "route__name")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("service_date", "planned_departure", "route", "driver", "vehicle", "status")
    list_filter = ("service_date", "status", "route")
    search_fields = ("driver__full_name", "vehicle__plate", "route__code")


@admin.register(Dispatch)
class DispatchAdmin(admin.ModelAdmin):
    list_display = ("shift", "sequence", "status", "departure_at", "arrival_at")
    list_filter = ("status", "shift__service_date", "shift__route")
    search_fields = ("shift__driver__full_name", "shift__vehicle__plate")


@admin.register(PassageRecord)
class PassageRecordAdmin(admin.ModelAdmin):
    list_display = ("dispatch", "stop", "passed_at", "recorded_by")
    list_filter = ("passed_at", "stop__route")
    search_fields = ("stop__name", "dispatch__shift__vehicle__plate")


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("category", "severity", "status", "created_at", "reported_by")
    list_filter = ("category", "severity", "status", "created_at")
    search_fields = ("description", "location", "dispatch__shift__vehicle__plate")
