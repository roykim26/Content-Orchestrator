from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import httpx

from app.integrations.publisher_worker import PublishOutcome


ATOM_NS = "http://www.w3.org/2005/Atom"
APP_NS = "http://www.w3.org/2007/app"
HATENA_BLOG_NS = "http://www.hatena.ne.jp/info/xmlns#hatenablog"

ET.register_namespace("", ATOM_NS)
ET.register_namespace("app", APP_NS)
ET.register_namespace("hatenablog", HATENA_BLOG_NS)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _account_env(base_name: str, account: str | None, default: str = "") -> str:
    account_key = str(account or "").strip().upper()
    candidates = []
    if account_key:
        suffix = base_name.removeprefix("HATENA_")
        candidates.extend(
            [
                f"{base_name}_{account_key}",
                f"HATENA_{account_key}_{suffix}",
                f"HATENA_ACCOUNT_{account_key}_{suffix}",
            ]
        )
    candidates.append(base_name)
    for name in candidates:
        value = _env(name)
        if value:
            return value
    return default


def _split_tags(value: Any, *, limit: int = 10) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,，、\s]+", str(value or ""))
    tags: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in tags:
            tags.append(text)
    return tags[:limit]


def _slugify(*parts: str, prefix: str) -> str:
    source = "-".join(part for part in parts if part).lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", source).strip("-")
    if not ascii_text:
        ascii_text = f"{prefix}-{abs(hash(source or prefix)) % 10_000_000}"
    return ascii_text[:70].strip("-") or prefix


def _article_from_artifact(artifact: dict[str, Any], *, default_tags: list[str]) -> dict[str, Any]:
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    title = str(artifact.get("title") or metadata.get("title") or "Untitled").strip()
    summary = str(artifact.get("summary") or metadata.get("summary") or "").strip()
    content = str(artifact.get("content") or "").strip()
    tags = (
        _split_tags(metadata.get("tags"), limit=10)
        or _split_tags(metadata.get("target_keyword"), limit=5)
        or default_tags
    )
    return {
        "title": title,
        "summary": summary,
        "body_md": content,
        "tags": tags,
    }


@dataclass(slots=True)
class ZennPublisher:
    repo_path: str
    username: str = ""
    remote: str = "origin"
    branch: str = "main"
    default_topics: tuple[str, ...] = ("ai", "edtech", "ukamiru")
    default_emoji: str = "📝"
    article_type: str = "tech"
    push_enabled: bool = True

    @classmethod
    def from_env(cls) -> "ZennPublisher":
        return cls(
            repo_path=_env("ZENN_REPO_PATH"),
            username=_env("ZENN_USERNAME", "takkenai26"),
            remote=_env("ZENN_GIT_REMOTE") or _env("GIT_REMOTE", "origin"),
            branch=_env("ZENN_GIT_BRANCH") or _env("GIT_BRANCH", "main"),
            default_topics=tuple(_split_tags(_env("ZENN_DEFAULT_TOPICS", "ai,edtech,ukamiru"), limit=5)),
            default_emoji=_env("ZENN_DEFAULT_EMOJI", "📝"),
            article_type=_env("ZENN_ARTICLE_TYPE", "tech"),
            push_enabled=_env("ZENN_PUSH_ENABLED", "true").lower() != "false",
        )

    def publish(self, artifact: dict[str, Any]) -> PublishOutcome:
        if not self.repo_path:
            return PublishOutcome(False, status="failed", error_message="ZENN_REPO_PATH is not configured.")

        repo = Path(self.repo_path)
        articles_dir = repo / "articles"
        articles_dir.mkdir(parents=True, exist_ok=True)

        article = _article_from_artifact(artifact, default_tags=list(self.default_topics))
        slug = _slugify(article["title"], str(artifact.get("artifact_id") or ""), prefix="zenn")
        relative_path = f"articles/{slug}.md"
        article_path = repo / relative_path
        topics = _split_tags(article["tags"], limit=5) or list(self.default_topics)
        body = article["body_md"].strip()

        frontmatter = (
            "---\n"
            f"title: {json.dumps(article['title'], ensure_ascii=False)}\n"
            f"emoji: {json.dumps(self.default_emoji, ensure_ascii=False)}\n"
            f"type: {json.dumps(self.article_type, ensure_ascii=False)}\n"
            f"topics: {json.dumps(topics, ensure_ascii=False)}\n"
            "published: true\n"
            "---\n\n"
        )
        article_path.write_text(frontmatter + body + "\n", encoding="utf-8")

        try:
            git_result = self._commit_and_push(repo, [relative_path], f"zenn: publish {slug}")
        except Exception as exc:  # noqa: BLE001
            return PublishOutcome(False, status="failed", error_message=str(exc))

        username = self.username or self._infer_username_from_remote(repo)
        published_url = f"https://zenn.dev/{username}/articles/{slug}" if username else None
        return PublishOutcome(
            published=True,
            published_url=published_url,
            external_publish_id=git_result.get("commit") or slug,
            status="published" if published_url else "published_unverified",
        )

    def _commit_and_push(self, repo: Path, file_paths: list[str], message: str) -> dict[str, str]:
        self._run(repo, "git", "rev-parse", "--is-inside-work-tree")
        self._run(repo, "git", "add", "--", *file_paths)
        if self._run(repo, "git", "diff", "--cached", "--quiet", check=False).returncode == 0:
            return {"commit": self._run(repo, "git", "rev-parse", "HEAD").stdout.strip(), "message": "no staged changes"}
        self._run(repo, "git", "commit", "-m", message)
        commit = self._run(repo, "git", "rev-parse", "HEAD").stdout.strip()
        if self.push_enabled:
            self._push_with_retry(repo)
        return {"commit": commit, "message": message}

    def _push_with_retry(self, repo: Path) -> None:
        last_error = ""
        for attempt in range(1, 4):
            result = self._run(repo, "git", "push", self.remote, self.branch, check=False)
            if result.returncode == 0:
                return
            last_error = f"git push attempt {attempt} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            if attempt < 3:
                self._run(repo, "git", "pull", "--rebase", self.remote, self.branch, check=False)
                time.sleep(min(attempt * 2, 10))
        raise RuntimeError(last_error)

    def _infer_username_from_remote(self, repo: Path) -> str:
        result = self._run(repo, "git", "remote", "get-url", self.remote, check=False)
        if result.returncode != 0:
            return ""
        remote_url = result.stdout.strip()
        match = re.search(r"[:/]([^/:]+)/(?:[^/]+?)(?:\.git)?$", remote_url)
        return match.group(1) if match else ""

    @staticmethod
    def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(args, cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if check and result.returncode != 0:
            raise RuntimeError(f"Command failed: {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        return result


@dataclass(slots=True)
class HatenaPublisher:
    account: str | None = None

    def publish(self, artifact: dict[str, Any]) -> PublishOutcome:
        account = self.account or str((artifact.get("metadata") or {}).get("account") or "").strip() or None
        try:
            config = self._config(account)
            article = _article_from_artifact(artifact, default_tags=["Ukamiru"])
            slug = _slugify(article["title"], str(artifact.get("artifact_id") or ""), prefix="hatena")
            export_dir = Path(config["export_dir"])
            export_dir.mkdir(parents=True, exist_ok=True)
            (export_dir / f"{slug}.md").write_text(self._local_markdown(article), encoding="utf-8")
            entry_xml = self._entry_xml(article=article, slug=slug, config=config)
            result = self._post_entry(entry_xml, config=config)
        except Exception as exc:  # noqa: BLE001
            return PublishOutcome(False, status="failed", error_message=str(exc))

        published_url = result.get("article_url") or result.get("preview_url") or result.get("edit_url")
        return PublishOutcome(
            published=True,
            published_url=published_url,
            external_publish_id=result.get("platform_post_id") or slug,
            status="draft_created" if config["default_draft"] else "published",
        )

    def _config(self, account: str | None) -> dict[str, Any]:
        hatena_id = _account_env("HATENA_ID", account)
        blog_id = _account_env("HATENA_BLOG_ID", account)
        api_key = _account_env("HATENA_API_KEY", account)
        missing = [name for name, value in [("HATENA_ID", hatena_id), ("HATENA_BLOG_ID", blog_id), ("HATENA_API_KEY", api_key)] if not value]
        if missing:
            suffix = f" for account {account}" if account else ""
            raise ValueError(f"Missing Hatena config{suffix}: {', '.join(missing)}")
        return {
            "hatena_id": hatena_id,
            "blog_id": blog_id,
            "api_key": api_key,
            "base_url": _account_env("HATENA_BASE_URL", account, "https://blog.hatena.ne.jp").rstrip("/"),
            "content_type": _account_env("HATENA_CONTENT_TYPE", account, "text/x-markdown"),
            "export_dir": _account_env("HATENA_EXPORT_DIR", account, "hatena_exports"),
            "default_draft": _account_env("HATENA_DEFAULT_DRAFT", account, "no").lower() == "yes",
            "enable_custom_url": _account_env("HATENA_ENABLE_CUSTOM_URL", account, "true").lower() == "true",
            "enable_preview": _account_env("HATENA_ENABLE_PREVIEW", account, "no").lower() == "yes",
            "use_scheduled": _account_env("HATENA_USE_SCHEDULED", account, "no").lower() == "yes",
            "timezone": _account_env("HATENA_TIMEZONE", account, "Asia/Tokyo"),
        }

    @staticmethod
    def _local_markdown(article: dict[str, Any]) -> str:
        parts = [f"# {article['title']}\n\n"]
        if article["summary"]:
            parts.append(f"> {article['summary']}\n\n")
        if article["tags"]:
            parts.append("categories: " + ", ".join(article["tags"]) + "\n\n")
        parts.append(article["body_md"].strip())
        return "".join(parts).rstrip() + "\n"

    def _entry_xml(self, *, article: dict[str, Any], slug: str, config: dict[str, Any]) -> str:
        entry = ET.Element(f"{{{ATOM_NS}}}entry")
        ET.SubElement(entry, f"{{{ATOM_NS}}}title").text = article["title"]
        author = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
        ET.SubElement(author, f"{{{ATOM_NS}}}name").text = config["hatena_id"]
        ET.SubElement(entry, f"{{{ATOM_NS}}}content", {"type": config["content_type"]}).text = article["body_md"].strip()
        ET.SubElement(entry, f"{{{ATOM_NS}}}updated").text = datetime.now(ZoneInfo(config["timezone"])).isoformat(timespec="seconds")
        for tag in _split_tags(article["tags"], limit=10):
            ET.SubElement(entry, f"{{{ATOM_NS}}}category", {"term": tag})
        control = ET.SubElement(entry, f"{{{APP_NS}}}control")
        ET.SubElement(control, f"{{{APP_NS}}}draft").text = "yes" if config["default_draft"] else "no"
        ET.SubElement(control, f"{{{APP_NS}}}preview").text = "yes" if config["default_draft"] and config["enable_preview"] else "no"
        ET.SubElement(control, f"{{{HATENA_BLOG_NS}}}scheduled").text = "yes" if config["default_draft"] and config["use_scheduled"] else "no"
        if config["enable_custom_url"]:
            ET.SubElement(entry, f"{{{HATENA_BLOG_NS}}}custom-url").text = slug
        return ET.tostring(entry, encoding="utf-8", xml_declaration=True).decode("utf-8")

    def _post_entry(self, entry_xml: str, *, config: dict[str, Any]) -> dict[str, str]:
        url = f"{config['base_url']}/{config['hatena_id']}/{config['blog_id']}/atom/entry"
        with httpx.Client(timeout=30, trust_env=False) as client:
            response = client.post(
                url,
                content=entry_xml.encode("utf-8"),
                headers={
                    "Content-Type": "application/atom+xml;type=entry;charset=utf-8",
                    "Accept": "application/atom+xml;type=entry, application/xml, text/xml",
                    "User-Agent": "content-orchestrator-platform-publisher/1.0",
                },
                auth=(config["hatena_id"], config["api_key"]),
            )
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"Hatena publish failed: HTTP {response.status_code}: {response.text[:1000]}")
        return self._parse_hatena_response(response.text, response.headers.get("Location", ""))

    @staticmethod
    def _parse_hatena_response(xml_text: str, location: str) -> dict[str, str]:
        ns = {"atom": ATOM_NS}
        root = ET.fromstring(xml_text.encode("utf-8"))

        def link(rel: str) -> str:
            for node in root.findall("atom:link", ns):
                if node.attrib.get("rel") == rel:
                    return node.attrib.get("href", "").strip()
            return ""

        edit_url = link("edit") or location.strip()
        return {
            "article_url": link("alternate"),
            "preview_url": link("preview"),
            "edit_url": edit_url,
            "platform_post_id": edit_url.rstrip("/").split("/")[-1] if edit_url else "",
        }


def quoted_path_url(path: str) -> str:
    return quote(path.replace("\\", "/"), safe="/:")
