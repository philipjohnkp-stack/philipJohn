import json
import smtplib
import tempfile
import unittest
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from pypdf import PdfReader

from analysis_reports import analyze, build_pdf, chart_svg, profile_data
from app import create_app
from mailer import DeliveryUncertain, email_ready, send_report
from privacy import MASK, redact_rows, redact_text, protect_text
from sql_assistant import AssistantError, QueryResult
from test_assistant import SCHEMA, SETTINGS


MODEL_REPORT = {
    "title": "Department review", "summary": "Sales have the larger returned total.",
    "findings": ["Sales total is 120."], "actions": ["Review department performance."],
    "limitations": ["No comparison period is available."],
}


def document():
    assistant = MagicMock()
    assistant.query.return_value = QueryResult(["department", "total"], [["Sales", 120], ["Support", 80]], False)
    assistant.complete.return_value = MODEL_REPORT
    return analyze(assistant, "Compare departments", [], SCHEMA)


class PrivacyTests(unittest.TestCase):
    def test_restored_table_values_keep_only_credentials_private(self):
        rows, _, _ = redact_rows(
            "SELECT name, email, api_key AS value FROM sales.customers",
            ["name", "email", "value"], [["Alice Example", "alice@example.com", "secret-value"]],
            credential_only=True,
        )
        self.assertEqual(rows, [["Alice Example", "alice@example.com", MASK]])
        self.assertEqual(protect_text("Find alice@example.com"), "Find alice@example.com")
        self.assertNotIn("secret-value", protect_text("api_key=secret-value"))

    def test_aliases_and_free_text_are_masked(self):
        rows, columns, count = redact_rows(
            "SELECT first_name AS label, email, notes, salary FROM sales.customers",
            ["label", "email", "notes", "salary"],
            [["Alice Example", "alice@example.com", "Call Alice Example at 212-555-0199", 100]],
        )
        self.assertEqual(rows[0][:2], [MASK, MASK])
        self.assertNotIn("Alice", rows[0][2])
        self.assertNotIn("212", rows[0][2])
        self.assertEqual(rows[0][3], 100)
        self.assertEqual(set(columns), {"label", "email"})
        self.assertEqual(count, 3)

    def test_cte_and_union_alias_lineage(self):
        for sql in (
            "WITH c AS (SELECT email AS value FROM sales.customers) SELECT value AS label FROM c",
            "SELECT department_name AS label FROM sales.customers UNION ALL SELECT first_name FROM sales.customers",
        ):
            rows, _, _ = redact_rows(sql, ["label"], [["Alice Example"]])
            self.assertEqual(rows, [[MASK]])

    def test_counts_and_business_dimensions_remain_usable(self):
        rows, _, _ = redact_rows(
            "SELECT department_name, COUNT(customer_id) AS total FROM sales.customers GROUP BY department_name",
            ["department_name", "total"], [["Sales", 12]],
        )
        self.assertEqual(rows, [["Sales", 12]])

    def test_json_identifier_extraction_is_masked(self):
        rows, _, _ = redact_rows(
            "SELECT JSON_EXTRACT(payload, '$.first_name') AS label FROM sales.customers",
            ["label"], [["Alice"]],
        )
        self.assertEqual(rows, [[MASK]])

    def test_recognized_text_identifiers_are_masked(self):
        text = redact_text("Email alice@example.com, phone 212-555-0199, card 4111-1111-1111-1111; salary for Alice Example")
        for value in ("alice@example.com", "212-555-0199", "4111", "Alice Example"):
            self.assertNotIn(value, text)


class ReportTests(unittest.TestCase):
    def test_numeric_profile_and_chart_and_pdf(self):
        profile = profile_data(QueryResult(["amount"], [[Decimal("0.0000001")], [Decimal("0.0000003")]], False))
        self.assertEqual(profile["columns"][0]["mean"], "0.0000002")
        report = document()
        self.assertIn(b"<svg", chart_svg(report))
        pdf = build_pdf(report)
        self.assertTrue(pdf.startswith(b"%PDF"))
        extracted = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("Department review", extracted)
        self.assertIn("120", extracted)

    def test_personal_values_do_not_enter_model_or_pdf(self):
        rows, private, count = redact_rows(
            "SELECT first_name AS label, salary FROM sales.customers", ["label", "salary"],
            [["Alice Example", 100], ["Bob Example", 200]],
        )
        assistant = MagicMock()
        assistant.query.return_value = QueryResult(["label", "salary"], rows, False, private, count)
        assistant.complete.return_value = MODEL_REPORT
        report = analyze(assistant, "Review compensation", [], SCHEMA)
        self.assertNotIn("Alice Example", str(assistant.complete.call_args))
        self.assertNotIn("Bob Example", json.dumps(report))
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(build_pdf(report))).pages)
        self.assertNotIn("Alice Example", text)
        self.assertIn(MASK, text)

    def test_clarification_and_invalid_response(self):
        assistant = MagicMock()
        assistant.query.return_value = "Which department?"
        self.assertEqual(analyze(assistant, "Review data", [], SCHEMA), "Which department?")
        assistant.complete.assert_not_called()
        assistant.query.return_value = QueryResult(["count"], [[0]], False)
        assistant.complete.return_value = {}
        with self.assertRaises(AssistantError):
            analyze(assistant, "Count", [], SCHEMA)


class FlaskTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = create_app({"TESTING": True, "STORE_PATH": Path(self.directory.name) / "test.sqlite3"})
        self.client = self.app.test_client()
        self.client.get("/")
        with self.client.session_transaction() as state:
            self.csrf = state["csrf"]
        self.config = patch("app.read_config", return_value={"OWNER_PASSWORD": "a-long-owner-password"})
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_store_path_can_use_persistent_deployment_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "persistent" / "studio.sqlite3"
            with patch.dict("os.environ", {"STORE_PATH": str(store_path)}):
                app = create_app({"TESTING": True})
            self.assertEqual(app.extensions["store"].path, store_path)

    def post(self, path, data=None):
        return self.client.post(path, json=data or {}, headers={"X-CSRF-Token": self.csrf})

    def make_report(self):
        with patch("app.Settings.from_env", return_value=SETTINGS), patch("app.SQLAssistant") as assistant, patch("app.analyze", return_value=document()):
            assistant.return_value.discover_schema.return_value = SCHEMA
            result = self.post("/api/chat", {"question": "Compare departments", "mode": "analysis"})
            self.assertEqual(result.status_code, 200, result.get_json())
            return result.get_json()["message"]["report_id"]

    def test_ui_has_no_private_settings_and_csrf_is_required(self):
        html = self.client.get("/").get_data(as_text=True)
        for private in ("DB_PASSWORD", "SMTP", "root@", "sql_assistant", "Send to my Gmail"):
            self.assertNotIn(private, html)
        self.assertIn('id="report-preview"', html)
        self.assertNotIn("<iframe", html)
        self.assertIn("Created by Philip John", html)
        self.assertIn("All rights reserved 2026", html)
        self.assertIn('id="voice-input"', html)
        self.assertIn('id="recent-chats"', html)
        self.assertIn('/static/monogram.png', html)
        with self.client.get("/static/monogram.png") as icon:
            self.assertEqual(icon.mimetype, "image/png")
            self.assertTrue(icon.data.startswith(b"\x89PNG"))
        self.assertEqual(self.client.post("/api/chat", json={"question": "Count"}).status_code, 403)
        self.assertEqual(self.post("/api/chat", {"question": "Count", "mode": []}).status_code, 400)

    def test_recent_chats_can_be_reopened_only_by_the_same_browser(self):
        self.make_report()
        first = self.client.get("/api/state").json
        original_id = first["chat_id"]
        self.assertEqual(first["recent_chats"][0]["title"], "Compare departments")
        self.post("/api/new")
        second = self.client.get("/api/state").json
        self.assertNotEqual(second["chat_id"], original_id)
        self.assertEqual(second["messages"], [])
        self.assertEqual(second["recent_chats"][0]["id"], original_id)
        self.assertEqual(self.post("/api/chat/switch", {"chat_id": original_id}).status_code, 200)
        restored = self.client.get("/api/state").json
        self.assertEqual(restored["messages"], first["messages"])
        outsider = self.app.test_client()
        outsider.get("/")
        with outsider.session_transaction() as state:
            token = state["csrf"]
        self.assertEqual(outsider.get("/api/state").json["recent_chats"], [])
        self.assertEqual(outsider.post(
            "/api/chat/switch", json={"chat_id": original_id}, headers={"X-CSRF-Token": token}
        ).status_code, 404)

    def test_recent_history_is_bounded(self):
        for _ in range(25):
            self.post("/api/new")
        with self.client.session_transaction() as state:
            self.assertLessEqual(len(state["chat_ids"]), 20)

    def test_reports_are_session_scoped_and_pdf_is_previewable(self):
        report_id = self.make_report()
        pdf = self.client.get(f"/api/reports/{report_id}/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertIn("frame-ancestors 'self'", pdf.headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", self.client.get("/").headers["Content-Security-Policy"])
        outsider = self.app.test_client()
        self.assertEqual(outsider.get(f"/api/reports/{report_id}/pdf").status_code, 404)
        self.assertEqual(self.client.get(f"/api/reports/{report_id}/chart.svg").mimetype, "image/svg+xml")

    def test_email_requires_owner_preview_and_no_duplicate_send(self):
        report_id = self.make_report()
        route = f"/api/reports/{report_id}"
        self.assertEqual(self.post(route + "/email").status_code, 403)
        self.assertEqual(self.post("/api/owner/login", {"password": "a-long-owner-password"}).status_code, 200)
        self.assertEqual(self.post(route + "/email").status_code, 409)
        self.post(route + "/preview")
        with patch("app.email_ready", return_value=True), patch("app.send_report") as send:
            self.assertEqual(self.post(route + "/email").status_code, 200)
            self.assertEqual(self.post(route + "/email").status_code, 409)
            send.assert_called_once()
            self.assertTrue(send.call_args.args[1].startswith(b"%PDF"))

    def test_unknown_delivery_is_not_retried(self):
        report_id = self.make_report()
        route = f"/api/reports/{report_id}"
        self.post("/api/owner/login", {"password": "a-long-owner-password"})
        self.post(route + "/preview")
        with patch("app.email_ready", return_value=True), patch("app.send_report", side_effect=DeliveryUncertain("Unconfirmed")) as send:
            self.assertEqual(self.post(route + "/email").status_code, 422)
            self.assertEqual(self.post(route + "/email").status_code, 409)
            send.assert_called_once()

    def test_personal_table_context_is_available_to_queries(self):
        with patch("app.Settings.from_env", return_value=SETTINGS), patch("app.SQLAssistant") as assistant:
            assistant.return_value.answer.return_value = "No matching records."
            result = self.post("/api/chat", {"question": "Find alice@example.com", "mode": "chat"})
            self.assertEqual(result.status_code, 200)
            self.assertIn("alice@example.com", str(assistant.return_value.answer.call_args))
        self.assertIn("alice@example.com", self.client.get("/api/state").get_data(as_text=True))

    def test_table_browsing_restores_values_and_rejects_unknown_tables(self):
        with patch("app.Settings.from_env", return_value=SETTINGS), patch("app.SQLAssistant") as factory:
            assistant = factory.return_value
            assistant.discover_schema.return_value = SCHEMA
            assistant.execute.side_effect = [
                QueryResult(["total"], [[51]], False),
                QueryResult(["id", "name"], [[7, "Alice Example"]], False),
            ]
            result = self.client.get("/api/table?database=sales&table=customers")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json["rows"], [[7, "Alice Example"]])
            self.assertTrue(result.json["has_more"])
            self.assertEqual(result.json["next_offset"], 1)
            self.assertEqual(self.client.get("/api/table?database=sales&table=missing").status_code, 404)
            self.assertEqual(self.client.get("/api/table?database=sales&table=customers&offset=-1").status_code, 400)


class MailTests(unittest.TestCase):
    @patch("mailer.read_config", return_value={
        "SMTP_USERNAME": "", "SMTP_APP_PASSWORD": "",
        "GMAIL_USERNAME": "owner@gmail.com", "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop",
    })
    @patch("mailer.smtplib.SMTP")
    def test_gmail_aliases_are_recognized_and_used_for_sending(self, smtp, config):
        smtp.return_value.send_message.return_value = {}
        self.assertTrue(email_ready())
        send_report("Report", b"%PDF-test")
        smtp.return_value.login.assert_called_once_with("owner@gmail.com", "abcdefghijklmnop")

    @patch("mailer.read_config", return_value={
        "SMTP_USERNAME": "primary@gmail.com", "SMTP_APP_PASSWORD": "primary-password",
        "GMAIL_USERNAME": "alias@gmail.com", "GMAIL_APP_PASSWORD": "alias-password",
    })
    @patch("mailer.smtplib.SMTP")
    def test_explicit_smtp_settings_take_precedence(self, smtp, config):
        smtp.return_value.send_message.return_value = {}
        send_report("Report", b"%PDF-test")
        smtp.return_value.login.assert_called_once_with("primary@gmail.com", "primary-password")

    @patch("mailer.read_config", return_value={"SMTP_USERNAME": "owner@gmail.com", "SMTP_APP_PASSWORD": "app-password"})
    @patch("mailer.smtplib.SMTP")
    def test_verified_starttls_and_reviewed_pdf_attachment(self, smtp, config):
        smtp.return_value.send_message.return_value = {}
        send_report("Business report", b"%PDF-test")
        smtp.return_value.starttls.assert_called_once()
        context = smtp.return_value.starttls.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        message = smtp.return_value.send_message.call_args.args[0]
        self.assertEqual(message["To"], "owner@gmail.com")
        self.assertEqual(next(message.iter_attachments()).get_payload(decode=True), b"%PDF-test")

    @patch("mailer.read_config", return_value={"SMTP_USERNAME": "owner@gmail.com", "SMTP_APP_PASSWORD": "app-password"})
    @patch("mailer.smtplib.SMTP")
    def test_ambiguous_smtp_delivery_is_explicit(self, smtp, config):
        smtp.return_value.send_message.side_effect = smtplib.SMTPServerDisconnected("private server info")
        with self.assertRaises(DeliveryUncertain) as caught:
            send_report("Report", b"%PDF-test")
        self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
