from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


class Vehicle(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Activa"
        MAINTENANCE = "maintenance", "En mantenimiento"
        INACTIVE = "inactive", "Inactiva"

    unit_code = models.CharField("código de unidad", max_length=20, unique=True)
    plate = models.CharField("placa", max_length=12, unique=True)
    brand_model = models.CharField("marca y modelo", max_length=100)
    year = models.PositiveSmallIntegerField("año")
    capacity = models.PositiveSmallIntegerField(
        "capacidad", default=30, validators=[MinValueValidator(1)]
    )
    soat_expiry = models.DateField("vencimiento del SOAT")
    technical_review_expiry = models.DateField("vencimiento de revisión técnica")
    maintenance_due = models.DateField("próximo mantenimiento", null=True, blank=True)
    status = models.CharField(
        "estado", max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    notes = models.TextField("observaciones", blank=True)
    created_at = models.DateTimeField("registrada", auto_now_add=True)

    class Meta:
        ordering = ["unit_code"]
        verbose_name = "unidad"
        verbose_name_plural = "unidades"

    def __str__(self):
        return f"{self.unit_code} · {self.plate}"

    @property
    def documents_expired(self):
        today = timezone.localdate()
        return self.soat_expiry < today or self.technical_review_expiry < today

    @property
    def dispatchable(self):
        return self.status == self.Status.ACTIVE and not self.documents_expired

    def get_operational_status(self):
        if self.status == self.Status.ACTIVE and self.documents_expired:
            return "Documentación vencida"
        return self.get_status_display()


class Driver(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Activo"
        SUSPENDED = "suspended", "Suspendido"
        INACTIVE = "inactive", "Inactivo"

    document_number = models.CharField("DNI", max_length=12, unique=True)
    full_name = models.CharField("nombre completo", max_length=120)
    phone = models.CharField("teléfono", max_length=20, blank=True)
    license_number = models.CharField("número de brevete", max_length=30, unique=True)
    license_expiry = models.DateField("vencimiento del brevete")
    status = models.CharField(
        "estado", max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    notes = models.TextField("observaciones", blank=True)
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        ordering = ["full_name"]
        verbose_name = "conductor"
        verbose_name_plural = "conductores"

    def __str__(self):
        return self.full_name

    @property
    def license_expired(self):
        return self.license_expiry < timezone.localdate()

    @property
    def dispatchable(self):
        return self.status == self.Status.ACTIVE and not self.license_expired

    def get_operational_status(self):
        if self.status == self.Status.ACTIVE and self.license_expired:
            return "Brevete vencido"
        return self.get_status_display()


class Route(models.Model):
    code = models.CharField("código", max_length=12, unique=True)
    name = models.CharField("nombre", max_length=100)
    origin = models.CharField("origen", max_length=120, blank=True)
    destination = models.CharField("destino", max_length=120, blank=True)
    distance_km = models.DecimalField(
        "distancia (km)", max_digits=7, decimal_places=2, null=True, blank=True
    )
    duration_minutes = models.PositiveSmallIntegerField(
        "duración estimada (minutos)", null=True, blank=True
    )
    color = models.CharField(
        "color en el mapa",
        max_length=7,
        default="#16845b",
        validators=[
            RegexValidator(
                regex=r"^#[0-9A-Fa-f]{6}$",
                message="Usa un color hexadecimal válido, por ejemplo #16845b.",
            )
        ],
    )
    active = models.BooleanField("activa", default=True)
    description = models.TextField("descripción", blank=True)
    created_at = models.DateTimeField("registrada", auto_now_add=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "ruta"
        verbose_name_plural = "rutas"

    def __str__(self):
        return f"{self.code} · {self.name}"


class Stop(models.Model):
    route = models.ForeignKey(
        Route, on_delete=models.CASCADE, related_name="stops", verbose_name="ruta"
    )
    name = models.CharField("nombre del paradero", max_length=120)
    sequence = models.PositiveSmallIntegerField(
        "orden", validators=[MinValueValidator(1)]
    )
    address = models.CharField("dirección o referencia", max_length=200, blank=True)
    latitude = models.DecimalField(
        "latitud", max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        "longitud", max_digits=9, decimal_places=6, null=True, blank=True
    )
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        ordering = ["route", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["route", "sequence"], name="unique_stop_order_per_route"
            )
        ]
        verbose_name = "paradero"
        verbose_name_plural = "paraderos"

    def __str__(self):
        return f"{self.route.code} · {self.sequence}. {self.name}"

    def clean(self):
        super().clean()
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError(
                "Ingresa tanto la latitud como la longitud, o deja ambas vacías."
            )
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValidationError({"latitude": "La latitud debe estar entre -90 y 90."})
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValidationError(
                {"longitude": "La longitud debe estar entre -180 y 180."}
            )


class Shift(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Programado"
        IN_PROGRESS = "in_progress", "En curso"
        COMPLETED = "completed", "Completado"
        CANCELLED = "cancelled", "Cancelado"

    service_date = models.DateField("fecha")
    route = models.ForeignKey(
        Route, on_delete=models.PROTECT, related_name="shifts", verbose_name="ruta"
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.PROTECT, related_name="shifts", verbose_name="conductor"
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.PROTECT, related_name="shifts", verbose_name="unidad"
    )
    planned_departure = models.TimeField("hora de salida programada")
    status = models.CharField(
        "estado", max_length=12, choices=Status.choices, default=Status.SCHEDULED
    )
    notes = models.TextField("observaciones", blank=True)
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        ordering = ["service_date", "planned_departure"]
        constraints = [
            models.UniqueConstraint(
                fields=["service_date", "driver", "planned_departure"],
                name="unique_driver_shift_start",
            ),
            models.UniqueConstraint(
                fields=["service_date", "vehicle", "planned_departure"],
                name="unique_vehicle_shift_start",
            ),
        ]
        verbose_name = "turno"
        verbose_name_plural = "turnos"

    def __str__(self):
        return f"{self.service_date:%d/%m/%Y} · {self.route.code} · {self.planned_departure:%H:%M}"

    def clean(self):
        super().clean()
        if self.driver_id and (
            self.driver.status != Driver.Status.ACTIVE
            or (
                self.service_date
                and self.driver.license_expiry < self.service_date
            )
        ):
            raise ValidationError(
                {"driver": "El conductor debe estar activo y tener el brevete vigente."}
            )
        if self.vehicle_id and (
            self.vehicle.status != Vehicle.Status.ACTIVE
            or (
                self.service_date
                and (
                    self.vehicle.soat_expiry < self.service_date
                    or self.vehicle.technical_review_expiry < self.service_date
                )
            )
        ):
            raise ValidationError(
                {
                    "vehicle": (
                        "La unidad debe estar activa y tener el SOAT y la revisión "
                        "técnica vigentes."
                    )
                }
            )


class Dispatch(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Pendiente"
        IN_PROGRESS = "in_progress", "En ruta"
        COMPLETED = "completed", "Finalizado"

    shift = models.ForeignKey(
        Shift, on_delete=models.PROTECT, related_name="dispatches", verbose_name="turno"
    )
    sequence = models.PositiveSmallIntegerField(
        "número de vuelta", validators=[MinValueValidator(1)]
    )
    status = models.CharField(
        "estado", max_length=12, choices=Status.choices, default=Status.SCHEDULED
    )
    departure_at = models.DateTimeField("salida real", null=True, blank=True)
    arrival_at = models.DateTimeField("llegada real", null=True, blank=True)
    notes = models.TextField("observaciones", blank=True)
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        ordering = ["shift__service_date", "shift__planned_departure", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["shift", "sequence"], name="unique_dispatch_sequence_per_shift"
            )
        ]
        verbose_name = "despacho"
        verbose_name_plural = "despachos"

    def __str__(self):
        return f"{self.shift} · vuelta {self.sequence}"

    def clean(self):
        super().clean()
        if self.departure_at and self.arrival_at and self.arrival_at < self.departure_at:
            raise ValidationError(
                {"arrival_at": "La llegada no puede ser anterior a la salida."}
            )
        if self.status == self.Status.IN_PROGRESS and not self.departure_at:
            raise ValidationError(
                {"departure_at": "Registra la salida antes de iniciar la vuelta."}
            )
        if self.status == self.Status.COMPLETED and not self.arrival_at:
            raise ValidationError(
                {"arrival_at": "Registra la llegada antes de finalizar la vuelta."}
            )

    @property
    def control_summary(self):
        passages = self.passages.all()
        if not passages:
            return "Sin controles"
        return " · ".join(
            f"{passage.stop.name} ({timezone.localtime(passage.passed_at):%H:%M})"
            for passage in passages
        )


class PassageRecord(models.Model):
    dispatch = models.ForeignKey(
        Dispatch,
        on_delete=models.CASCADE,
        related_name="passages",
        verbose_name="despacho",
    )
    stop = models.ForeignKey(
        Stop, on_delete=models.PROTECT, related_name="passages", verbose_name="paradero"
    )
    passed_at = models.DateTimeField("hora de paso", default=timezone.now)
    notes = models.CharField("observaciones", max_length=250, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="passage_records",
        verbose_name="registrado por",
    )

    class Meta:
        ordering = ["-passed_at"]
        verbose_name = "control de paso"
        verbose_name_plural = "controles de paso"

    def __str__(self):
        return f"{self.dispatch} · {self.stop}"

    def clean(self):
        super().clean()
        if (
            self.dispatch_id
            and self.stop_id
            and self.dispatch.shift.route_id != self.stop.route_id
        ):
            raise ValidationError(
                {"stop": "Selecciona un paradero de la ruta asignada al despacho."}
            )


class Incident(models.Model):
    class Category(models.TextChoices):
        BREAKDOWN = "breakdown", "Falla mecánica"
        DELAY = "delay", "Demora"
        SAFETY = "safety", "Seguridad"
        ROUTE = "route", "Desvío o ruta"
        OTHER = "other", "Otro"

    class Severity(models.TextChoices):
        LOW = "low", "Baja"
        MEDIUM = "medium", "Media"
        HIGH = "high", "Alta"
        CRITICAL = "critical", "Crítica"

    class Status(models.TextChoices):
        OPEN = "open", "Abierta"
        REVIEWING = "reviewing", "En revisión"
        RESOLVED = "resolved", "Resuelta"

    dispatch = models.ForeignKey(
        Dispatch,
        on_delete=models.SET_NULL,
        related_name="incidents",
        verbose_name="despacho",
        null=True,
        blank=True,
    )
    category = models.CharField("tipo", max_length=12, choices=Category.choices)
    severity = models.CharField(
        "prioridad", max_length=10, choices=Severity.choices, default=Severity.MEDIUM
    )
    description = models.TextField("descripción")
    location = models.CharField("ubicación", max_length=200, blank=True)
    status = models.CharField(
        "estado", max_length=12, choices=Status.choices, default=Status.OPEN
    )
    resolution_notes = models.TextField("resolución", blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reported_incidents",
        verbose_name="reportada por",
    )
    created_at = models.DateTimeField("reportada", auto_now_add=True)
    resolved_at = models.DateTimeField("resuelta el", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "incidencia"
        verbose_name_plural = "incidencias"

    def __str__(self):
        return f"{self.get_category_display()} · {self.created_at:%d/%m/%Y}"

    def clean(self):
        super().clean()
        if self.status == self.Status.RESOLVED and not self.resolution_notes.strip():
            raise ValidationError(
                {"resolution_notes": "Añade una nota antes de cerrar la incidencia."}
            )
