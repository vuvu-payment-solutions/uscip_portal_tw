from html.parser import HTMLParser

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from portal.models import (
    SoftwareApprovalHistory,
    SoftwareRequest,
    UserProfile,
)


class SelectInspector(HTMLParser):
    """Extract attributes and selected value for named <select> elements."""

    def __init__(self):
        super().__init__()
        self.selects = {}
        self._current_select = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "select":
            name = attrs_dict.get("name")
            if name:
                self._current_select = name
                self.selects[name] = {
                    "attrs": attrs_dict,
                    "selected_value": None,
                }

        elif tag == "option" and self._current_select:
            if "selected" in attrs_dict:
                self.selects[self._current_select]["selected_value"] = attrs_dict.get(
                    "value"
                )

    def handle_endtag(self, tag):
        if tag == "select":
            self._current_select = None


class SoftwareResubmitFlowTests(TestCase):
    """Regression tests for Software Application create/resubmit behavior."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="software_test_user",
            password="Strong-Test-Password-123!",
            email="software-test@example.com",
        )

        UserProfile.objects.update_or_create(
            user=self.user,
            defaults={
                "role": "user",
                "department": "CS",
                "full_name": "Software Test User",
            },
        )

        self.client.force_login(self.user)

    def _create_returned_request(self, department="CS"):
        return SoftwareRequest.objects.create(
            applicant=self.user,
            department=department,
            software_name="Visual Studio Code",
            software_version="1.92.0",
            vendor="Microsoft",
            request_type="Version Upgrade",
            license_type="Commercial",
            target_device="TEST-PC-001",
            business_purpose="Automated regression test",
            data_level="Confidential",
            internet_access_required=True,
            admin_privilege_required=False,
            security_concern="Extension security review required",
            status="Returned",
            return_reason="Please confirm the requested version.",
        )

    @staticmethod
    def _inspect_selects(response):
        parser = SelectInspector()
        parser.feed(response.content.decode(response.charset or "utf-8"))
        return parser.selects

    def test_new_application_department_is_editable(self):
        """New requests must allow the applicant to select Department."""
        response = self.client.get(reverse("software_apply"))

        self.assertEqual(response.status_code, 200)

        selects = self._inspect_selects(response)
        department = selects["department"]

        self.assertNotIn(
            "disabled",
            department["attrs"],
            "Department should be editable for a new Software Application.",
        )

    def test_resubmit_department_is_disabled_and_original_values_are_selected(self):
        """Returned requests must display original values and lock Department."""
        item = self._create_returned_request(department="CS")

        response = self.client.get(
            reverse("resubmit_software", args=[item.pk])
        )

        self.assertEqual(response.status_code, 200)

        selects = self._inspect_selects(response)

        self.assertIn(
            "disabled",
            selects["department"]["attrs"],
            "Department must be disabled during resubmission.",
        )
        self.assertEqual(selects["department"]["selected_value"], "CS")
        self.assertEqual(
            selects["request_type"]["selected_value"],
            "Version Upgrade",
        )
        self.assertEqual(
            selects["license_type"]["selected_value"],
            "Commercial",
        )
        self.assertEqual(
            selects["data_level"]["selected_value"],
            "Confidential",
        )

    def test_resubmit_preserves_original_department_even_when_post_is_tampered(self):
        """Backend must ignore a changed Department sent by the browser."""
        item = self._create_returned_request(department="CS")

        response = self.client.post(
            reverse("resubmit_software", args=[item.pk]),
            {
                # Deliberately tampered value; backend must ignore it.
                "department": "IT",
                "software_name": "Visual Studio Code",
                "software_version": "1.93.0",
                "vendor": "Microsoft",
                "request_type": "Version Upgrade",
                "license_type": "Commercial",
                "target_device": "TEST-PC-001",
                "business_purpose": "Automated regression test updated",
                "data_level": "Confidential",
                "internet_access_required": "on",
                "security_concern": "Extension security review completed",
            },
        )

        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()

        self.assertEqual(item.department, "CS")
        self.assertEqual(item.status, "Pending Team Leader")
        self.assertEqual(item.request_type, "Version Upgrade")
        self.assertEqual(item.license_type, "Commercial")
        self.assertEqual(item.data_level, "Confidential")

        self.assertTrue(
            SoftwareApprovalHistory.objects.filter(
                software_request=item,
                action="resubmit",
                from_status="Returned",
                to_status="Pending Team Leader",
            ).exists(),
            "A resubmit Approval History record should be created.",
        )

    def test_it_resubmit_returns_to_pending_supervisor(self):
        """IT requests must return to Supervisor after resubmission."""
        item = self._create_returned_request(department="IT")

        response = self.client.post(
            reverse("resubmit_software", args=[item.pk]),
            {
                "department": "CS",  # Tampered; must be ignored.
                "software_name": "Visual Studio Code",
                "software_version": "1.93.0",
                "vendor": "Microsoft",
                "request_type": "Version Upgrade",
                "license_type": "Commercial",
                "target_device": "TEST-PC-001",
                "business_purpose": "IT automated regression test",
                "data_level": "Confidential",
                "internet_access_required": "on",
                "security_concern": "Validated",
            },
        )

        self.assertEqual(response.status_code, 302)

        item.refresh_from_db()

        self.assertEqual(item.department, "IT")
        self.assertEqual(item.status, "Pending Supervisor")

        self.assertTrue(
            SoftwareApprovalHistory.objects.filter(
                software_request=item,
                action="resubmit",
                from_status="Returned",
                to_status="Pending Supervisor",
            ).exists(),
            "IT resubmission history should point to Pending Supervisor.",
        )

    def test_non_it_departments_return_to_team_leader(self):
        """CS, Marketing, and Procurement must return to Team Leader."""
        for department in ("CS", "Marketing", "Procurement"):
            with self.subTest(department=department):
                item = self._create_returned_request(department=department)

                response = self.client.post(
                    reverse("resubmit_software", args=[item.pk]),
                    {
                        "department": "IT",  # Tampered; must be ignored.
                        "software_name": "Visual Studio Code",
                        "software_version": "1.93.0",
                        "vendor": "Microsoft",
                        "request_type": "Version Upgrade",
                        "license_type": "Commercial",
                        "target_device": "TEST-PC-001",
                        "business_purpose": f"{department} regression test",
                        "data_level": "Confidential",
                        "security_concern": "Validated",
                    },
                )

                self.assertEqual(response.status_code, 302)

                item.refresh_from_db()

                self.assertEqual(item.department, department)
                self.assertEqual(item.status, "Pending Team Leader")
                self.assertTrue(
                    SoftwareApprovalHistory.objects.filter(
                        software_request=item,
                        action="resubmit",
                        to_status="Pending Team Leader",
                    ).exists()
                )
