import errno
import json
import os
import socket
import ssl
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymysql
import sqlglot

from sql_assistant import (
    MAX_CELL_CHARS,
    MAX_RESULT_CHARS,
    MAX_ROWS,
    AssistantError,
    QueryRejected,
    QueryResult,
    Settings,
    SQLAssistant,
    plain_answer,
    validate_query,
)


SCHEMA = {
    "sales": {
        "orders": [{"name": "customer_id", "type": "int", "key": ""}],
        "customers": [{"name": "id", "type": "int", "key": "PRI"}],
    },
    "archive": {"orders": [{"name": "customer_id", "type": "int", "key": ""}]},
}
SETTINGS = Settings("https://example.openai.azure.com", "test", "2024-10-21", "test", "localhost", 3306, "test", "test")


class SettingsTests(unittest.TestCase):
    def test_env_file_updates_override_stale_environment_without_mutating_it(self):
        environment = {
            "AZURE_OPENAI_ENDPOINT": SETTINGS.endpoint,
            "AZURE_OPENAI_API_KEY": SETTINGS.api_key,
            "AZURE_OPENAI_API_VERSION": SETTINGS.api_version,
            "AZURE_OPENAI_DEPLOYMENT_MINI": SETTINGS.deployment,
            "DB_HOST": SETTINGS.host,
            "DB_PORT": str(SETTINGS.port),
            "DB_USER": SETTINGS.user,
            "DB_PASSWORD": "old-password",
        }
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            with patch.dict(os.environ, environment, clear=True), patch("sql_assistant.Path") as path:
                path.return_value.with_name.return_value = env_file
                env_file.write_text(
                    "DB_PASSWORD=updated-password\nDB_REQUIRE_TLS=true\nDB_SSL_CA=/tmp/mysql-ca.pem\n"
                )
                updated = Settings.from_env()
                self.assertEqual(updated.password, "updated-password")
                self.assertTrue(updated.require_tls)
                self.assertEqual(updated.ssl_ca, "/tmp/mysql-ca.pem")
                env_file.write_text("DB_PASSWORD=newer-password\nDB_UNIX_SOCKET=/tmp/test-mysql.sock\n")
                updated = Settings.from_env()
                self.assertEqual(updated.password, "newer-password")
                self.assertEqual(updated.unix_socket, "/tmp/test-mysql.sock")
                self.assertFalse(updated.require_tls)
                self.assertEqual(os.environ["DB_PASSWORD"], "old-password")
                env_file.write_text("DB_PASSWORD=\n")
                with self.assertRaises(AssistantError):
                    Settings.from_env()

    def test_invalid_database_tls_setting_is_rejected(self):
        with patch("sql_assistant.read_config", return_value={
            "AZURE_OPENAI_ENDPOINT": SETTINGS.endpoint,
            "AZURE_OPENAI_API_KEY": SETTINGS.api_key,
            "AZURE_OPENAI_API_VERSION": SETTINGS.api_version,
            "AZURE_OPENAI_DEPLOYMENT_MINI": SETTINGS.deployment,
            "DB_HOST": SETTINGS.host,
            "DB_PORT": str(SETTINGS.port),
            "DB_USER": SETTINGS.user,
            "DB_PASSWORD": SETTINGS.password,
            "DB_REQUIRE_TLS": "sometimes",
        }):
            with self.assertRaises(AssistantError):
                Settings.from_env()

    def test_settings_representation_does_not_include_secrets(self):
        settings = replace(SETTINGS, api_key="private-api-key", password="private-db-password")
        self.assertNotIn("private-api-key", repr(settings))
        self.assertNotIn("private-db-password", repr(settings))


class QueryValidationTests(unittest.TestCase):
    def test_cross_database_join(self):
        query = validate_query(
            "SELECT COUNT(*) FROM sales.orders a JOIN archive.orders b "
            "ON a.customer_id = b.customer_id",
            SCHEMA,
        )
        self.assertIn("sales.orders", query)
        self.assertIn("archive.orders", query)
        self.assertTrue(query.endswith(f"LIMIT {MAX_ROWS + 1}"))

    def test_cte_subquery_and_union(self):
        for query in (
            "WITH recent AS (SELECT customer_id FROM sales.orders) SELECT COUNT(*) FROM recent",
            "SELECT * FROM (SELECT customer_id FROM sales.orders) AS recent",
            "SELECT customer_id FROM sales.orders UNION ALL SELECT customer_id FROM archive.orders",
            "WITH orders AS (SELECT customer_id FROM sales.orders) SELECT * FROM orders",
            "SELECT 'sales' AS database_name UNION ALL SELECT 'archive'",
        ):
            with self.subTest(query=query):
                self.assertIn("LIMIT", validate_query(query, SCHEMA))

    def test_common_analytics_functions(self):
        for expression in (
            "COUNT(*)",
            "SUM(CASE WHEN customer_id > 1 THEN 1 ELSE 0 END)",
            "COALESCE(customer_id, 0)",
            "ROW_NUMBER() OVER (ORDER BY customer_id)",
            "DATE_FORMAT(CURRENT_DATE(), '%Y-%m')",
            "DATE_SUB(CURDATE(), INTERVAL 30 DAY)",
            "ROUND(AVG(customer_id), 2)",
        ):
            with self.subTest(expression=expression):
                validate_query(f"SELECT {expression} FROM sales.orders", SCHEMA)

    def test_explicit_small_limit_preserved_and_large_limit_capped(self):
        for requested, expected in ((0, 0), (5, 5), (200, 200), (9999, 201)):
            with self.subTest(requested=requested):
                query = validate_query(f"SELECT * FROM sales.orders LIMIT {requested}", SCHEMA)
                tree = sqlglot.parse_one(query, read="mysql")
                self.assertEqual(int(tree.args["limit"].expression.this), expected)

    def test_writes_system_access_functions_and_multiple_statements_rejected(self):
        rejected = (
            "DELETE FROM sales.orders",
            "UPDATE sales.orders SET customer_id = 1",
            "DROP DATABASE sales",
            "INSERT INTO sales.orders SELECT * FROM archive.orders",
            "SELECT 1; DELETE FROM sales.orders",
            "SELECT * FROM mysql.user",
            "SELECT * FROM information_schema.tables",
            "SELECT * FROM orders",
            "SELECT * FROM missing.orders",
            "SELECT * FROM sales.missing",
            "SELECT * FROM sales.orders FOR UPDATE",
            "SELECT * FROM sales.orders INTO OUTFILE '/tmp/export'",
            "SELECT * FROM sales.orders INTO DUMPFILE '/tmp/export'",
            "SELECT SLEEP(10)",
            "SELECT BENCHMARK(10000000, 1)",
            "SELECT LOAD_FILE('/etc/passwd')",
            "SELECT GET_LOCK('example', 10)",
            "SELECT my_custom_function(1)",
            "SELECT sales.my_custom_function(1)",
            "SELECT @@version",
            "SELECT @secret",
            "SELECT @x := 1",
            "SELECT /*+ MAX_EXECUTION_TIME(0) */ * FROM sales.orders",
            "WITH RECURSIVE n AS (SELECT 1 UNION ALL SELECT 1 FROM n) SELECT * FROM n",
            "SELECT * FROM sales.orders LIMIT @n",
            "WITH hidden AS (SELECT * FROM mysql.user) SELECT * FROM hidden",
            "SELECT * FROM sales.orders WHERE customer_id IN (SELECT User FROM mysql.user)",
            "",
        )
        for query in rejected:
            with self.subTest(query=query):
                with self.assertRaises(QueryRejected):
                    validate_query(query, SCHEMA)

    def test_executable_comments_do_not_reach_mysql(self):
        query = validate_query("SELECT customer_id FROM sales.orders /*!50000 FOR UPDATE */", SCHEMA)
        self.assertNotIn("/*", query)
        self.assertNotIn("FOR UPDATE", query)


class AnswerTests(unittest.TestCase):
    def test_plain_answer_and_sql_leak_filter(self):
        self.assertEqual(plain_answer("There are 12 customers."), "There are 12 customers.")
        for value in (
            None,
            "",
            "SELECT * FROM sales.orders",
            "SELECT 1",
            "Here is the query: SELECT COUNT(*)",
            "```sql\nSELECT 1\n```",
        ):
            with self.subTest(value=value):
                with self.assertRaises(AssistantError):
                    plain_answer(value)

    def test_result_preserves_numbers_dates_null_and_marks_truncation(self):
        payload = json.loads(
            QueryResult(["a", "b", "c", "d"], [[Decimal("1.20"), date(2025, 1, 1), None, 12]], False).for_model()
        )
        self.assertEqual(payload["rows"], [["1.20", "2025-01-01", None, 12]])
        self.assertFalse(payload["truncated"])
        payload = json.loads(QueryResult(["a"], [["x" * (MAX_CELL_CHARS + 1)]], False).for_model())
        self.assertEqual(len(payload["rows"][0][0]), MAX_CELL_CHARS)
        self.assertTrue(payload["truncated"])
        payload = json.loads(QueryResult(["a"], [["x" * 1000]] * MAX_ROWS, False).for_model())
        self.assertLessEqual(len(json.dumps(payload["rows"])), MAX_RESULT_CHARS)
        self.assertTrue(payload["truncated"])

    def test_binary_and_row_truncation_are_explicit(self):
        payload = json.loads(QueryResult(["blob"], [[b"private"]], False).for_model())
        self.assertEqual(payload["rows"], [["[binary value omitted]"]])
        self.assertTrue(payload["truncated"])
        self.assertTrue(json.loads(QueryResult(["a"], [[1]], True).for_model())["truncated"])

    @patch("sql_assistant.AzureOpenAI")
    def test_question_executes_backend_and_only_returns_answer(self, client):
        assistant = SQLAssistant(SETTINGS)
        assistant.complete = MagicMock(side_effect=[
            {"sql": "SELECT COUNT(*) FROM sales.orders", "message": ""},
            {"answer": "There are 12 orders."},
        ])
        assistant.execute = MagicMock(return_value=QueryResult(["count"], [[12]], False))
        history = [{"role": "user", "content": "Use the sales database."}]
        answer = assistant.answer("How many orders?", history, SCHEMA)
        self.assertEqual(answer, "There are 12 orders.")
        assistant.execute.assert_called_once_with("SELECT COUNT(*) FROM sales.orders", SCHEMA)
        planning_messages = assistant.complete.call_args_list[0].args[0]
        self.assertIn(history[0], planning_messages)
        summary_input = assistant.complete.call_args_list[1].args[0][-1]["content"]
        self.assertNotIn("SELECT", summary_input)

    @patch("sql_assistant.AzureOpenAI")
    def test_clarification_does_not_execute(self, client):
        assistant = SQLAssistant(SETTINGS)
        assistant.complete = MagicMock(return_value={"sql": None, "message": "Which database do you mean?"})
        assistant.execute = MagicMock()
        self.assertEqual(assistant.answer("Count the orders", [], SCHEMA), "Which database do you mean?")
        assistant.execute.assert_not_called()

    @patch("sql_assistant.AzureOpenAI")
    def test_invalid_query_is_repaired_once(self, client):
        assistant = SQLAssistant(SETTINGS)
        assistant.complete = MagicMock(side_effect=[
            {"sql": "SELECT * FROM orders"},
            {"sql": "SELECT * FROM sales.orders"},
            {"answer": "No matching records were found."},
        ])
        assistant.execute = MagicMock(side_effect=[
            QueryRejected("Use qualified names"),
            QueryResult(["id"], [], False),
        ])
        self.assertEqual(assistant.answer("Find orders", [], SCHEMA), "No matching records were found.")
        self.assertEqual(assistant.execute.call_count, 2)

    @patch("sql_assistant.AzureOpenAI")
    def test_database_errors_are_not_exposed(self, client):
        assistant = SQLAssistant(SETTINGS)
        assistant.complete = MagicMock(return_value={"sql": "SELECT * FROM sales.orders"})
        assistant.execute = MagicMock(side_effect=pymysql.OperationalError(1045, "secret hostname/password"))
        with self.assertRaises(AssistantError) as caught:
            assistant.answer("Find orders", [], SCHEMA)
        self.assertNotIn("secret", str(caught.exception))
        self.assertNotIn("secret hostname/password", str(assistant.complete.call_args_list))
        self.assertIn("rejected the login", str(caught.exception))

    @patch("sql_assistant.AzureOpenAI")
    def test_discovery_reports_safe_actionable_database_errors(self, client):
        cases = (
            (1045, None, "rejected the login"),
            (1142, None, "denied access"),
            (2003, PermissionError(errno.EPERM, "secret network details"), "access to MySQL was blocked"),
            (2003, FileNotFoundError(errno.ENOENT, "secret socket path"), "socket was not found"),
            (2003, ConnectionRefusedError(errno.ECONNREFUSED, "secret host"), "not accepting connections"),
            (2003, TimeoutError("secret host"), "timed out"),
            (2003, socket.gaierror(socket.EAI_NONAME, "secret host"), "hostname could not be resolved"),
            (2003, ssl.SSLCertVerificationError(1, "secret certificate details"), "certificate could not be verified"),
            (2003, ssl.SSLError(1, "secret TLS details"), "secure MySQL connection failed"),
            (2003, None, "couldn't reach MySQL"),
            (2013, None, "connection was interrupted"),
            (2026, None, "secure MySQL connection failed"),
            (9999, None, "could not complete the request"),
        )
        for code, cause, expected in cases:
            with self.subTest(code=code, expected=expected):
                assistant = SQLAssistant(SETTINGS)
                error = pymysql.OperationalError(code, "secret host/user/password")
                error.__cause__ = cause
                assistant.connect = MagicMock(side_effect=error)
                with self.assertLogs("sql_assistant", level="ERROR") as logs:
                    with self.assertRaises(AssistantError) as caught:
                        assistant.discover_schema()
                self.assertIn(expected, str(caught.exception))
                self.assertIn(f"code={code}", logs.output[0])
                self.assertNotIn("secret", str(caught.exception))
                self.assertNotIn("secret", "\n".join(logs.output))
                self.assertIs(caught.exception.__cause__, error)

    @patch("sql_assistant.AzureOpenAI")
    def test_discovery_preserves_implicit_network_exception_diagnostics(self, client):
        assistant = SQLAssistant(SETTINGS)
        error = pymysql.OperationalError(2003, "secret details")
        error.__context__ = PermissionError(errno.EPERM, "secret details")
        assistant.connect = MagicMock(side_effect=error)
        with self.assertLogs("sql_assistant", level="ERROR") as logs:
            with self.assertRaisesRegex(AssistantError, "access to MySQL was blocked"):
                assistant.discover_schema()
        self.assertIn(f"network_errno={errno.EPERM}", logs.output[0])
        self.assertNotIn("secret", "\n".join(logs.output))

    @patch("sql_assistant.AzureOpenAI")
    @patch("sql_assistant.pymysql.connect")
    def test_connect_uses_configured_socket_and_preserves_tcp_default(self, connect, client):
        for socket_path in ("", "/tmp/test-mysql.sock"):
            with self.subTest(socket_path=socket_path):
                assistant = SQLAssistant(replace(SETTINGS, unix_socket=socket_path))
                assistant.connect()
                self.assertEqual(connect.call_args.kwargs["unix_socket"], socket_path or None)
                self.assertIsNone(connect.call_args.kwargs["ssl"])
                self.assertEqual(connect.call_args.kwargs["user"], SETTINGS.user)
                self.assertEqual(connect.call_args.kwargs["password"], SETTINGS.password)
                self.assertEqual(connect.call_args.kwargs["host"], SETTINGS.host)
                self.assertEqual(connect.call_args.kwargs["port"], SETTINGS.port)

    @patch("sql_assistant.AzureOpenAI")
    @patch("sql_assistant.pymysql.connect")
    @patch("sql_assistant.ssl.create_default_context")
    def test_connect_enforces_verified_tls_when_configured(self, create_context, connect, client):
        context = object()
        create_context.return_value = context
        assistant = SQLAssistant(replace(SETTINGS, require_tls=True, ssl_ca="/tmp/mysql-ca.pem"))
        assistant.connect()
        create_context.assert_called_once_with(cafile="/tmp/mysql-ca.pem")
        self.assertIs(connect.call_args.kwargs["ssl"], context)

    @patch("sql_assistant.AzureOpenAI")
    @patch("sql_assistant.pymysql.connect")
    def test_unavailable_socket_does_not_silently_fall_back_to_tcp(self, connect, client):
        error = pymysql.OperationalError(2003, "secret connection details")
        error.__cause__ = FileNotFoundError(errno.ENOENT, "secret socket path")
        connect.side_effect = error
        assistant = SQLAssistant(replace(SETTINGS, unix_socket="/tmp/missing-mysql.sock"))
        with self.assertLogs("sql_assistant", level="ERROR"):
            with self.assertRaisesRegex(AssistantError, "socket was not found"):
                assistant.discover_schema()
        connect.assert_called_once()

    @patch("sql_assistant.AzureOpenAI")
    def test_execute_starts_read_only_transaction_and_rolls_back(self, client):
        assistant = SQLAssistant(SETTINGS)
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [("count",)]
        cursor.fetchmany.return_value = [(1,)] * (MAX_ROWS + 1)
        assistant.connect = MagicMock(return_value=connection)
        result = assistant.execute("SELECT COUNT(*) FROM sales.orders", SCHEMA)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual(statements[0], "SET SESSION MAX_EXECUTION_TIME = 10000")
        self.assertEqual(statements[1], "START TRANSACTION READ ONLY")
        self.assertEqual(len(result.rows), MAX_ROWS)
        self.assertTrue(result.truncated)
        connection.rollback.assert_called_once()

    @patch("sql_assistant.AzureOpenAI")
    def test_failed_execution_also_rolls_back(self, client):
        assistant = SQLAssistant(SETTINGS)
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = [None, None, pymysql.OperationalError("failure")]
        assistant.connect = MagicMock(return_value=connection)
        with self.assertRaises(pymysql.OperationalError):
            assistant.execute("SELECT * FROM sales.orders", SCHEMA)
        connection.rollback.assert_called_once()

    @patch("sql_assistant.AzureOpenAI")
    def test_discovers_every_accessible_database(self, client):
        assistant = SQLAssistant(SETTINGS)
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [
                ("sales", "orders", "customer_id", "int", ""),
                ("sales", "customers", "id", "int", "PRI"),
                ("archive", "orders", "customer_id", "int", ""),
            ],
            [("sales", "orders", "customer_id", "sales", "customers", "id")],
        ]
        assistant.connect = MagicMock(return_value=connection)
        schema = assistant.discover_schema()
        self.assertEqual(set(schema), {"sales", "archive"})
        self.assertEqual(schema["sales"]["orders"][0]["references"], "sales.customers.id")


if __name__ == "__main__":
    unittest.main()
