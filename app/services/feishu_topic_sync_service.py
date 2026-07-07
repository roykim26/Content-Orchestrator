from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import time
from typing import Any

import httpx
from sqlmodel import Session

from app.core.config import settings
from app.models.artifact import ArtifactPublishResult, ContentArtifact
from app.models.topic import Topic
from app.services.topic_import_service import TopicImportService


class FeishuTopicSyncError(RuntimeError):
    pass


class FeishuTopicSyncService:
    NOTE_WRITEBACK_FIELDS: dict[str, int] = {
        "note_account": 1,
        "note_status": 1,
        "note_url": 1,
        "note_published_at": 1,
        "note_artifact_id": 1,
        "note_error_message": 1,
    }
    AMEBA_WRITEBACK_FIELDS: dict[str, int] = {
        "ameba_status": 1,
        "ameba_draft_url": 1,
        "ameba_post_url": 1,
        "ameba_published_at": 1,
        "ameba_artifact_id": 1,
        "ameba_error_message": 1,
    }

    def __init__(self, session: Session) -> None:
        self.session = session
        self.import_service = TopicImportService(session)
        self._tenant_access_token = ""
        self._tenant_access_token_expires_at = 0.0
        self._field_meta_cache: dict[str, dict[str, Any]] = {}

    def sync(
        self,
        *,
        plan: bool = False,
        dry_run: bool = False,
        skip_existing: bool = True,
        status: str | None = "ready",
        limit: int | None = None,
    ) -> dict[str, object]:
        ensured_fields: list[str] = []
        field_setup_error = ""
        try:
            ensured_fields = self.ensure_note_writeback_fields() + self.ensure_ameba_writeback_fields()
        except FeishuTopicSyncError as exc:
            field_setup_error = str(exc)
        rows = self.fetch_topic_rows(status=status, limit=limit)
        result = self.import_service.import_rows(
            rows,
            source_name=self.source_name(),
            plan=plan,
            dry_run=dry_run,
            skip_existing=skip_existing,
        )
        result["source"] = {
            "type": "feishu_bitable",
            "app_token": settings.feishu_topic_app_token or "",
            "table_id": settings.feishu_topic_table_id or "",
            "status_filter": status or "",
            "limit": limit,
            "ensured_fields": ensured_fields,
            "field_setup_error": field_setup_error,
        }
        return result

    def write_note_publish_result(
        self,
        *,
        topic: Topic,
        artifact: ContentArtifact,
        payload: ArtifactPublishResult,
    ) -> dict[str, object]:
        if not self.is_configured():
            missing = self.missing_config()
            raise FeishuTopicSyncError(f"Feishu topic writeback config missing: {missing}")
        if not topic.feishu_record_id:
            raise FeishuTopicSyncError(f"Topic {topic.id} has no feishu_record_id.")

        ensured_fields = self.ensure_note_writeback_fields()
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        is_success = payload.published or (payload.status or "").strip().lower() == "draft_created"
        note_status = payload.status if is_success else "failed"
        note_account = str(artifact.extra_metadata.get("note_account") or topic.note_account or "").strip()
        fields = {
            "note_account": note_account,
            "note_status": note_status,
            "note_url": payload.published_url or "",
            "note_published_at": now if is_success else "",
            "note_artifact_id": artifact.id,
            "note_error_message": payload.error_message or "",
        }
        written_fields = self.update_record_fields(topic.feishu_record_id, fields)
        return {
            "record_id": topic.feishu_record_id,
            "ensured_fields": ensured_fields,
            "written_fields": written_fields,
        }

    def write_legacy_note_publish_result(
        self,
        *,
        topic: Topic,
        artifact: ContentArtifact,
        payload: ArtifactPublishResult,
    ) -> dict[str, object]:
        if not self.is_legacy_configured():
            missing = self.missing_legacy_config()
            raise FeishuTopicSyncError(f"Feishu legacy topic writeback config missing: {missing}")
        if not topic.feishu_record_id:
            raise FeishuTopicSyncError(f"Topic {topic.id} has no feishu_record_id.")

        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        is_success = payload.published or (payload.status or "").strip().lower() == "draft_created"
        note_status = payload.status if is_success else "failed"
        note_account = str(artifact.extra_metadata.get("note_account") or topic.note_account or "").strip()
        fields = {
            "status": note_status,
            "note_account": note_account,
            "note_url": payload.published_url or "",
            "note_published_at": now if is_success else None,
            "error_message": payload.error_message or "",
        }
        written_fields = self.update_legacy_record_fields(topic.feishu_record_id, fields)
        return {
            "record_id": topic.feishu_record_id,
            "written_fields": written_fields,
            "table": "legacy_topic_main",
        }

    def write_ameba_publish_result(
        self,
        *,
        topic: Topic,
        artifact: ContentArtifact,
        payload: ArtifactPublishResult,
    ) -> dict[str, object]:
        if not self.is_configured():
            missing = self.missing_config()
            raise FeishuTopicSyncError(f"Feishu topic writeback config missing: {missing}")
        if not topic.feishu_record_id:
            raise FeishuTopicSyncError(f"Topic {topic.id} has no feishu_record_id.")

        ensured_fields = self.ensure_ameba_writeback_fields()
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        status = (payload.status or "").strip().lower()
        is_draft = status == "draft_created"
        is_published_unverified = status == "published_unverified"
        is_success = payload.published or is_draft
        fields = {
            "ameba_status": payload.status if is_success else "failed",
            "ameba_draft_url": (payload.published_url or "") if is_draft else "",
            "ameba_post_url": (payload.published_url or "") if payload.published and not is_published_unverified else "",
            "ameba_published_at": now if payload.published and not is_published_unverified else "",
            "ameba_artifact_id": artifact.id,
            "ameba_error_message": payload.error_message or "",
        }
        written_fields = self.update_record_fields(topic.feishu_record_id, fields)
        return {
            "record_id": topic.feishu_record_id,
            "ensured_fields": ensured_fields,
            "written_fields": written_fields,
        }

    def write_legacy_ameba_publish_result(
        self,
        *,
        topic: Topic,
        artifact: ContentArtifact,
        payload: ArtifactPublishResult,
    ) -> dict[str, object]:
        if not self.is_legacy_configured():
            missing = self.missing_legacy_config()
            raise FeishuTopicSyncError(f"Feishu legacy topic writeback config missing: {missing}")
        if not topic.feishu_record_id:
            raise FeishuTopicSyncError(f"Topic {topic.id} has no feishu_record_id.")

        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        status = (payload.status or "").strip().lower()
        is_draft = status == "draft_created"
        is_published_unverified = status == "published_unverified"
        is_success = payload.published or is_draft
        fields = {
            "ameba_status": payload.status if is_success else "failed",
            "ameba_draft_url": (payload.published_url or "") if is_draft else "",
            "ameba_post_url": (payload.published_url or "") if payload.published and not is_published_unverified else "",
            "ameba_published_at": now if payload.published and not is_published_unverified else None,
            "ameba_error_message": payload.error_message or "",
        }
        written_fields = self.update_legacy_record_fields(topic.feishu_record_id, fields)
        return {
            "record_id": topic.feishu_record_id,
            "written_fields": written_fields,
            "table": "legacy_topic_main",
        }

    def fetch_topic_rows(
        self,
        *,
        status: str | None = "ready",
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_configured():
            missing = self.missing_config()
            raise FeishuTopicSyncError(f"Feishu topic sync config missing: {missing}")

        rows: list[dict[str, Any]] = []
        page_token = ""
        has_more = True
        page_size = min(max(limit or 500, 1), 500)

        while has_more:
            params: dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token

            data = self._request(
                "GET",
                f"/open-apis/bitable/v1/apps/{settings.feishu_topic_app_token}/"
                f"tables/{settings.feishu_topic_table_id}/records",
                params=params,
            )
            for record in data.get("items", []):
                fields = dict(record.get("fields") or {})
                if status and str(fields.get("status", "")).strip().lower() != status.lower():
                    continue
                rows.append(self._fields_to_import_row(fields, str(record.get("record_id") or record.get("id") or "")))
                if limit and len(rows) >= limit:
                    return rows

            has_more = bool(data.get("has_more"))
            page_token = str(data.get("page_token") or "")

        return rows

    def create_topic_record(self, fields: dict[str, Any]) -> dict[str, object]:
        if not self.is_configured():
            missing = self.missing_config()
            raise FeishuTopicSyncError(f"Feishu topic sync config missing: {missing}")

        fields_meta = self._load_field_meta()
        outbound_fields: dict[str, Any] = {}
        for field_name, value in fields.items():
            if not field_name or value is None:
                continue
            if field_name not in fields_meta:
                continue
            outbound_fields[field_name] = self._normalize_outbound_value(field_name, value)

        if not outbound_fields:
            raise FeishuTopicSyncError("Cannot create Feishu topic record with empty fields.")

        data = self._request(
            "POST",
            f"/open-apis/bitable/v1/apps/{settings.feishu_topic_app_token}/"
            f"tables/{settings.feishu_topic_table_id}/records",
            json_body={"fields": outbound_fields},
        )
        record = dict(data.get("record") or {})
        record_id = str(record.get("record_id") or record.get("id") or data.get("record_id") or "")
        return {
            "record_id": record_id,
            "written_fields": list(outbound_fields.keys()),
        }

    def is_configured(self) -> bool:
        return not self.missing_config()

    def missing_config(self) -> list[str]:
        missing: list[str] = []
        if not settings.feishu_app_id:
            missing.append("FEISHU_APP_ID")
        if not settings.feishu_app_secret:
            missing.append("FEISHU_APP_SECRET")
        if not settings.feishu_topic_app_token:
            missing.append("FEISHU_TOPIC_APP_TOKEN")
        if not settings.feishu_topic_table_id:
            missing.append("FEISHU_TOPIC_TABLE_ID")
        return missing

    def notify_publish_result(
        self,
        *,
        topic: Topic,
        artifact: ContentArtifact,
        payload: ArtifactPublishResult,
    ) -> dict[str, object]:
        receive_id = (settings.feishu_notify_receive_id or "").strip()
        receive_id_type = (settings.feishu_notify_receive_id_type or "").strip()
        if not receive_id or not receive_id_type:
            raise FeishuTopicSyncError("Feishu notify target is not configured.")

        status = (payload.status or "").strip() or ("published" if payload.published else "failed")
        url = payload.published_url or artifact.published_url or ""
        text = "\n".join(
            [
                "Content Orchestrator 发布结果通知",
                f"平台：{artifact.platform}",
                f"账号：{artifact.extra_metadata.get('note_account') or topic.note_account or '-'}",
                f"状态：{status}",
                f"主题：{topic.master_topic}",
                f"关键词：{topic.target_keyword}",
                f"内容 ID：{artifact.id}",
                f"链接：{url or '-'}",
                f"错误：{payload.error_message or '-'}",
            ]
        )
        data = self._request(
            "POST",
            "/open-apis/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json_body={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        return {"message_id": data.get("message_id", ""), "receive_id_type": receive_id_type}

    def notify_text(self, text: str) -> dict[str, object]:
        receive_id = (settings.feishu_notify_receive_id or "").strip()
        receive_id_type = (settings.feishu_notify_receive_id_type or "").strip()
        if not receive_id or not receive_id_type:
            raise FeishuTopicSyncError("Feishu notify target is not configured.")

        data = self._request(
            "POST",
            "/open-apis/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json_body={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        return {"message_id": data.get("message_id", ""), "receive_id_type": receive_id_type}

    def is_legacy_configured(self) -> bool:
        return not self.missing_legacy_config()

    def missing_legacy_config(self) -> list[str]:
        missing: list[str] = []
        if not settings.feishu_app_id:
            missing.append("FEISHU_APP_ID")
        if not settings.feishu_app_secret:
            missing.append("FEISHU_APP_SECRET")
        if not settings.feishu_legacy_topic_app_token:
            missing.append("FEISHU_LEGACY_TOPIC_APP_TOKEN or FEISHU_APP_TOKEN")
        if not settings.feishu_legacy_topic_table_id:
            missing.append("FEISHU_LEGACY_TOPIC_TABLE_ID or FEISHU_TABLE_ID")
        return missing

    def source_name(self) -> str:
        return f"feishu:{settings.feishu_topic_app_token}/{settings.feishu_topic_table_id}"

    def _fields_to_import_row(self, fields: dict[str, Any], record_id: str) -> dict[str, Any]:
        def text_any(*names: str) -> str:
            for name in names:
                value = self._text(fields.get(name))
                if value:
                    return value
            return ""

        def list_any(*names: str) -> list[str]:
            for name in names:
                raw_value = fields.get(name)
                if isinstance(raw_value, list):
                    value = [str(item).strip() for item in raw_value if str(item).strip()]
                else:
                    value = [item.strip() for item in re.split(r"[,，、/|;\n]+", self._text(raw_value)) if item.strip()]
                if value:
                    return value
            return []

        row = {
            "master_topic": text_any("master_topic", "topic"),
            "topic_cluster": text_any("topic_cluster"),
            "business_goal": text_any("business_goal"),
            "target_keyword": text_any("target_keyword", "main_keyword"),
            "secondary_keyword": text_any("secondary_keyword"),
            "secondary_keywords": list_any("secondary_keywords"),
            "target_audience": text_any("target_audience"),
            "article_type": text_any("article_type"),
            "content_focus": text_any("content_focus"),
            "scenes": list_any("scenes"),
            "target_url": text_any("target_url"),
            "brand_name": text_any("brand_name"),
            "site": text_any("site"),
            "language": text_any("language"),
            "extra_rules": text_any("extra_rules"),
            "priority": text_any("priority") or "A",
            "target_platforms": list_any("target_platforms"),
            "status": text_any("status") or "ready",
            "brief": text_any("brief"),
            "note_account": text_any("note_account"),
            "source_record_id": record_id,
            "source_topic_id": text_any("topic_id"),
        }
        return row

    def _get_tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._tenant_access_token_expires_at:
            return self._tenant_access_token

        with httpx.Client(trust_env=False, timeout=30) as client:
            response = client.post(
                f"{settings.feishu_base_url}/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": settings.feishu_app_id,
                    "app_secret": settings.feishu_app_secret,
                },
            )
        if response.status_code >= 400:
            raise FeishuTopicSyncError(
                f"Failed to get Feishu tenant_access_token: HTTP {response.status_code}: {response.text}"
            )

        payload = response.json()
        if payload.get("code") != 0:
            raise FeishuTopicSyncError(
                f"Failed to get Feishu tenant_access_token: code={payload.get('code')} msg={payload.get('msg')}"
            )

        token = str(payload.get("tenant_access_token") or "")
        if not token:
            raise FeishuTopicSyncError("Feishu tenant_access_token response was empty.")

        expires_in = int(payload.get("expire") or 7200)
        self._tenant_access_token = token
        self._tenant_access_token_expires_at = now + max(expires_in - 60, 60)
        return token

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self._get_tenant_access_token()
        with httpx.Client(trust_env=False, timeout=60) as client:
            response = client.request(
                method,
                f"{settings.feishu_base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                json=json_body,
            )
        if response.status_code >= 400:
            raise FeishuTopicSyncError(
                f"Feishu API request failed: {method} {path}: HTTP {response.status_code}: {response.text}"
            )

        payload = response.json()
        if payload.get("code") != 0:
            raise FeishuTopicSyncError(
                f"Feishu API request failed: {method} {path}: code={payload.get('code')} msg={payload.get('msg')}"
            )
        return dict(payload.get("data") or {})

    def ensure_note_writeback_fields(self) -> list[str]:
        return self._ensure_writeback_fields(self.NOTE_WRITEBACK_FIELDS)

    def ensure_ameba_writeback_fields(self) -> list[str]:
        return self._ensure_writeback_fields(self.AMEBA_WRITEBACK_FIELDS)

    def _ensure_writeback_fields(self, field_defs: dict[str, int]) -> list[str]:
        if not self.is_configured():
            missing = self.missing_config()
            raise FeishuTopicSyncError(f"Feishu topic field config missing: {missing}")

        fields_meta = self._load_field_meta(force=True)
        created: list[str] = []
        for field_name, field_type in field_defs.items():
            if field_name in fields_meta:
                continue
            try:
                self._request(
                    "POST",
                    f"/open-apis/bitable/v1/apps/{settings.feishu_topic_app_token}/"
                    f"tables/{settings.feishu_topic_table_id}/fields",
                    json_body={"field_name": field_name, "type": field_type},
                )
            except FeishuTopicSyncError as exc:
                raise FeishuTopicSyncError(f"Failed to create Feishu field '{field_name}': {exc}") from exc
            created.append(field_name)

        if created:
            self._load_field_meta(force=True)
        return created

    def update_record_fields(self, record_id: str, fields: dict[str, Any]) -> list[str]:
        fields_meta = self._load_field_meta()
        outbound_fields: dict[str, Any] = {}
        for field_name, value in fields.items():
            if not field_name or value is None:
                continue
            if field_name not in fields_meta:
                continue
            outbound_fields[field_name] = self._normalize_outbound_value(field_name, value)

        if not outbound_fields:
            return []

        self._request(
            "PUT",
            f"/open-apis/bitable/v1/apps/{settings.feishu_topic_app_token}/"
            f"tables/{settings.feishu_topic_table_id}/records/{record_id}",
            json_body={"fields": outbound_fields},
        )
        return list(outbound_fields.keys())

    def update_legacy_record_fields(self, record_id: str, fields: dict[str, Any]) -> list[str]:
        outbound_fields = {field_name: value for field_name, value in fields.items() if field_name and value is not None}
        if not outbound_fields:
            return []

        self._request(
            "PUT",
            f"/open-apis/bitable/v1/apps/{settings.feishu_legacy_topic_app_token}/"
            f"tables/{settings.feishu_legacy_topic_table_id}/records/{record_id}",
            json_body={"fields": outbound_fields},
        )
        return list(outbound_fields.keys())

    def _load_field_meta(self, *, force: bool = False) -> dict[str, dict[str, Any]]:
        if self._field_meta_cache and not force:
            return self._field_meta_cache

        fields_by_name: dict[str, dict[str, Any]] = {}
        page_token = ""
        has_more = True

        while has_more:
            params: dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token

            data = self._request(
                "GET",
                f"/open-apis/bitable/v1/apps/{settings.feishu_topic_app_token}/"
                f"tables/{settings.feishu_topic_table_id}/fields",
                params=params,
            )

            for item in data.get("items", []):
                field_name = str(item.get("field_name") or "")
                if field_name:
                    fields_by_name[field_name] = dict(item)

            has_more = bool(data.get("has_more"))
            page_token = str(data.get("page_token") or "")

        self._field_meta_cache = fields_by_name
        return fields_by_name

    def _field_type(self, field_name: str) -> int | None:
        return self._load_field_meta().get(field_name, {}).get("type")

    def _normalize_outbound_value(self, field_name: str, value: Any) -> Any:
        field_type = self._field_type(field_name)
        if field_type == 1:
            return self._textify(value)
        if field_type == 5:
            if value == "":
                return None
            if isinstance(value, (int, float)):
                return int(value)
            text = str(value).strip()
            if not text:
                return None
            if text.isdigit():
                return int(text)
            return int(datetime.fromisoformat(text).timestamp() * 1000)
        if field_type == 4:
            return value if isinstance(value, list) else [str(value)]
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return value

    @staticmethod
    def _textify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        return str(value).strip()

    @staticmethod
    def _list_value(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        if value is None:
            return []
        return [item.strip().lower() for item in str(value).split(",") if item.strip()]
