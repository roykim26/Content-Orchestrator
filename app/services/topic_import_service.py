from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from sqlmodel import Session, select

from app.models.topic import Topic, TopicCreate
from app.services.topic_service import TopicService


class TopicImportService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.topic_service = TopicService(session)

    def import_from_path(
        self,
        input_path: Path,
        *,
        plan: bool = False,
        dry_run: bool = False,
        skip_existing: bool = False,
    ) -> dict[str, object]:
        rows = load_rows_from_path(input_path)
        return self.import_rows(
            rows,
            source_name=str(input_path.resolve()),
            plan=plan,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )

    def import_from_upload(
        self,
        *,
        filename: str,
        content: bytes,
        plan: bool = False,
        dry_run: bool = False,
        skip_existing: bool = False,
    ) -> dict[str, object]:
        rows = load_rows_from_bytes(filename, content)
        return self.import_rows(
            rows,
            source_name=filename,
            plan=plan,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )

    def import_from_text(
        self,
        *,
        filename_hint: str,
        content: str,
        plan: bool = False,
        dry_run: bool = False,
        skip_existing: bool = False,
    ) -> dict[str, object]:
        rows = load_rows_from_text(filename_hint, content)
        return self.import_rows(
            rows,
            source_name=filename_hint,
            plan=plan,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )

    def import_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        source_name: str,
        plan: bool = False,
        dry_run: bool = False,
        skip_existing: bool = False,
    ) -> dict[str, object]:
        summary: dict[str, object] = {
            "source_name": source_name,
            "row_count": len(rows),
            "created": 0,
            "planned": 0,
            "skipped": 0,
            "errors": 0,
            "results": [],
        }

        results: list[dict[str, object]] = []
        for index, row in enumerate(rows, start=1):
            try:
                payload = build_topic_payload(row)
                existing_topic = find_existing_topic(self.session, payload)
                if skip_existing and existing_topic:
                    summary["skipped"] = int(summary["skipped"]) + 1
                    result = {
                        "row": index,
                        "status": "skipped",
                        "topic_id": existing_topic.id,
                        "master_topic": payload.master_topic,
                        "target_keyword": payload.target_keyword,
                        "reason": "Topic already exists.",
                    }
                    if not dry_run:
                        changed = False
                        for field_name in (
                            "secondary_keyword",
                            "secondary_keywords",
                            "target_audience",
                            "article_type",
                            "content_focus",
                            "scenes",
                            "target_url",
                            "brand_name",
                            "site",
                            "language",
                            "extra_rules",
                            "note_account",
                            "feishu_record_id",
                            "feishu_topic_id",
                        ):
                            value = getattr(payload, field_name)
                            if value and getattr(existing_topic, field_name) != value:
                                setattr(existing_topic, field_name, value)
                                result[f"{field_name}_updated"] = True
                                changed = True
                        if changed:
                            self.session.add(existing_topic)
                            self.session.commit()
                    results.append(result)
                    continue

                if dry_run:
                    results.append(
                        {
                            "row": index,
                            "status": "preview",
                            "master_topic": payload.master_topic,
                            "target_keyword": payload.target_keyword,
                            "target_platforms": payload.target_platforms,
                        }
                    )
                    continue

                topic = self.topic_service.create_topic(payload)
                summary["created"] = int(summary["created"]) + 1
                result: dict[str, object] = {
                    "row": index,
                    "status": "created",
                    "topic_id": topic.id,
                    "master_topic": topic.master_topic,
                    "target_keyword": topic.target_keyword,
                    "target_platforms": topic.target_platforms,
                }

                if plan:
                    plan_result = self.topic_service.plan_topic(topic.id)
                    summary["planned"] = int(summary["planned"]) + 1
                    result["status"] = "planned"
                    result["task_count"] = plan_result["task_count"] if plan_result else 0

                results.append(result)
            except Exception as exc:  # noqa: BLE001
                self.session.rollback()
                summary["errors"] = int(summary["errors"]) + 1
                results.append(
                    {
                        "row": index,
                        "status": "error",
                        "reason": str(exc),
                    }
                )

        summary["results"] = results
        return summary


def load_rows_from_path(input_path: Path) -> list[dict[str, Any]]:
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        with input_path.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))
    if suffix == ".json":
        with input_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, list):
            raise ValueError("JSON input must be a list of topic objects.")
        return payload
    if suffix in {".xlsx", ".xlsm"}:
        with input_path.open("rb") as file:
            return load_rows_from_bytes(input_path.name, file.read())
    raise ValueError("Only .csv, .json, .xlsx, and .xlsm files are supported.")


def load_rows_from_text(filename_hint: str, content: str) -> list[dict[str, Any]]:
    suffix = Path(filename_hint).suffix.lower()
    if suffix == ".json":
        payload = json.loads(content)
        if not isinstance(payload, list):
            raise ValueError("JSON input must be a list of topic objects.")
        return payload
    if suffix in {".csv", ".txt", ""}:
        lines = content.splitlines()
        return list(csv.DictReader(lines))
    raise ValueError("Text import only supports CSV or JSON content.")


def load_rows_from_bytes(filename: str, content: bytes) -> list[dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        text = content.decode("utf-8-sig")
        return list(csv.DictReader(text.splitlines()))
    if suffix == ".json":
        payload = json.loads(content.decode("utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON input must be a list of topic objects.")
        return payload
    if suffix in {".xlsx", ".xlsm"}:
        return load_excel_rows(content)
    raise ValueError("Only .csv, .json, .xlsx, and .xlsm files are supported.")


def build_topic_payload(row: dict[str, Any]) -> TopicCreate:
    def optional(*names: str) -> str:
        for name in names:
            value = str(row.get(name, "") or "").strip()
            if value:
                return value
        return ""

    def required(*names: str) -> str:
        value = optional(*names)
        if not value:
            raise ValueError(f"Missing required field: {names[0]}")
        return value

    return TopicCreate(
        master_topic=required("master_topic", "topic"),
        topic_cluster=required("topic_cluster"),
        business_goal=required("business_goal"),
        target_keyword=required("target_keyword", "main_keyword"),
        secondary_keyword=optional("secondary_keyword") or None,
        secondary_keywords=normalize_list(row.get("secondary_keywords")),
        target_audience=optional("target_audience") or None,
        article_type=optional("article_type") or None,
        content_focus=optional("content_focus") or None,
        scenes=normalize_list(row.get("scenes")),
        target_url=optional("target_url") or None,
        brand_name=optional("brand_name") or None,
        site=optional("site") or None,
        language=optional("language") or None,
        extra_rules=optional("extra_rules") or None,
        priority=str(row.get("priority", "A") or "A").strip().upper(),
        target_platforms=normalize_platforms(row.get("target_platforms")),
        status=str(row.get("status", "ready") or "ready").strip().lower(),
        brief=str(row.get("brief", "")).strip() or None,
        note_account=normalize_note_account(row.get("note_account")),
        feishu_record_id=str(row.get("source_record_id", "")).strip() or None,
        feishu_topic_id=str(row.get("source_topic_id", "")).strip() or None,
    )


def normalize_platforms(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if value is None:
        return []

    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("target_platforms JSON value must be a list.")
        return [str(item).strip().lower() for item in parsed if str(item).strip()]
    return [item.strip().lower() for item in text.split(",") if item.strip()]


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []

    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    parts = re.split(r"[,，、/|;\n]+", text)
    return [part.strip() for part in parts if part.strip()]


def normalize_note_account(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def find_existing_topic(session: Session, payload: TopicCreate) -> Topic | None:
    statement = select(Topic).where(
        Topic.master_topic == payload.master_topic,
        Topic.target_keyword == payload.target_keyword,
    )
    return session.exec(statement).first()


def topic_exists(session: Session, payload: TopicCreate) -> bool:
    return find_existing_topic(session, payload) is not None


def load_excel_rows(content: bytes) -> list[dict[str, Any]]:
    rows = read_xlsx_rows(content)
    if not rows:
        return []

    headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
    result: list[dict[str, Any]] = []
    for values in rows[1:]:
        if values is None:
            continue
        if all(value is None or str(value).strip() == "" for value in values):
            continue
        row = {
            headers[index]: values[index]
            for index in range(min(len(headers), len(values)))
            if headers[index]
        }
        result.append(row)
    return result


def read_xlsx_rows(content: bytes) -> list[list[Any]]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared_strings = load_shared_strings(archive, ns)
        sheet_path = resolve_first_sheet_path(archive, ns)
        sheet_xml = ET.fromstring(archive.read(sheet_path))

        rows: list[list[Any]] = []
        for row_element in sheet_xml.findall(".//main:sheetData/main:row", ns):
            cell_map: dict[int, Any] = {}
            max_index = -1
            for cell in row_element.findall("main:c", ns):
                cell_ref = cell.attrib.get("r", "")
                column_index = column_letters_to_index("".join(char for char in cell_ref if char.isalpha()))
                max_index = max(max_index, column_index)
                cell_map[column_index] = parse_cell_value(cell, shared_strings, ns)
            if max_index < 0:
                rows.append([])
                continue
            rows.append([cell_map.get(index) for index in range(max_index + 1)])
        return rows


def load_shared_strings(archive: zipfile.ZipFile, ns: dict[str, str]) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    shared_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in shared_xml.findall("main:si", ns):
        text_parts = [node.text or "" for node in item.findall(".//main:t", ns)]
        values.append("".join(text_parts))
    return values


def resolve_first_sheet_path(archive: zipfile.ZipFile, ns: dict[str, str]) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    first_sheet = workbook.find("main:sheets/main:sheet", ns)
    if first_sheet is None:
        raise ValueError("Workbook does not contain any sheets.")
    relationship_id = first_sheet.attrib.get(f"{{{ns['rel']}}}id")
    if not relationship_id:
        raise ValueError("First sheet is missing relationship id.")

    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for relation in relationships.findall("pkgrel:Relationship", ns):
        if relation.attrib.get("Id") == relationship_id:
            target = relation.attrib["Target"]
            normalized_target = target.lstrip("/")
            if normalized_target.startswith("xl/"):
                return normalized_target
            return f"xl/{normalized_target}"
    raise ValueError("Could not resolve first worksheet path.")


def parse_cell_value(cell: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        text_parts = [node.text or "" for node in cell.findall(".//main:t", ns)]
        return "".join(text_parts)

    value_element = cell.find("main:v", ns)
    if value_element is None or value_element.text is None:
        return None
    raw_value = value_element.text

    if cell_type == "s":
        index = int(raw_value)
        return shared_strings[index] if 0 <= index < len(shared_strings) else raw_value
    if cell_type == "b":
        return raw_value == "1"
    if cell_type == "str":
        return raw_value
    if cell_type in {None, "n"}:
        return normalize_number(raw_value)
    return raw_value


def normalize_number(value: str) -> Any:
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer():
        return int(number)
    return number


def column_letters_to_index(column_letters: str) -> int:
    if not column_letters:
        return -1
    result = 0
    for char in column_letters.upper():
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result - 1
