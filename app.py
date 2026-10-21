from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import json
import os
import secrets
import sqlite3
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, abort, g, jsonify, render_template, request, send_file, session
from flask.sessions import SecureCookieSessionInterface
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import HTTPException

from analysis_reports import analyze, answer_document, build_pdf, chart_svg, hide_database_identifiers, pdf_document
from app_logging import LOG_CONTEXT, configure_logging, configured_secrets
from mailer import DeliveryUncertain, email_ready, send_report, validate_recipient
from ocr import extract_text
from privacy import protect_text
from sql_assistant import AssistantError, Settings, SQLAssistant, read_config
from storage import ConversationDeletedError, Store

LOGGER = logging.getLogger(__name__)
LOGGER = logging.getLogger(__name__)
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
    runtime_config = read_config()
    debug_setting = app.config.get("DEBUG_LOGGING", runtime_config.get("APP_DEBUG", "false"))
    debug_logging = debug_setting is True or str(debug_setting).strip().lower() in {"1", "true", "yes", "on"}
    log_directory = Path(app.config.get("LOG_DIR") or Path(app.root_path) / "logs")
    configure_logging(log_directory, debug=debug_logging, secrets=configured_secrets(runtime_config))
    LOGGER.info(
        "Application logging initialized",
        extra={"action": "application.start", "status": "ready"},
    )
    store_path = app.config.get("STORE_PATH") or os.environ.get("STORE_PATH") or Path(app.instance_path) / "studio.sqlite3"
    store = Store(Path(store_path))
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

    def log_event(
        action: str,
        status: str,
        *,
        level: int = logging.INFO,
        **details: object,
    ) -> None:
        fields = " ".join(f"{key}={value}" for key, value in details.items())
        LOGGER.log(
            level,
            fields or "-",
            extra={"action": action, "status": status},
        )

    def set_action(action: str, **details: object) -> None:
        g.log_action = action
        g.log_details = details
        LOG_CONTEXT.set({**LOG_CONTEXT.get(), "action": action, "status": "started"})

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
        identity = chat_id()
        session_log_id = hmac.new(
            app.secret_key.encode(), identity.encode(), hashlib.sha256
        ).hexdigest()[:16]
        context_token = LOG_CONTEXT.set({
            "user": "owner" if owner() else "anonymous",
            "session_id": session_log_id,
            "action": "http.request",
            "status": "received",
        })
        g.log_context_token = context_token
        if debug_logging:
            LOGGER.debug(
                "method=%s path=%s",
                request.method,
                request.path,
                extra={"action": "http.request", "status": "received"},
            )
        if not app.config.get("TESTING") and not store.allow("http-global", 180, 60):
            abort(429, description="The service is busy. Please try again shortly.")
        if request.host.split(":")[0] not in {"localhost", "127.0.0.1", "[::1]"} and not request.is_secure:
            abort(400, description="Please use the HTTPS address.")
        if request.path == "/api/ocr":
            request.max_content_length = 3 * 1024 * 1024
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
        action = getattr(g, "log_action", None)
        if action:
            status = "success" if response.status_code < 400 else "failed"
            log_event(
                action,
                status,
                level=logging.INFO if status == "success" else logging.WARNING,
                http_status=response.status_code,
                **getattr(g, "log_details", {}),
            )
        elif response.status_code >= 400:
            log_event(
                "http.error",
                "failed",
                level=logging.WARNING,
                http_status=response.status_code,
            )
        return response

    @app.teardown_request
    def clear_log_context(error):
        token = getattr(g, "log_context_token", None)
        if token is not None:
            LOG_CONTEXT.reset(token)

    @app.errorhandler(AssistantError)
    def assistant_failure(error):
        LOGGER.warning(
            "error_type=%s detail=%s",
            type(error).__name__,
            str(error),
            extra={"action": "request.error", "status": "failed"},
            exc_info=(type(error), error, error.__traceback__),
        )
        return jsonify(error=str(error)), 422

    @app.errorhandler(sqlite3.Error)
    def storage_failure(error):
        LOGGER.error(
            "error_type=%s detail=%s",
            type(error).__name__,
            str(error),
            extra={"action": "storage.error", "status": "failed"},
            exc_info=(type(error), error, error.__traceback__),
        )
        return jsonify(error="Local storage is unavailable. Please try again shortly."), 503

    @app.errorhandler(ConversationDeletedError)
    def conversation_deleted(error):
        LOGGER.warning("A request finished after its conversation was deleted")
        return jsonify(error="This conversation was deleted. Refresh the page to start a new one."), 409

    @app.errorhandler(Exception)
    def unexpected_failure(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        LOGGER.error(
            "error_type=%s",
            type(error).__name__,
            extra={"action": "application.error", "status": "failed"},
            exc_info=(type(error), error, error.__traceback__),
        )
        return jsonify(error="An unexpected error occurred. Please try again."), 500

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
            messages=[
                {key: value for key, value in message.items() if key != "context"}
                for message in store.messages(identity)
            ],
            owner=owner(), email_ready=email_ready(),
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

    @app.post("/api/history/clear")
    def clear_history():
        set_action("history.delete")
        body = request.get_json()
        if not isinstance(body, dict) or body.get("confirm") is not True:
            abort(400, description="Confirm that you want to delete this session's history.")
        rate_limit("history-delete", 5)
        if not store.delete_history(session["chat_ids"]):
            abort(409, description="Wait for ongoing answers or email sends to finish, then delete history.")
        session["chat_ids"] = []
        session["chat_id"] = uuid4().hex
        chat_id()
        return jsonify(ok=True)

    @app.post("/api/ocr")
    def ocr():
        body = request.get_json()
        image = body.get("image") if isinstance(body, dict) else None
        prefix = "data:image/png;base64,"
        if not isinstance(image, str) or not image.startswith(prefix):
            abort(400, description="Paste a PNG snip.")
        rate_limit("ocr", 10)
        try:
            data = base64.b64decode(image[len(prefix):], validate=True)
        except ValueError:
            abort(400, description="The snip could not be read.")
        text = extract_text(data)
        return jsonify(text=text[:3000])

    @app.post("/api/chat")
    def chat():
        body = request.get_json()
        if not isinstance(body, dict):
            abort(400, description="Please enter a question.")
        question = body.get("question")
        mode = body.get("mode", "chat")
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
        set_action("report.generate")
        assistant = None
        try:
            assistant = SQLAssistant(Settings.from_env())
            history = [
                {**message, "content": message.get("context", message["content"])}
                for message in store.messages(identity)[-10:]
            ]
            answer = assistant.general_answer(question, history)
            schema = {}
            if answer is None:
                schema = assistant.discover_schema()
                document = analyze(assistant, question, history, schema)
                if isinstance(document, str):
                    answer = hide_database_identifiers(document, schema)
                    document = answer_document(
                        hide_database_identifiers(question, schema), answer
                    )
                else:
                    document = hide_database_identifiers(document, schema)
                    answer = document["summary"]
            else:
                document = answer_document(question, answer)
            answer = protect_text(answer)
            display_question = hide_database_identifiers(question, schema)
            document["display_mode"] = mode
            report_id = uuid4().hex
            g.log_details["report_id"] = report_id
            store.save_report(report_id, identity, document, b"")
            store.save_turn(identity, display_question, answer, report_id, context_question=question)
            store.cleanup()
            return jsonify(question=display_question, message={"role": "assistant", "content": answer, "report_id": report_id})
        finally:
            if assistant is not None:
                assistant.client.close()
            store.release_chat(identity)

    @app.get("/api/reports/<report_id>")
    def report_data(report_id):
        report = get_report(report_id)
        document = {
            key: value for key, value in report["document"].items()
            if key not in {"data", "profile"}
        }
        return jsonify(document=document, mail_status=report["mail_status"])

    @app.get("/api/reports/<report_id>/chart.svg")
    def report_chart(report_id):
        set_action("chart.export", report_id=report_id)
        document = pdf_document(get_report(report_id)["document"], request.args.get("chart"))
        return app.response_class(chart_svg(document), mimetype="image/svg+xml")

    @app.get("/api/reports/<report_id>/pdf")
    def report_pdf(report_id):
        set_action("pdf.export", report_id=report_id, download=request.args.get("download") == "1")
        report = get_report(report_id)
        chart_kind = request.args.get("chart")
        document = pdf_document(report["document"], chart_kind)
        pdf = build_pdf(document)
        return send_file(
            BytesIO(pdf), mimetype="application/pdf",
            as_attachment=request.args.get("download") == "1", download_name="Sage Analyse Report.pdf",
        )

    @app.post("/api/reports/<report_id>/preview")
    def preview_report(report_id):
        set_action("report.preview", report_id=report_id)
        get_report(report_id)
        store.review(report_id, chat_id())
        return jsonify(ok=True)

    @app.post("/api/reports/<report_id>/email")
    def email_report(report_id):
        set_action("email.request", report_id=report_id)
        body = request.get_json()
        if not isinstance(body, dict):
            abort(400, description="A recipient and PDF options are required.")
        recipient = validate_recipient(body.get("recipient"))
        chart_kind = body.get("chart")
        if chart_kind is not None and not isinstance(chart_kind, str):
            abort(400, description="Select a valid chart option.")
        report = get_report(report_id)
        if not report["reviewed"]:
            abort(409, description="Preview the PDF before sending it.")
        if report["mail_status"] in {"sent", "sending", "unknown"}:
            abort(409, description="This report was already sent, is being sent, or has unconfirmed delivery.")
        if not email_ready():
            raise AssistantError("Email delivery is unavailable. Please contact the site owner.")
        document = pdf_document(report["document"], chart_kind)
        rate_limit("email", 3, 3600)
        session_key = hmac.new(app.secret_key.encode(), session["csrf"].encode(), hashlib.sha256).hexdigest()
        recipient_key = hmac.new(app.secret_key.encode(), recipient.lower().encode(), hashlib.sha256).hexdigest()
        for key, maximum, seconds in (
            ("email-session-" + session_key, 3, 3600),
            ("email-recipient-" + recipient_key, 3, 86400),
            ("email-global-hour", 20, 3600),
            ("email-global-day", 50, 86400),
        ):
            if not store.allow(key, maximum, seconds):
                LOGGER.warning("Email sending limit reached")
                abort(429, description="The email sending limit has been reached. Please try again later or download the PDF.")
        pdf = build_pdf(document)
        if not store.claim_email(report_id, chat_id()):
            abort(409, description="This report was already sent, is being sent, or has unconfirmed delivery.")
        try:
            send_report(document["title"], pdf, recipient)
        except DeliveryUncertain as error:
            store.email_status(report_id, chat_id(), "unknown")
            log_event(
                "email.delivery", "unknown", level=logging.ERROR,
                report_id=report_id, error_type=type(error).__name__, detail=str(error),
            )
            raise
        except AssistantError as error:
            store.email_status(report_id, chat_id(), "failed")
            log_event(
                "email.delivery", "failed", level=logging.ERROR,
                report_id=report_id, error_type=type(error).__name__, detail=str(error),
            )
            raise
        store.email_status(report_id, chat_id(), "sent")
        log_event("email.delivery", "success", report_id=report_id, detail="smtp_accepted")
        return jsonify(message="Gmail accepted the PDF for delivery. Check the recipient's inbox and spam folder.")

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8502, debug=False, threaded=True)
