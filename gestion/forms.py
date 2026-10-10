from django import forms
from django.utils import timezone

from .models import Dispatch, Driver, Incident, PassageRecord, Route, Shift, Stop, Vehicle


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"
            if isinstance(field.widget, forms.DateInput):
                field.widget.input_type = "date"
            elif isinstance(field.widget, forms.TimeInput):
                field.widget.input_type = "time"
            elif isinstance(field.widget, forms.DateTimeInput):
                field.widget.input_type = "datetime-local"


class VehicleForm(StyledModelForm):
    class Meta:
        model = Vehicle
        fields = [
            "unit_code",
            "plate",
            "brand_model",
            "year",
            "capacity",
            "soat_expiry",
            "technical_review_expiry",
            "maintenance_due",
            "status",
            "notes",
        ]
        widgets = {
            "soat_expiry": forms.DateInput(),
            "technical_review_expiry": forms.DateInput(),
            "maintenance_due": forms.DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class DriverForm(StyledModelForm):
    class Meta:
        model = Driver
        fields = [
            "document_number",
            "full_name",
            "phone",
            "license_number",
            "license_expiry",
            "status",
            "notes",
        ]
        widgets = {
            "license_expiry": forms.DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class RouteForm(StyledModelForm):
    class Meta:
        model = Route
        fields = [
            "code",
            "name",
            "origin",
            "destination",
            "distance_km",
            "duration_minutes",
            "color",
            "active",
            "description",
        ]
        widgets = {
            "color": forms.ColorInput(),
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class StopForm(StyledModelForm):
    class Meta:
        model = Stop
        fields = ["route", "sequence", "name", "address", "latitude", "longitude"]


class ShiftForm(StyledModelForm):
    class Meta:
        model = Shift
        fields = [
            "service_date",
            "route",
            "driver",
            "vehicle",
            "planned_departure",
            "notes",
        ]
        widgets = {
            "service_date": forms.DateInput(),
            "planned_departure": forms.TimeInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["driver"].queryset = Driver.objects.filter(
            status=Driver.Status.ACTIVE, license_expiry__gte=today
        )
        self.fields["driver"].error_messages["invalid_choice"] = (
            "Selecciona un conductor activo con el brevete vigente."
        )
        self.fields["vehicle"].queryset = Vehicle.objects.filter(
            status=Vehicle.Status.ACTIVE,
            soat_expiry__gte=today,
            technical_review_expiry__gte=today,
        )
        self.fields["vehicle"].error_messages["invalid_choice"] = (
            "Selecciona una unidad activa con sus documentos vigentes."
        )
        self.fields["route"].queryset = Route.objects.filter(active=True)
        for field_name in ("driver", "vehicle", "route"):
            current = getattr(self.instance, f"{field_name}_id", None)
            if current:
                self.fields[field_name].queryset = (
                    self.fields[field_name].queryset
                    | self.fields[field_name].queryset.model.objects.filter(pk=current)
                )


class DispatchForm(StyledModelForm):
    class Meta:
        model = Dispatch
        fields = ["shift", "sequence", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = Shift.objects.exclude(
            status__in=[Shift.Status.COMPLETED, Shift.Status.CANCELLED]
        ).select_related("route", "driver", "vehicle")
        if self.instance.pk and self.instance.shift_id:
            queryset = queryset | Shift.objects.filter(pk=self.instance.shift_id).select_related(
                "route", "driver", "vehicle"
            )
        self.fields["shift"].queryset = queryset


class IncidentForm(StyledModelForm):
    class Meta:
        model = Incident
        fields = [
            "dispatch",
            "category",
            "severity",
            "description",
            "location",
            "status",
            "resolution_notes",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "resolution_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dispatch"].required = False
        self.fields["dispatch"].queryset = Dispatch.objects.select_related(
            "shift__route", "shift__vehicle", "shift__driver"
        ).order_by("-shift__service_date", "-sequence")


class PassageRecordForm(StyledModelForm):
    class Meta:
        model = PassageRecord
        fields = ["stop", "notes"]
        widgets = {"notes": forms.TextInput()}

    def __init__(self, *args, dispatch, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stop"].queryset = dispatch.shift.route.stops.all()
