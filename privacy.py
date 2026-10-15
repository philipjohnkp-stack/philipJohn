from __future__ import annotations

import ipaddress
import re
from typing import Any, Mapping, Sequence

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope


MASK = "[private]"
SECRET_FIELD = re.compile(r"(^|_)(password|passwd|secret|token|api_key|credential)(_|$)", re.IGNORECASE)


def protect_text(text: str, known_values: Sequence[str] = ()) -> str:
    text = re.sub(
        r"\b((?:[A-Za-z0-9]+_)*(?:password|passwd|api[_ -]?key|access[_ -]?token|secret))"
        r"(\s*(?:[:=]|\bis\b)\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        lambda match: match.group(1) + match.group(2) + MASK, text, flags=re.IGNORECASE,
    )
    for value in sorted(set(known_values), key=len, reverse=True):
        if len(value) >= 2:
            text = text.replace(value, MASK)
    return text


def credential_column(name: str) -> bool:
    return bool(SECRET_FIELD.search(re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)))
SAFE_NAMES = {"product_name", "department_name", "category_name", "region_name", "country_name", "team_name", "database_name", "table_name", "column_name"}
IDENTIFIERS = re.compile(
    r"(^id$|(^|_)(email|e_mail|phone|mobile|telephone|fax|ssn|sin|passport|"
    r"address|street|postcode|postal_code|zip_code|dob|birth|birthday|"
    r"latitude|longitude|username|password|secret|token|api_key|"
    r"iban|bank_account|account_number|credit_card|card_number)(_|$)|"
    r"(^|_)(employee|customer|patient|person|student|member|contact|client|user)_id$|"
    r"(^|_)(first|last|full|given|family|middle|display|contact|customer|employee|"
    r"person|patient|student|user|owner|member|client)?_?name$|surname)"
)
TEXT_PATTERNS = (
    re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE),
    re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    re.compile(r"(?<!\w)(?:\+\d{1,3}[\s.-]*)?(?:\(\d{3}\)|\d{3})[\s.-]+\d{3}[\s.-]+\d{4}(?!\w)"),
    re.compile(r"(?<!\w)\+?\d{10,19}(?!\w)"),
    re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){11,30}\b"),
    re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b"),
    re.compile(r"\b\d{1,6}\s+(?:[A-Za-z0-9.'-]+\s+){1,5}(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Boulevard|Blvd)\b", re.IGNORECASE),
)
LABELED_PRIVATE = re.compile(
    r"\b(name|email|phone|password|api[_ -]?key|access[_ -]?token|"
    r"social security number|date of birth|passport number)"
    r"(\s*(?:[:=]|\bis\b)\s*)(\"[^\"]*\"|'[^']*'|[^\n,;]+)",
    re.IGNORECASE,
)


def private_column(name: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    if normalized in {
        "fname", "lname", "mname", "ename", "firstname", "lastname", "fullname",
        "employeeid", "customerid", "userid", "patientid", "memberid", "emailaddress",
        "phonenumber", "dateofbirth", "postalcode", "zipcode", "mrn", "medical_record_number",
        "employee_number", "employee_no", "customer_number", "patient_number",
        "national_id", "tax_id", "tax_number", "pan", "aadhaar", "aadhar",
        "accountnumber", "creditcardnumber", "bankaccountnumber",
        "customer", "employee", "patient", "person", "contact", "client", "member",
    }:
        return True
    return normalized not in SAFE_NAMES and bool(IDENTIFIERS.search(normalized))


def redact_text(text: str, known_values: Sequence[str] = ()) -> str:
    text = LABELED_PRIVATE.sub(lambda match: match.group(1) + match.group(2) + MASK, text)
    for pattern in TEXT_PATTERNS:
        text = pattern.sub(MASK, text)
    text = re.sub(
        r"\b(for|about|named|called|employee|customer|patient|contact|person)\s+"
        r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b",
        lambda match: match.group(1) + " " + MASK,
        text,
    )
    def hide_card(match: re.Match[str]) -> str:
        digits = [int(char) for char in match.group() if char.isdigit()]
        checksum = sum(value if index % 2 == 0 else (2 * value - 9 if value > 4 else 2 * value)
                       for index, value in enumerate(reversed(digits)))
        return MASK if 13 <= len(digits) <= 19 and checksum % 10 == 0 else match.group()
    text = re.sub(r"(?<!\w)(?:\d[ -]?){12,18}\d(?!\w)", hide_card, text)
    for value in sorted(set(known_values), key=len, reverse=True):
        if len(value.strip()) >= 2:
            text = re.sub(r"(?<!\w)" + re.escape(value) + r"(?!\w)", MASK, text, flags=re.IGNORECASE)

    def hide_ip(match: re.Match[str]) -> str:
        try:
            ipaddress.ip_address(match.group())
        except ValueError:
            return match.group()
        return MASK

    return re.sub(r"(?<!\w)(?:\d{1,3}\.){3}\d{1,3}(?!\w)", hide_ip, text)


def redact_history(history: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    return [{"role": entry["role"], "content": protect_text(entry["content"])} for entry in history]


def redact_rows(
    sql: str, columns: list[str], rows: list[list[Any]], *, credential_only: bool = False
) -> tuple[list[list[Any]], list[str], int]:
    classify = credential_column if credential_only else private_column
    clean_text = protect_text if credential_only else redact_text
    tree = sqlglot.parse_one(sql, read="mysql")
    tainted = {node.name.lower() for node in tree.find_all(exp.Column) if classify(node.name)}

    def private_expression(node: exp.Expression) -> bool:
        if isinstance(node, exp.Count):
            return False
        if isinstance(node, exp.Column):
            return classify(node.name) or node.name.lower() in tainted
        if isinstance(node, exp.JSONPathKey):
            return classify(str(node.this))
        return any(private_expression(child) for child in node.iter_expressions())

    for scope in traverse_scope(tree):
        for expression in scope.expression.selects:
            if private_expression(expression):
                tainted.add(expression.alias_or_name.lower())
    private_positions = {
        index for index, name in enumerate(columns)
        if classify(name) or name.lower() in tainted
    }
    expressions = tree.selects
    if len(expressions) == len(columns):
        for index, expression in enumerate(expressions):
            if private_expression(expression):
                private_positions.add(index)
            elif isinstance(expression.unalias(), exp.Count):
                private_positions.discard(index)
    if isinstance(tree, exp.SetOperation):
        branches = [node for node in tree.walk() if isinstance(node, exp.Select)]
        for branch in branches:
            for index, expression in enumerate(branch.selects):
                if private_expression(expression):
                    private_positions.add(index)

    known_values = [
        str(row[index]) for row in rows for index in private_positions
        if index < len(row) and row[index] is not None and 2 <= len(str(row[index])) <= 200
    ]
    redacted: list[list[Any]] = []
    count = 0
    for row in rows:
        cleaned = []
        for index, value in enumerate(row):
            if index in private_positions and value is not None:
                cleaned.append(MASK)
                count += 1
            elif isinstance(value, str):
                masked = clean_text(value, known_values)
                count += masked != value
                cleaned.append(masked)
            elif isinstance(value, bytes):
                cleaned.append(MASK)
                count += 1
            else:
                cleaned.append(value)
        redacted.append(cleaned)
    return redacted, [name for index, name in enumerate(columns) if index in private_positions], count
