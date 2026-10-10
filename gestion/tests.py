from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Dispatch, Driver, Incident, PassageRecord, Route, Shift, Stop, Vehicle


class OperationsTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="operador", password="test-password-123"
        )
        self.client.force_login(self.user)
        self.today = timezone.localdate()
        self.route = Route.objects.create(
            code="A", name="Ruta A", origin="California", destination="Centro"
        )
        self.driver = Driver.objects.create(
            document_number="12345678",
            full_name="Ana Conductora",
            license_number="Q12345678",
            license_expiry=self.today + timedelta(days=365),
        )
        self.vehicle = Vehicle.objects.create(
            unit_code="U001",
            plate="ABC-123",
            brand_model="Hyundai County",
            year=2022,
            capacity=30,
            soat_expiry=self.today + timedelta(days=180),
            technical_review_expiry=self.today + timedelta(days=180),
        )
        self.shift = Shift.objects.create(
            service_date=self.today,
            route=self.route,
            driver=self.driver,
            vehicle=self.vehicle,
            planned_departure=time(8, 0),
        )

    def test_business_pages_require_login(self):
        self.client.logout()
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(
            response, f"{reverse('login')}?next={reverse('dashboard')}"
        )

    def test_login_page_and_post_logout_work(self):
        self.client.logout()
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')

        self.assertTrue(
            self.client.login(username="operador", password="test-password-123")
        )
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertRedirects(
            self.client.get(reverse("dashboard")),
            f"{reverse('login')}?next={reverse('dashboard')}",
        )

    def test_all_primary_modules_render(self):
        urls = [
            "dashboard",
            "fleet_list",
            "drivers_list",
            "routes_list",
            "stops_list",
            "shifts_list",
            "dispatch_list",
            "incidents_list",
            "reports",
        ]
        for url_name in urls:
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(url_name)).status_code, 200)

    def test_vehicle_registration_persists_and_validates(self):
        response = self.client.post(
            reverse("fleet_create"),
            {
                "unit_code": "U002",
                "plate": "ABC-456",
                "brand_model": "Toyota Coaster",
                "year": 2023,
                "capacity": 28,
                "soat_expiry": self.today + timedelta(days=180),
                "technical_review_expiry": self.today + timedelta(days=180),
                "maintenance_due": "",
                "status": Vehicle.Status.ACTIVE,
                "notes": "",
            },
        )
        self.assertRedirects(response, reverse("fleet_list"))
        self.assertTrue(Vehicle.objects.filter(unit_code="U002").exists())

    def test_route_and_stop_forms_create_a_map_ready_route(self):
        response = self.client.post(
            reverse("routes_create"),
            {
                "code": "C",
                "name": "Ruta C",
                "origin": "California",
                "destination": "Centro",
                "distance_km": "12.50",
                "duration_minutes": 45,
                "color": "#167a55",
                "active": "on",
                "description": "",
            },
        )
        self.assertRedirects(response, reverse("routes_list"))
        route = Route.objects.get(code="C")
        response = self.client.post(
            reverse("stops_create"),
            {
                "route": route.pk,
                "sequence": 1,
                "name": "Paradero central",
                "address": "Plaza principal",
                "latitude": "-8.111600",
                "longitude": "-79.028600",
            },
        )
        self.assertRedirects(response, reverse("stops_list"))
        map_response = self.client.get(reverse("routes_list"), {"route": route.pk})
        self.assertEqual(
            map_response.context["map_stops"],
            [
                {
                    "name": "Paradero central",
                    "sequence": 1,
                    "latitude": -8.1116,
                    "longitude": -79.0286,
                }
            ],
        )

    def test_shift_and_dispatch_forms_create_multiple_rounds(self):
        response = self.client.post(
            reverse("shifts_create"),
            {
                "service_date": self.today,
                "route": self.route.pk,
                "driver": self.driver.pk,
                "vehicle": self.vehicle.pk,
                "planned_departure": "09:30",
                "notes": "",
            },
        )
        self.assertRedirects(response, reverse("shifts_list"))
        shift = Shift.objects.get(planned_departure=time(9, 30))
        self.assertEqual(shift.status, Shift.Status.SCHEDULED)
        for sequence in (1, 2):
            response = self.client.post(
                reverse("dispatch_create"),
                {"shift": shift.pk, "sequence": sequence, "notes": ""},
            )
            self.assertRedirects(response, reverse("dispatch_list"))
        self.assertEqual(shift.dispatches.count(), 2)

    def test_shift_cannot_be_assigned_to_driver_with_expired_license(self):
        self.driver.license_expiry = self.today - timedelta(days=1)
        self.driver.save()
        self.assertFalse(self.driver.dispatchable)
        form_response = self.client.post(
            reverse("shifts_create"),
            {
                "service_date": self.today,
                "route": self.route.pk,
                "driver": self.driver.pk,
                "vehicle": self.vehicle.pk,
                "planned_departure": "09:00",
                "status": Shift.Status.SCHEDULED,
                "notes": "",
            },
        )
        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, "brevete vigente")
        self.assertEqual(Shift.objects.count(), 1)

    def test_shift_cannot_be_assigned_to_vehicle_with_expired_documents(self):
        self.vehicle.soat_expiry = self.today - timedelta(days=1)
        self.vehicle.save()
        response = self.client.post(
            reverse("shifts_create"),
            {
                "service_date": self.today,
                "route": self.route.pk,
                "driver": self.driver.pk,
                "vehicle": self.vehicle.pk,
                "planned_departure": "09:00",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "documentos vigentes")
        self.assertEqual(Shift.objects.count(), 1)

    def test_dispatch_records_departure_arrival_and_completes_shift(self):
        dispatch = Dispatch.objects.create(shift=self.shift, sequence=1)

        response = self.client.post(
            reverse("dispatch_action", args=[dispatch.pk, "depart"])
        )
        dispatch.refresh_from_db()
        self.shift.refresh_from_db()
        self.assertRedirects(response, reverse("dispatch_list"))
        self.assertEqual(dispatch.status, Dispatch.Status.IN_PROGRESS)
        self.assertIsNotNone(dispatch.departure_at)
        self.assertEqual(self.shift.status, Shift.Status.IN_PROGRESS)

        response = self.client.post(
            reverse("dispatch_action", args=[dispatch.pk, "arrive"])
        )
        dispatch.refresh_from_db()
        self.shift.refresh_from_db()
        self.assertRedirects(response, reverse("dispatch_list"))
        self.assertEqual(dispatch.status, Dispatch.Status.COMPLETED)
        self.assertGreaterEqual(dispatch.arrival_at, dispatch.departure_at)
        self.assertEqual(self.shift.status, Shift.Status.IN_PROGRESS)

        second_dispatch = Dispatch.objects.create(shift=self.shift, sequence=2)
        response = self.client.post(
            reverse("shift_action", args=[self.shift.pk, "close"]), follow=True
        )
        second_dispatch.refresh_from_db()
        self.shift.refresh_from_db()
        self.assertEqual(self.shift.status, Shift.Status.IN_PROGRESS)
        self.assertEqual(second_dispatch.status, Dispatch.Status.SCHEDULED)
        self.assertContains(response, "Finaliza todas las vueltas")

        self.client.post(
            reverse("dispatch_action", args=[second_dispatch.pk, "depart"])
        )
        self.client.post(
            reverse("dispatch_action", args=[second_dispatch.pk, "arrive"])
        )
        response = self.client.post(
            reverse("shift_action", args=[self.shift.pk, "close"])
        )
        self.shift.refresh_from_db()
        self.assertRedirects(response, reverse("shifts_list"))
        self.assertEqual(self.shift.status, Shift.Status.COMPLETED)

    def test_inspector_can_record_route_checkpoint_during_trip(self):
        dispatch = Dispatch.objects.create(
            shift=self.shift,
            sequence=1,
            status=Dispatch.Status.IN_PROGRESS,
            departure_at=timezone.now(),
        )
        stop = Stop.objects.create(
            route=self.route,
            name="Plaza principal",
            sequence=1,
            latitude="-8.111600",
            longitude="-79.028600",
        )
        response = self.client.post(
            reverse("passage_create", args=[dispatch.pk]),
            {"stop": stop.pk, "notes": "Paso verificado"},
        )
        self.assertRedirects(response, reverse("dispatch_list"))
        passage = PassageRecord.objects.get(dispatch=dispatch)
        self.assertEqual(passage.stop, stop)
        self.assertEqual(passage.recorded_by, self.user)

    def test_route_rejects_a_stop_with_coordinates_from_only_one_axis(self):
        stop = Stop(
            route=self.route,
            name="Paradero incompleto",
            sequence=1,
            latitude="-8.111600",
        )
        with self.assertRaises(ValidationError):
            stop.full_clean()

    def test_incident_cannot_be_closed_without_resolution_notes(self):
        incident = Incident(
            category=Incident.Category.DELAY,
            severity=Incident.Severity.MEDIUM,
            description="Demora en la ruta",
            status=Incident.Status.RESOLVED,
            reported_by=self.user,
        )
        with self.assertRaises(ValidationError):
            incident.full_clean()

    def test_incident_creation_and_resolution_are_audited(self):
        response = self.client.post(
            reverse("incidents_create"),
            {
                "dispatch": "",
                "category": Incident.Category.DELAY,
                "severity": Incident.Severity.HIGH,
                "description": "Tráfico en la ruta",
                "location": "Avenida principal",
                "status": Incident.Status.OPEN,
                "resolution_notes": "",
            },
        )
        self.assertRedirects(response, reverse("incidents_list"))
        incident = Incident.objects.get()
        self.assertEqual(incident.reported_by, self.user)
        self.assertIsNone(incident.resolved_at)

        response = self.client.post(
            reverse("incidents_edit", args=[incident.pk]),
            {
                "dispatch": "",
                "category": incident.category,
                "severity": incident.severity,
                "description": incident.description,
                "location": incident.location,
                "status": Incident.Status.RESOLVED,
                "resolution_notes": "Se normalizó el tránsito.",
            },
        )
        self.assertRedirects(response, reverse("incidents_list"))
        incident.refresh_from_db()
        self.assertEqual(incident.status, Incident.Status.RESOLVED)
        self.assertIsNotNone(incident.resolved_at)

    def test_csv_report_is_downloadable_and_contains_dispatch_rows(self):
        Dispatch.objects.create(shift=self.shift, sequence=1)
        response = self.client.get(reverse("export_report"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("ABC-123", response.content.decode("utf-8-sig"))
