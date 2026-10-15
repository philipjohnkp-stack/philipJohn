from __future__ import annotations

import hashlib
import hmac
import logging
import json
import secrets
import sqlite3
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_file, session
from flask.sessions import SecureCookieSessionInterface
from werkzeug.middleware.proxy_fix import ProxyFix

from analysis_reports import analyze, build_pdf, chart_svg
from mailer import DeliveryUncertain, email_ready, send_report
from privacy import protect_text
from sql_assistant import AssistantError, Settings, SQLAssistant, read_config
from storage import Store


LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("werkzeug").setLevel(logging.ERROR)


class SessionCookies(SecureCookieSessionInterface):
    def get_cookie_secure(self, app: Flask) -> bool:
        return request.is_secure


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(MAX_CONTENT_LENGTH=16384, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    if test_config:
        app.config.update(test_config)
    store = Store(Path(app.config.get("STORE_PATH", Path(app.instance_path) / "studio.sqlite3")))
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or store.secret()
    app.extensions["store"] = store
    app.session_interface = SessionCookies()
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

    def chat_id() -> str:
        if "chat_id" not in session:
            session["chat_id"] = uuid4().hex
            session["csrf"] = secrets.token_urlsafe(32)
        known = session.get("chat_ids", [])
        if session["chat_id"] not in known:
            session["chat_ids"] = (known + [session["chat_id"]])[-20:]
        return session["chat_id"]

    def owner() -> bool:
        password = read_config().get("OWNER_PASSWORD", "")
        if len(password) < 16:
            return False
        expected = hmac.new(app.secret_key.encode(), password.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(session.get("owner", ""), expected)

    def rate_limit(action: str, maximum: int, seconds: int = 60) -> None:
        if app.config.get("TESTING"):
            return
        address = request.remote_addr or ""
        if address in {"127.0.0.1", "::1"}:
            address = request.headers.get("CF-Connecting-IP", address)
        key = hmac.new(app.secret_key.encode(), address.encode(), hashlib.sha256).hexdigest()
        if not store.allow(action + key, maximum, seconds):
            LOGGER.warning("Request rate limit reached")
            abort(429, description="Too many requests. Please wait and try again.")

    def get_report(report_id: str) -> dict[str, Any]:
        report = store.report(report_id, chat_id())
        if report is None:
            abort(404, description="Report not found in this conversation.")
        return report

    @app.before_request
    def protect_requests():
        if not app.config.get("TESTING") and not store.allow("http-global", 180, 60):
            abort(429, description="The service is busy. Please try again shortly.")
        chat_id()
        if request.host.split(":")[0] not in {"localhost", "127.0.0.1", "[::1]"} and not request.is_secure:
            abort(400, description="Please use the HTTPS address.")
        if request.method == "POST":
            if not request.is_json:
                abort(415, description="A JSON request is required.")
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                abort(403, description="Refresh the page and try again.")

    @app.after_request
    def response_headers(response):
        ancestors = "'self'" if response.mimetype == "application/pdf" else "'none'"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            f"frame-src 'self'; frame-ancestors {ancestors}; base-uri 'none'; form-action 'self'"
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=86400"
        return response

    @app.errorhandler(AssistantError)
    def assistant_failure(error):
        LOGGER.warning("User request failed (%s)", type(error).__name__)
        return jsonify(error=str(error)), 422

    @app.errorhandler(sqlite3.Error)
    def storage_failure(error):
        LOGGER.error("Local storage failed (%s)", type(error).__name__)
        return jsonify(error="Local storage is unavailable. Please try again shortly."), 503

    for code in (400, 403, 404, 409, 413, 415, 429, 503):
        app.register_error_handler(code, lambda error: (jsonify(error=error.description), error.code))

    @app.get("/")
    def index():
        return render_template("index.html", csrf=session["csrf"], owner=owner())

    @app.get("/owner")
    def owner_page():
        return render_template("owner.html", csrf=session["csrf"])

    @app.post("/api/owner/login")
    def owner_login():
        rate_limit("login", 5)
        config = read_config()
        configured = config.get("OWNER_PASSWORD", "")
        body = request.get_json()
        if not isinstance(body, dict):
            abort(400, description="Invalid sign-in request.")
        supplied = body.get("password", "")
        if len(configured) < 16:
            abort(503, description="Owner access has not been configured.")
        if not isinstance(supplied, str) or not secrets.compare_digest(supplied.encode(), configured.encode()):
            abort(403, description="The sign-in was not accepted.")
        session["owner"] = hmac.new(app.secret_key.encode(), configured.encode(), hashlib.sha256).hexdigest()
        return jsonify(ok=True)

    @app.get("/api/state")
    def state():
        identity = chat_id()
        return jsonify(
            messages=store.messages(identity), owner=owner(), email_ready=owner() and email_ready(),
            recent_chats=store.recent_chats(session["chat_ids"]), chat_id=identity,
        )

    @app.post("/api/new")
    def new_chat():
        session["chat_id"] = uuid4().hex
        chat_id()
        return jsonify(ok=True)

    @app.post("/api/chat/switch")
    def switch_chat():
        body = request.get_json()
        identity = body.get("chat_id") if isinstance(body, dict) else None
        if not isinstance(identity, str) or identity not in session.get("chat_ids", []):
            abort(404, description="Conversation not found in this browser session.")
        session["chat_id"] = identity
        return jsonify(ok=True)

    @app.get("/api/catalog")
    def catalog():
        rate_limit("browse", 30)
        assistant = SQLAssistant(Settings.from_env())
        try:
            return jsonify(databases=assistant.discover_schema())
        finally:
            assistant.client.close()

    @app.get("/api/table")
    def table_data():
        rate_limit("browse", 30)
        database, table = request.args.get("database", ""), request.args.get("table", "")
        try:
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            abort(400, description="Invalid page offset.")
        if offset < 0:
            abort(400, description="Invalid page offset.")
        assistant = SQLAssistant(Settings.from_env())
        try:
            schema = assistant.discover_schema()
            if database not in schema or table not in schema[database]:
                abort(404, description="Table not found.")
            def quote(value: str) -> str:
                return "`" + value.replace("`", "``") + "`"
            qualified = quote(database) + "." + quote(table)
            order = [column["name"] for column in schema[database][table] if column["key"] == "PRI"]
            ordering = " ORDER BY " + ", ".join(quote(name) for name in order) if order else ""
            total = assistant.execute("SELECT COUNT(*) AS total FROM " + qualified, schema).rows[0][0]
            result = assistant.execute(f"SELECT * FROM {qualified}{ordering} LIMIT 50 OFFSET {offset}", schema)
            encoded = json.dumps(result.rows, default=str, allow_nan=False)
            if len(encoded) > 2_000_000:
                raise AssistantError("These rows are too large to preview. Ask for the specific columns you need.")
            return jsonify(
                columns=result.columns, rows=json.loads(encoded), total=total, offset=offset,
                next_offset=offset + len(result.rows), has_more=offset + len(result.rows) < total,
                structure=schema[database][table],
            )
        finally:
            assistant.client.close()

    @app.post("/api/chat")
    def chat():
        body = request.get_json()
        if not isinstance(body, dict):
            abort(400, description="Please enter a question.")
        question = body.get("question")
        mode = body.get("mode", "analysis")
        if not isinstance(question, str) or not question.strip() or len(question) > 4000 or not isinstance(mode, str) or mode not in {"chat", "analysis"}:
            abort(400, description="Enter a question of up to 4,000 characters.")
        question = protect_text(question.strip())
        rate_limit("analysis", 5)
        if not app.config.get("TESTING") and (
            not store.allow("all-analysis-minute", 30, 60) or not store.allow("all-analysis-day", 200, 86400)
        ):
            abort(429, description="The shared analysis allowance has been reached. Please try later.")
        identity = chat_id()
        if not store.claim_chat(identity):
            abort(409, description="Your previous question is still being processed.")
        assistant = None
        try:
            assistant = SQLAssistant(Settings.from_env())
            history = store.messages(identity)[-10:]
            schema = assistant.discover_schema()
            database = body.get("database")
            if database:
                if not isinstance(database, str) or database not in schema:
                    abort(400, description="Select an available database.")
                schema = {database: schema[database]}
            report_id = None
            if mode == "analysis":
                document = analyze(assistant, question, history, schema)
                if isinstance(document, str):
                    answer = document
                else:
                    report_id = uuid4().hex
                    pdf = build_pdf(document)
                    store.save_report(report_id, identity, document, pdf)
                    answer = document["summary"]
            else:
                answer = assistant.answer(question, history, schema)
            answer = protect_text(answer)
            store.save_turn(identity, question, answer, report_id)
            store.cleanup()
            return jsonify(question=question, message={"role": "assistant", "content": answer, "report_id": report_id})
        finally:
            if assistant is not None:
                assistant.client.close()
            store.release_chat(identity)

    @app.get("/api/reports/<report_id>")
    def report_data(report_id):
        report = get_report(report_id)
        return jsonify(document=report["document"], mail_status=report["mail_status"])

    @app.get("/api/reports/<report_id>/chart.svg")
    def report_chart(report_id):
        return app.response_class(chart_svg(get_report(report_id)["document"]), mimetype="image/svg+xml")

    @app.get("/api/reports/<report_id>/pdf")
    def report_pdf(report_id):
        return send_file(
            BytesIO(get_report(report_id)["pdf"]), mimetype="application/pdf",
            as_attachment=request.args.get("download") == "1", download_name="business-report.pdf",
        )

    @app.post("/api/reports/<report_id>/preview")
    def preview_report(report_id):
        get_report(report_id)
        store.review(report_id, chat_id())
        return jsonify(ok=True)

    @app.post("/api/reports/<report_id>/email")
    def email_report(report_id):
        if not owner():
            abort(403, description="Owner sign-in is required to send email.")
        rate_limit("email", 3, 3600)
        report = get_report(report_id)
        if not report["reviewed"]:
            abort(409, description="Preview the PDF before sending it.")
        if not email_ready():
            raise AssistantError("The owner must configure Gmail delivery first.")
        if not store.claim_email(report_id, chat_id()):
            abort(409, description="This report was already sent, is being sent, or has unconfirmed delivery.")
        try:
            send_report(report["document"]["title"], report["pdf"])
        except DeliveryUncertain:
            store.email_status(report_id, chat_id(), "unknown")
            raise
        except AssistantError:
            store.email_status(report_id, chat_id(), "failed")
            raise
        store.email_status(report_id, chat_id(), "sent")
        return jsonify(message="Gmail accepted the report. Check your inbox.")

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8502, debug=False, threaded=True)
