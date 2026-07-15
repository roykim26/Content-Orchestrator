from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.core.config import settings
from app.models.artifact import ArtifactGenerationPayload
from app.models.topic import Topic
from app.services.content_quality_service import UkamiruProductFacts, canonicalize_url


class ArtifactEngine:
    def __init__(self) -> None:
        self.generation_model = settings.openai_model
        self.product_facts = UkamiruProductFacts()

    def generate(self, payload: ArtifactGenerationPayload, topic: Topic) -> tuple[str, str, str]:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured for artifact generation.")

        system_prompt = str(payload.extra_metadata.get("system_prompt") or "").strip()
        response = self._chat_completion(
            system_prompt=system_prompt,
            user_prompt=self._build_user_prompt(payload, topic),
            response_format_json=True,
            max_tokens=max(settings.llm_max_tokens, 5000),
        )
        result = self._parse_generation_response(response, topic, platform=payload.platform)
        result = self._postprocess_generated_result(result, payload, topic)
        self._validate_generated_content(result, platform=payload.platform)
        return result

    def _generate_ameba(
        self,
        payload: ArtifactGenerationPayload,
        topic: Topic,
        *,
        system_prompt: str,
    ) -> tuple[str, str, str]:
        user_prompt = self._build_user_prompt(payload, topic)
        try:
            response = self._chat_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format_json=True,
                max_tokens=max(settings.llm_max_tokens, 8000),
            )
            result = self._parse_generation_response(response, topic, platform=payload.platform)
            self._validate_generated_content(result, platform=payload.platform)
            return result
        except RuntimeError as exc:
            if not self._should_retry_ameba_generation(exc):
                raise

        response = self._chat_completion(
            system_prompt=system_prompt,
            user_prompt=self._build_ameba_markdown_prompt(payload, topic),
            max_tokens=max(settings.llm_max_tokens, 8000),
        )
        result = self._parse_markdown_fallback(response, topic)
        self._validate_generated_content(result, platform=payload.platform)
        return result

    @staticmethod
    def _should_retry_ameba_generation(exc: RuntimeError) -> bool:
        text = str(exc)
        retry_tokens = [
            "LLM response content was empty",
            "LLM returned malformed JSON",
            "response_format",
            "json",
        ]
        return any(token.lower() in text.lower() for token in retry_tokens)

    def _chat_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format_json: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        base_url = settings.openai_base_url.rstrip("/")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        request_body: dict[str, Any] = {
            "model": settings.openai_model,
            "messages": messages,
            "temperature": settings.llm_temperature,
            "max_tokens": max_tokens or settings.llm_max_tokens,
        }
        if response_format_json:
            request_body["response_format"] = {"type": "json_object"}

        with httpx.Client(timeout=360, trust_env=False) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )

        if response.status_code >= 400:
            raise RuntimeError(f"LLM request failed: HTTP {response.status_code}: {response.text}")

        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("LLM response did not include choices.")

        content = self._extract_choice_content(choices[0])
        if not str(content).strip():
            finish_reason = choices[0].get("finish_reason", "")
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            message_keys = sorted(message.keys())
            raise RuntimeError(
                f"LLM response content was empty. finish_reason={finish_reason!r}, message_keys={message_keys!r}"
            )
        return str(content).strip()

    def _extract_choice_content(self, choice: dict[str, Any]) -> str:
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = message.get("content", "")
        text = self._content_to_text(content)
        if text:
            return text

        for key in ("output_text", "text"):
            text = self._content_to_text(message.get(key) or choice.get(key))
            if text:
                return text
        return ""

    def _content_to_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content") or item.get("output_text")
                    if text:
                        parts.append(str(text))
            return "\n".join(part.strip() for part in parts if part and part.strip()).strip()
        return str(value).strip()

    def _generate_legacy_article(self, payload: ArtifactGenerationPayload, topic: Topic) -> tuple[str, str, str]:
        messages = self._build_legacy_messages(payload, topic)
        last_error: RuntimeError | None = None
        user_prompt = messages[1]["content"]
        for attempt in range(2):
            response = self._chat_completion(
                system_prompt=messages[0]["content"],
                user_prompt=user_prompt,
                max_tokens=self._legacy_max_tokens(payload.platform, retry=attempt > 0),
            )
            title, body = self._extract_title_and_body(response, fallback_title=topic.master_topic)
            content = self._postprocess_legacy_article(body, topic, platform=payload.platform)
            summary = self._build_summary(content)
            result = (title, summary or self._build_summary(content), content)
            try:
                self._validate_generated_content(result, platform=payload.platform)
                return result
            except RuntimeError as exc:
                last_error = exc
                repaired = self._repair_legacy_result(result, topic, platform=payload.platform)
                if repaired:
                    try:
                        self._validate_generated_content(repaired, platform=payload.platform)
                        return repaired
                    except RuntimeError as repair_exc:
                        last_error = repair_exc
                if attempt >= 1:
                    raise
                if not self._should_regenerate_legacy_article(exc):
                    raise last_error
                user_prompt = self._build_legacy_retry_prompt(payload, topic, failure=str(last_error or exc))
        raise last_error or RuntimeError("Generated article failed validation.")

    @staticmethod
    def _legacy_max_tokens(platform: str, *, retry: bool = False) -> int:
        platform_key = str(platform or "").strip().lower()
        caps = {
            "note": (3000, 2400),
            "ameba": (3800, 3000),
        }
        first_cap, retry_cap = caps.get(platform_key, (3000, 2400))
        cap = retry_cap if retry else first_cap
        configured = max(int(settings.llm_max_tokens or cap), 1000)
        return min(configured, cap)

    @staticmethod
    def _should_regenerate_legacy_article(exc: RuntimeError) -> bool:
        text = str(exc).lower()
        retryable = [
            "too short",
            "at least two markdown h2",
            "formatting or encoding artifacts",
        ]
        return any(token in text for token in retryable)

    def _build_legacy_messages(self, payload: ArtifactGenerationPayload, topic: Topic) -> list[dict[str, str]]:
        row = self._topic_row(payload, topic)
        secondary_keyword_text = row["secondary_keyword"]
        if row["secondary_keywords"] and not secondary_keyword_text:
            secondary_keyword_text = " / ".join(row["secondary_keywords"])
        scenes_text = " / ".join(row["scenes"])
        anchor_candidates = self._anchor_candidates(row)
        anchor_text = " / ".join(anchor_candidates[:4]) if anchor_candidates else row["main_keyword"]
        context = "\n".join(
            self._legacy_context_lines(
                {
                    "topic": row["topic"],
                    "main_keyword": row["main_keyword"],
                    "secondary_keyword": secondary_keyword_text,
                    "audience": row["target_audience"],
                    "article_type": row["article_type"],
                    "content_focus": row["content_focus"],
                    "scenes": scenes_text,
                    "target_url": row["target_url"],
                    "brand_name": row["brand_name"],
                    "rules": row["extra_rules"],
                }
            )
        )

        if payload.platform.lower() == "ameba":
            system_prompt = (
                "You write warm, practical Japanese Ameba Blog articles.\n"
                "Ukamiru is the parent brand and primary destination for qualification-exam online practice.\n"
                "TakkenAI is only the宅建対策 module/subsite inside Ukamiru.\n"
                "Output final markdown only: title line, intro, 3-4 ## sections, closing.\n"
                "Do not output JSON, explanations, code fences, unsupported facts, or guaranteed-result claims.\n"
                "Use one natural target_url markdown link if target_url is provided."
            )
            user_prompt = (
                "Write an Ameba article in natural Japanese.\n"
                "Length: 1,400-1,900 Japanese characters.\n"
                "Must include: concrete example, practical checklist/workflow, one caution point.\n"
                "Tone: friendly, skim-friendly, not salesy.\n"
                f"Preferred link anchor: {anchor_text}\n\n"
                f"Context:\n{context}"
            )
            return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

        system_prompt = (
            "You write high-quality Japanese note articles.\n"
            "Ukamiru is the parent brand and primary destination for qualification-exam online practice.\n"
            "TakkenAI is only the宅建対策 module/subsite inside Ukamiru.\n"
            "Output final markdown only: title line, intro, 3-4 ## sections, closing.\n"
            "Do not output JSON, explanations, code fences, markdown links, raw URLs, or sales copy.\n"
            "Keep brand mentions neutral and natural."
        )
        user_prompt = (
            "Write a complete note article.\n"
            "Length: 1,200-1,600 Japanese characters.\n"
            "Start from the reader problem or scenario. Include concrete examples or decision criteria.\n"
            "Title must be natural and non-clickbait.\n\n"
            f"Context:\n{context}"
        )
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

        if payload.platform.lower() == "ameba":
            system_prompt = """
You are a Japanese blog editor for Ameba Blog.
Write reader-friendly Japanese articles for takkenai.jp, a site about 宅建 learning and exam preparation.

Hard requirements:
1. Output only the final article text. Do not output JSON or explanations.
2. Use Markdown headings.
3. Keep the tone warmer, lighter, and more conversational than note.
4. Do not promise guaranteed exam success.
5. Do not invent official dates, laws, statistics, or exam changes.
6. Mention the brand naturally when it helps the reader.
7. Include the target URL as a natural Markdown link when a target URL is provided.
8. Write a complete article, not a short announcement.
9. Target length: 1,800-2,600 Japanese characters.
10. Structure: introduction, 4-6 H2 sections, and a natural closing paragraph.
""".strip()
            user_prompt = f"""
Create an Ameba Blog article from this topic.

topic_id: {row["topic_id"]}
topic: {row["topic"]}
main_keyword: {row["main_keyword"]}
secondary_keyword: {secondary_keyword_text}
target_audience: {row["target_audience"]}
article_type: {row["article_type"]}
content_focus: {row["content_focus"]}
scenes: {scenes_text}
target_url: {row["target_url"]}
brand_name: {row["brand_name"]}
extra_rules: {row["extra_rules"]}

Writing requirements:
- Write in natural Japanese.
- Make it suitable for Ameba Blog: approachable, easy to skim, practical, and not too formal.
- Put the article title on the first line.
- Write 1,800-2,600 Japanese characters.
- Use 4-6 clear ## headings.
- Each ## section must contain 2-3 short paragraphs.
- Include at least one concrete example, one practical checklist or numbered workflow, and one caution point.
- Avoid ending after only a brief product explanation; make it read like a full blog post.
- Avoid salesy landing-page copy.
- If a target_url exists, use one natural Markdown link with anchor text chosen from: {anchor_text}
- End with a soft next step for readers who want to organize their 宅建 study.
""".strip()
            return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

        system_prompt = """
You are a high-quality note article writer.

Hard requirements:
1. Output only the final article text. Do not output explanations, prompt text, or JSON.
2. Use Markdown headings.
3. After the title, include at least 3 H2 sections. H3 sections are optional.
4. Do not include any Markdown links, raw URLs, or standalone related-page lines anywhere in the article.
5. If you mention the brand, keep it neutral and natural. Do not turn it into a promotion.
6. Do not include filler such as "below is the article".
7. Do not return empty content.
8. Every section heading must start with exactly "## " on its own line.
""".strip()
        user_prompt = f"""
Write a complete note article draft based on the topic below.

topic_id: {row["topic_id"]}
topic: {row["topic"]}
main_keyword: {row["main_keyword"]}
secondary_keyword: {secondary_keyword_text}
target_audience: {row["target_audience"]}
article_type: {row["article_type"]}
content_focus: {row["content_focus"]}
scenes: {scenes_text}
target_url: {row["target_url"]}
site: {row["site"]}
language: {row["language"]}
brand_name: {row["brand_name"]}
extra_rules: {row["extra_rules"]}

Writing requirements:
- {self._language_instruction(row["language"])}
- Keep the title natural and non-clickbait.
- Start the first paragraph directly from the reader problem or scenario.
- Use a clear ## / ### hierarchy in the body.
- Include 4-6 H2 sections, each beginning with exactly "## ".
- Each H2 section must contain 2-3 short paragraphs with concrete examples or decision criteria.
- Do not insert any Markdown links, raw URLs, or standalone related-page lines.
- If you mention brand_name, keep it as a neutral in-text mention only.
- End like a normal article, not like an advertisement or landing page.
- Output only the final article text.
""".strip()
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    @classmethod
    def _legacy_context_lines(cls, values: dict[str, Any]) -> list[str]:
        lines = []
        for key, value in values.items():
            text = cls._truncate_prompt_value(value)
            if text:
                lines.append(f"- {key}: {text}")
        return lines

    @staticmethod
    def _truncate_prompt_value(value: Any, limit: int = 220) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1].rstrip()}..."

    def _build_legacy_retry_prompt(
        self,
        payload: ArtifactGenerationPayload,
        topic: Topic,
        *,
        failure: str,
    ) -> str:
        row = self._topic_row(payload, topic)
        context = "\n".join(
            self._legacy_context_lines(
                {
                    "topic": row["topic"],
                    "main_keyword": row["main_keyword"],
                    "audience": row["target_audience"],
                    "content_focus": row["content_focus"],
                    "target_url": row["target_url"],
                }
            )
        )
        link_rule = "Use one natural markdown target_url link." if payload.platform.lower() == "ameba" else "No links or raw URLs."
        return f"""
Regenerate the full article. Previous draft failed: {self._truncate_prompt_value(failure, 160)}

Rules:
- Final markdown only, no JSON or code fences.
- Title line, intro, 3-4 ## sections, closing.
- Each ## heading must start with exactly "## ".
- 1,200-1,700 Japanese characters.
- {link_rule}

Context:
{context}
""".strip()

    def _topic_row(self, payload: ArtifactGenerationPayload, topic: Topic) -> dict[str, Any]:
        metadata = payload.extra_metadata
        configured_target_url = topic.target_url or str(metadata.get("target_url") or "")
        target_url = self.product_facts.resolve_target_url(topic)
        if configured_target_url and not self.product_facts._is_ukamiru_home(configured_target_url):
            target_url = configured_target_url
        target_url = canonicalize_url(target_url)
        brand_name = topic.brand_name or str(metadata.get("brand_name") or "") or self._infer_brand_name(topic)
        return {
            "topic_id": topic.feishu_topic_id or topic.id,
            "topic": topic.master_topic,
            "topic_cluster": topic.topic_cluster,
            "business_goal": topic.business_goal,
            "main_keyword": topic.target_keyword,
            "secondary_keyword": topic.secondary_keyword or str(metadata.get("secondary_keyword") or ""),
            "secondary_keywords": self._to_list(topic.secondary_keywords or metadata.get("secondary_keywords")),
            "target_audience": topic.target_audience or str(metadata.get("target_audience") or ""),
            "article_type": topic.article_type or str(metadata.get("article_type") or payload.content_type or ""),
            "content_focus": topic.content_focus or str(metadata.get("content_focus") or topic.brief or ""),
            "scenes": self._to_list(topic.scenes or metadata.get("scenes")),
            "target_url": target_url,
            "brand_name": brand_name,
            "site": topic.site or str(metadata.get("site") or "ukamiru.jp"),
            "language": topic.language or str(metadata.get("language") or "ja"),
            "extra_rules": topic.extra_rules or str(metadata.get("extra_rules") or topic.brief or ""),
        }

    @staticmethod
    def _infer_brand_name(topic: Topic) -> str:
        text = f"{topic.master_topic} {topic.target_keyword} {topic.topic_cluster} {topic.brief or ''}"
        if any(token in text for token in ("TakkenAI", "宅建", "takken")):
            return "Ukamiru / TakkenAI"
        return "Ukamiru"

    @classmethod
    def _infer_target_url(cls, topic: Topic) -> str:
        return "https://www.ukamiru.jp/"
        primary_text = f"{topic.master_topic} {topic.target_keyword} {topic.topic_cluster}"
        text = f"{topic.master_topic} {topic.target_keyword} {topic.topic_cluster} {topic.brief or ''}"
        takken_rules = [
            (("自己採点",), "https://www.takkenai.jp/tools/goukakuten-saitentool/"),
            (("合格点",), "https://www.takkenai.jp/tools/goukakuten-saitentool/"),
            (("学習スケジュール",), "https://www.takkenai.jp/tools/benkyou-keikaku/"),
            (("勉強時間",), "https://www.takkenai.jp/tools/benkyou-keikaku/"),
            (("模擬試験",), "https://www.takkenai.jp/mock-exam/"),
            (("過去問",), "https://www.takkenai.jp/takken/past-exams/"),
            (("ヤマ当て",), "https://www.takkenai.jp/takken/yamaate/"),
            (("知識点",), "https://www.takkenai.jp/takken/knowledge/"),
            (("動画講座",), "https://www.takkenai.jp/takken/video/"),
            (("音声講座",), "https://www.takkenai.jp/takken/audio/"),
            (("通信講座",), "https://www.takkenai.jp/takken/school/"),
            (("アプリ",), "https://www.takkenai.jp/takken/app/"),
            (("宅建",), "https://www.takkenai.jp/takken/"),
        ]
        real_estate_rules = [
            (("SNS", "投稿"), "https://www.takkenai.jp/tools/sns-generator/"),
            (("動画",), "https://www.takkenai.jp/tools/video-generator/"),
            (("チラシ",), "https://www.takkenai.jp/tools/flyer-generator/"),
            (("住宅ローン",), "https://www.takkenai.jp/tools/loan/"),
            (("仲介手数料",), "https://www.takkenai.jp/tools/brokerage-fee/"),
            (("価格査定",), "https://www.takkenai.jp/tools/property-valuation/"),
            (("エリア調査",), "https://www.takkenai.jp/tools/area-research/"),
            (("物件情報", "一括"), "https://www.takkenai.jp/tools/property-center/"),
            (("資金計画",), "https://www.takkenai.jp/tools/finance-center/"),
            (("賃貸管理",), "https://www.takkenai.jp/tools/rental-management/"),
            (("重説",), "https://www.takkenai.jp/tools/jusetsu-checker/"),
            (("事業用", "分析"), "https://www.takkenai.jp/tools/commercial-real-estate/"),
            (("利回り",), "https://www.takkenai.jp/tools/yield-calculator/"),
            (("不動産", "AI", "ツール"), "https://www.takkenai.jp/tools/"),
            (("不動産", "業務効率化"), "https://www.takkenai.jp/tools/"),
        ]
        rules = takken_rules if "宅建" in text else real_estate_rules
        for haystack in (primary_text, text):
            for keywords, url in rules:
                if all(keyword in haystack for keyword in keywords):
                    return url
        return "https://www.takkenai.jp/tools/" if "不動産" in text else "https://www.takkenai.jp/"

    @staticmethod
    def _language_instruction(language: str) -> str:
        normalized = str(language or "").strip().lower()
        if normalized in {"ja", "jp", "japanese", "日本語"}:
            return "Write in natural Japanese."
        if normalized in {"en", "english"}:
            return "Write in natural English."
        return "Use the language that best matches the topic and audience; prefer Japanese when unsure."

    @staticmethod
    def _to_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [part.strip() for part in re.split(r"[,，、/|;\n]+", text) if part.strip()]

    def _anchor_candidates(self, row: dict[str, Any]) -> list[str]:
        candidates = []
        candidates.extend(self._to_list(row.get("main_keyword")))
        candidates.extend(self._to_list(row.get("secondary_keyword")))
        candidates.extend(self._to_list(row.get("secondary_keywords")))
        candidates.extend(self._to_list(row.get("brand_name")))
        deduped = []
        seen = set()
        for item in candidates:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _repair_legacy_result(
        self,
        result: tuple[str, str, str],
        topic: Topic,
        *,
        platform: str,
    ) -> tuple[str, str, str] | None:
        title, summary, content = result
        content = self._promote_heading_like_lines(content)
        content = self._postprocess_legacy_article(content, topic, platform=platform)
        if len(content.strip()) < 700:
            return None

        title = re.sub(r"^#+\s*", "", str(title or "").strip())
        if len(title) < 8:
            title = topic.master_topic.strip()
        if len(title) < 8:
            return None

        summary = str(summary or "").strip()
        if len(summary) < 30:
            summary = self._build_summary(content)
        if len(summary) < 30:
            return None

        return title, summary, content

    @staticmethod
    def _promote_heading_like_lines(text: str) -> str:
        lines: list[str] = []
        for line in str(text or "").splitlines():
            stripped = line.strip()
            bold_heading = re.fullmatch(r"\*\*([^*]{3,80})\*\*", stripped)
            numbered_heading = re.fullmatch(r"\d+[.)]\s+(.{3,80})", stripped)
            if bold_heading:
                lines.append(f"## {bold_heading.group(1).strip()}")
                continue
            if numbered_heading:
                lines.append(f"## {numbered_heading.group(1).strip()}")
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _postprocess_legacy_article(self, content: str, topic: Topic, *, platform: str) -> str:
        row = self._topic_row(
            ArtifactGenerationPayload(task_id="", platform=platform, content_type="", objective="", angle=""),
            topic,
        )
        text = self._strip_json_fence(content)
        text = self._remove_raw_related_url_tail(text)
        text = self._normalize_markdown_headings(text)
        text = self._demote_oversized_markdown_headings(text)
        if platform.lower() == "note":
            text = self._strip_markdown_links_and_raw_urls(text)
        text = self._replace_target_markdown_links(
            text=text,
            target_url=row["target_url"],
            tracked_target_url=self._tracked_url_for_row(row, platform=platform),
        )
        text = self._ensure_target_link(text, row, platform=platform)
        text = self._collapse_duplicate_target_links(text, row, platform=platform)
        text = self._normalize_markdown_headings(self._remove_raw_related_url_tail(text))
        return self._demote_oversized_markdown_headings(text).strip()

    @staticmethod
    def _normalize_markdown_headings(text: str) -> str:
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                lines.append("")
                continue
            match = re.match(r"^(#{1,6})(.*)$", stripped)
            if match and match.group(2) and not match.group(2).startswith(" "):
                stripped = f"{match.group(1)} {match.group(2).lstrip()}"
            lines.append(stripped)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    @classmethod
    def _demote_oversized_markdown_headings(cls, text: str) -> str:
        lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            match = re.match(r"^(#{2,6})\s+(.+)$", stripped)
            if match and cls._is_oversized_markdown_heading(match.group(2)):
                lines.append(match.group(2).strip())
                continue
            lines.append(line)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    @staticmethod
    def _is_oversized_markdown_heading(heading: str) -> bool:
        normalized = re.sub(r"\s+", "", str(heading or ""))
        if len(normalized) > 90:
            return True
        sentence_marks = "。！？.!?"
        if len(normalized) > 60 and any(mark in normalized for mark in sentence_marks):
            return True
        return False

    @staticmethod
    def _remove_raw_related_url_tail(text: str) -> str:
        cleaned = []
        for line in text.splitlines():
            stripped = line.strip()
            if re.fullmatch(r"(関連ページ|関連記事|参考)\s*[:：]\s*https?://\S+", stripped, flags=re.IGNORECASE):
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    @staticmethod
    def _strip_markdown_links_and_raw_urls(text: str) -> str:
        cleaned = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
        cleaned = re.sub(r"https?://\S+", "", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    def _ensure_target_link(self, text: str, row: dict[str, Any], *, platform: str) -> str:
        target_url = self._tracked_url_for_row(row, platform=platform)
        if not text or not target_url or self._contains_markdown_link(text, target_url):
            return text
        for anchor_text in self._anchor_candidates(row):
            replaced = self._replace_first_plain_text_with_link_in_paragraphs(
                text=text,
                phrase=anchor_text,
                link_markdown=f"[{anchor_text}]({target_url})",
            )
            if replaced != text:
                return replaced
        fallback_anchor = row.get("main_keyword") or row.get("brand_name") or "詳しくはこちら"
        return self._append_sentence_to_last_paragraph(
            text,
            f"詳しくは、[{fallback_anchor}]({target_url}) も参考にしてみてください。",
        )

    @staticmethod
    def _contains_markdown_link(text: str, target_url: str) -> bool:
        if not text or not target_url:
            return False
        return re.search(rf"\[[^\]]+\]\({re.escape(target_url)}\)", text) is not None

    @staticmethod
    def _replace_first_plain_text_with_link_in_paragraphs(text: str, phrase: str, link_markdown: str) -> str:
        if not text or not phrase or not link_markdown:
            return text
        lines = text.splitlines()
        pattern = re.compile(rf"(?<!\[){re.escape(phrase)}(?!\]\()")
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            replaced = pattern.sub(link_markdown, line, count=1)
            if replaced != line:
                lines[index] = replaced
                return "\n".join(lines)
        return text

    @staticmethod
    def _append_sentence_to_last_paragraph(text: str, sentence: str) -> str:
        lines = text.splitlines()
        for index in range(len(lines) - 1, -1, -1):
            stripped = lines[index].strip()
            if not stripped:
                continue
            if stripped.startswith("#") or re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
                break
            joiner = "" if re.search(r"[。！？!?]$", stripped) else "。"
            lines[index] = f"{stripped}{joiner}{sentence}"
            return "\n".join(lines).strip()
        return f"{text}\n\n{sentence}".strip()

    @staticmethod
    def _build_tracked_target_url(
        *,
        target_url: str,
        platform: str,
        campaign: str = "",
        content_id: str = "",
    ) -> str:
        target_url = str(target_url or "").strip()
        platform_key = str(platform or "").strip().lower()
        if not target_url:
            return target_url
        if platform_key in {"x", "bluesky"}:
            return ArtifactEngine._strip_utm_parameters(target_url)
        tracked_platforms = {"note", "ameba", "hatena", "zenn"}
        if platform_key not in tracked_platforms:
            return target_url
        parsed = urlsplit(target_url)
        query_items = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ]
        query_items.append(("utm_source", platform_key))
        query_items.append(("utm_medium", "referral"))
        if campaign:
            query_items.append(("utm_campaign", campaign))
        if content_id:
            query_items.append(("utm_content", content_id))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query_items), parsed.fragment))

    @staticmethod
    def _strip_utm_parameters(url: str) -> str:
        parsed = urlsplit(str(url or "").strip())
        query_items = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query_items), parsed.fragment))

    def _tracked_url_for_row(self, row: dict[str, Any], *, platform: str) -> str:
        return self._build_tracked_target_url(
            target_url=str(row.get("target_url") or ""),
            platform=platform,
            campaign=str(row.get("business_goal") or row.get("topic_cluster") or ""),
            content_id=str(row.get("topic_id") or ""),
        )

    def _postprocess_generated_result(
        self,
        result: tuple[str, str, str],
        payload: ArtifactGenerationPayload,
        topic: Topic,
    ) -> tuple[str, str, str]:
        title, summary, content = result
        platform = payload.platform.lower()
        long_form_platforms = {"ameba", "hatena", "livedoor", "note", "zenn"}
        if platform not in long_form_platforms | {"x", "bluesky"}:
            return result

        row = self._topic_row(payload, topic)
        target_url = self._tracked_url_for_row(row, platform=platform)
        if not target_url:
            return result

        if platform in long_form_platforms:
            content = self._replace_target_markdown_links(
                text=content,
                target_url=row["target_url"],
                tracked_target_url=target_url,
            )
            content = self._ensure_target_link(content, row, platform=platform)
            content = self._collapse_duplicate_target_links(content, row, platform=platform)
        elif platform == "x":
            content = self._prepare_x_social_text(content)
        else:
            content = self._ensure_social_target_url(
                text=content,
                target_url=row["target_url"],
                tracked_target_url=target_url,
                max_length=300,
            )
        return title, summary, content

    def _prepare_x_social_text(self, text: str) -> str:
        cleaned = str(text or "").strip()
        cleaned = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"https?://[^\s]+", "", cleaned)
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
        return self._truncate_x_weighted(cleaned, max_weight=280)

    @classmethod
    def _truncate_x_weighted(cls, text: str, *, max_weight: int) -> str:
        if cls._x_weighted_length(text) <= max_weight:
            return text
        ellipsis = "..."
        ellipsis_weight = cls._x_weighted_length(ellipsis)
        budget = max(max_weight - ellipsis_weight, 0)
        kept: list[str] = []
        used = 0
        for char in text:
            char_weight = cls._x_char_weight(char)
            if used + char_weight > budget:
                break
            kept.append(char)
            used += char_weight
        return "".join(kept).rstrip(" \n\t.,!?;:\u3002\uff0c\uff01\uff1f\uff1b\uff1a") + ellipsis

    @classmethod
    def _x_weighted_length(cls, text: str) -> int:
        return sum(cls._x_char_weight(char) for char in str(text or ""))

    @staticmethod
    def _x_char_weight(char: str) -> int:
        codepoint = ord(char)
        if codepoint == 0:
            return 0
        if codepoint <= 0x10FF:
            return 1
        if 0x2000 <= codepoint <= 0x200D:
            return 1
        if 0x2010 <= codepoint <= 0x201F:
            return 1
        if 0x2032 <= codepoint <= 0x2037:
            return 1
        return 2

    def _ensure_social_target_url(
        self,
        *,
        text: str,
        target_url: str,
        tracked_target_url: str,
        max_length: int,
    ) -> str:
        cleaned = str(text or "").strip()
        markdown_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

        def replace_markdown(match: re.Match[str]) -> str:
            if self._is_same_target_link(url=match.group(2), target_url=target_url):
                return match.group(1)
            return match.group(0)

        cleaned = markdown_pattern.sub(replace_markdown, cleaned)
        for url in re.findall(r"https?://[^\s]+", cleaned):
            candidate = url.rstrip(".,!?;:)]}\u3002\uff0c\uff01\uff1f\uff1b\uff1a\uff09\u300d\u300f")
            if self._is_same_target_link(url=candidate, target_url=target_url):
                cleaned = cleaned.replace(candidate, "")
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        available = max_length - len(tracked_target_url) - 1
        if len(cleaned) > available:
            cleaned = cleaned[: max(available - 1, 0)].rstrip(" \n\t.,!?;:\u3002\uff0c\uff01\uff1f\uff1b\uff1a") + "\u2026"
        return f"{cleaned}\n{tracked_target_url}".strip()

    def _replace_target_markdown_links(self, *, text: str, target_url: str, tracked_target_url: str) -> str:
        if not text or not target_url or not tracked_target_url:
            return text
        pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

        def repl(match: re.Match[str]) -> str:
            url = match.group(2).strip()
            if self._is_same_target_link(url=url, target_url=target_url):
                return f"[{match.group(1)}]({tracked_target_url})"
            return match.group(0)

        return pattern.sub(repl, text)

    @staticmethod
    def _is_same_target_link(*, url: str, target_url: str) -> bool:
        url_parts = urlsplit(str(url or "").strip())
        target_parts = urlsplit(str(target_url or "").strip())
        url_host = url_parts.netloc.lower().removeprefix("www.")
        target_host = target_parts.netloc.lower().removeprefix("www.")
        if (url_parts.scheme, url_host, url_parts.path, url_parts.fragment) != (
            target_parts.scheme,
            target_host,
            target_parts.path,
            target_parts.fragment,
        ):
            return False
        url_query = [
            (key, value)
            for key, value in parse_qsl(url_parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ]
        target_query = [
            (key, value)
            for key, value in parse_qsl(target_parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ]
        return url_query == target_query

    def _collapse_duplicate_target_links(self, text: str, row: dict[str, Any], *, platform: str) -> str:
        target_url = self._tracked_url_for_row(row, platform=platform)
        if not text or not target_url:
            return text
        pattern = re.compile(rf"\[([^\]]+)\]\({re.escape(target_url)}\)")
        seen_first = False

        def repl(match: re.Match[str]) -> str:
            nonlocal seen_first
            if not seen_first:
                seen_first = True
                return match.group(0)
            return match.group(1)

        return pattern.sub(repl, text)

    @staticmethod
    def _extract_title_and_body(text: str, fallback_title: str) -> tuple[str, str]:
        raw_lines = [line.rstrip() for line in text.strip().splitlines()]
        lines = [line.strip() for line in raw_lines if line.strip()]
        if not lines:
            return fallback_title, text.strip()
        first = re.sub(r"^#+\s*", "", lines[0]).strip()
        if 3 <= len(first) <= 100:
            first_index = next((index for index, line in enumerate(raw_lines) if line.strip()), 0)
            body = "\n".join(raw_lines[first_index + 1 :]).strip()
            return first or fallback_title, body or text.strip()
        return fallback_title, text.strip()

    @staticmethod
    def _build_summary(content: str) -> str:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped[:220]
        return content.strip()[:220]

    def _build_user_prompt(self, payload: ArtifactGenerationPayload, topic: Topic) -> str:
        platform = payload.platform.lower()
        row = self._topic_row(payload, topic)
        tracked_target_url = self._tracked_url_for_row(row, platform=platform)
        product_context = self.product_facts.prompt_context(platform)
        if platform == "x":
            return "\n".join(
                [
                    "Create a publish-ready X post.",
                    "",
                    "Return JSON only with these keys:",
                    "- title: short internal label",
                    "- summary: short editorial summary",
                    "- content: final X post text, 60-130 Japanese characters",
                    "",
                    "Do not wrap the JSON in markdown code fences.",
                    "Do not include URLs, markdown links, hashtags, emojis, source notes, or meta commentary.",
                    "No link will be appended to X posts.",
                    "",
                    "Topic context:",
                    f"- master_topic: {topic.master_topic}",
                    f"- topic_cluster: {topic.topic_cluster}",
                    f"- business_goal: {topic.business_goal}",
                    f"- target_keyword: {topic.target_keyword}",
                    f"- brief: {topic.brief or ''}",
                    f"- target_url: {tracked_target_url}",
                    "",
                    "Writing requirements:",
                    "- Write in Japanese.",
                    "- Use one clear hook and one practical insight.",
                    "- Make it useful as a standalone social post.",
                    "- Keep it under X's 280 weighted-character limit; Japanese CJK characters count as 2.",
                    "- Avoid generic AI disclaimers and salesy claims.",
                    "- Mention Ukamiru naturally without a URL.",
                ]
            )
        if platform == "bluesky":
            return "\n".join(
                [
                    "Create a publish-ready Bluesky post.",
                    "",
                    "Return JSON only with these keys:",
                    "- title: short internal label",
                    "- summary: short editorial summary",
                    "- content: final Bluesky post text, 100-280 Japanese characters",
                    "",
                    "Do not wrap the JSON in markdown code fences.",
                    "Do not include markdown links, source notes, or meta commentary.",
                    "A tracked target URL will be appended automatically; make the CTA lead naturally into it.",
                    "",
                    "Topic context:",
                    f"- master_topic: {topic.master_topic}",
                    f"- topic_cluster: {topic.topic_cluster}",
                    f"- business_goal: {topic.business_goal}",
                    f"- target_keyword: {topic.target_keyword}",
                    f"- brief: {topic.brief or ''}",
                    f"- target_url: {tracked_target_url}",
                    "",
                    "Writing requirements:",
                    "- Write in Japanese.",
                    "- Use a conversational, discussion-friendly tone.",
                    "- Include one observation or question that invites replies.",
                    "- Keep it under 300 characters.",
                    "- Avoid generic AI disclaimers and salesy claims.",
                    "- Include a calm, concise CTA to visit Ukamiru.",
                ]
            )
        return "\n".join(
            [
                "Create a publish-ready content artifact.",
                "",
                "Return JSON only with these keys:",
                "- title: concise title in the same language as the target audience",
                "- summary: one short editorial summary",
                "- content: markdown body, ready to publish, 1200-1800 Japanese characters",
                "",
                "Do not wrap the JSON in markdown code fences.",
                "Do not include chain-of-thought, planning notes, source notes, or meta commentary.",
                "",
                "Topic context:",
                f"- master_topic: {topic.master_topic}",
                f"- topic_cluster: {topic.topic_cluster}",
                f"- business_goal: {topic.business_goal}",
                f"- target_keyword: {topic.target_keyword}",
                f"- priority: {topic.priority}",
                f"- brief: {topic.brief or ''}",
                f"- target_url: {tracked_target_url}",
                f"- target_audience: {row['target_audience']}",
                f"- article_type: {row['article_type']}",
                f"- content_focus: {row['content_focus']}",
                f"- scenes: {' / '.join(row['scenes'])}",
                f"- extra_rules: {row['extra_rules']}",
                "",
                "Distribution task:",
                f"- platform: {payload.platform}",
                f"- content_type: {payload.content_type}",
                f"- objective: {payload.objective}",
                f"- angle: {payload.angle}",
                "",
                "Product and platform constraints:",
                product_context,
                "",
                "Writing requirements:",
                "- Write in Japanese unless the topic clearly calls for another language.",
                "- Avoid generic AI disclaimers.",
                "- Treat target_keyword as a search query, not copy. Never reproduce a space-separated Japanese query verbatim; rewrite it as natural Japanese.",
                "- Keep product or brand references useful, not salesy.",
                "- Follow the supplied platform role and angle. Do not reuse the same comprehensive angle on every platform.",
                "- Use one short opening paragraph followed by 3-6 '##' sections.",
                "- Each section must contain concrete steps, examples, or decision criteria.",
                "- If the title promises 手順, 始め方, or 使い方, include at least three numbered steps and explain the actual user action and result.",
                "- Use only the verified product capability claims above. If the facts do not support a feature, omit it.",
                "- Do not use broken mojibake text, mixed encoding artifacts, or unreadable symbols.",
                "- Do not include front matter.",
                "- Include 1-3 natural Markdown links only when they help the reader; include target_url at least once.",
            ]
        )

    def _build_ameba_markdown_prompt(self, payload: ArtifactGenerationPayload, topic: Topic) -> str:
        return "\n".join(
            [
                "Create a publish-ready Ameba Blog article in markdown.",
                "",
                "Return markdown only. Do not return JSON. Do not wrap the response in code fences.",
                "",
                "Required structure:",
                "- Start with one H1 title using '# '.",
                "- Use 3-5 H2 sections.",
                "- Write 1200-1800 Japanese characters.",
                "- Keep paragraphs short and natural for a consumer blog.",
                "- Do not include chain-of-thought, planning notes, source notes, or meta commentary.",
                "",
                "Topic context:",
                f"- master_topic: {topic.master_topic}",
                f"- topic_cluster: {topic.topic_cluster}",
                f"- business_goal: {topic.business_goal}",
                f"- target_keyword: {topic.target_keyword}",
                f"- priority: {topic.priority}",
                f"- brief: {topic.brief or ''}",
                "",
                "Distribution task:",
                f"- platform: {payload.platform}",
                f"- content_type: {payload.content_type}",
                f"- objective: {payload.objective}",
                f"- angle: {payload.angle}",
                "",
                "Writing requirements:",
                "- Mention the target keyword naturally.",
                "- Avoid generic AI disclaimers.",
                "- Keep product or brand references useful, not salesy.",
                "- Do not use broken mojibake text, mixed encoding artifacts, or unreadable symbols.",
                "- Do not include front matter.",
            ]
        )

    def _parse_generation_response(self, response_text: str, topic: Topic, *, platform: str = "") -> tuple[str, str, str]:
        parsed = self._try_parse_json(response_text)
        if not parsed and platform.lower() == "ameba":
            parsed = self._try_extract_json_object(response_text)
        if parsed:
            title = str(parsed.get("title") or topic.master_topic).strip()
            summary = str(parsed.get("summary") or "").strip()
            content = str(parsed.get("content") or "").strip()
            if content:
                return title, summary, content
        if self._looks_like_json_response(response_text):
            raise RuntimeError("LLM returned malformed JSON for artifact generation.")

        title = topic.master_topic
        lines = [line.strip() for line in response_text.splitlines() if line.strip()]
        if lines and lines[0].startswith("#"):
            title = lines[0].lstrip("#").strip() or title
        summary = ""
        for line in lines:
            if not line.startswith("#") and len(line) >= 30:
                summary = line[:220]
                break
        return title, summary, response_text

    @staticmethod
    def _try_parse_json(text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        fenced_match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
        if fenced_match:
            cleaned = fenced_match.group(1).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @classmethod
    def _try_extract_json_object(cls, text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        start = cleaned.find("{")
        if start < 0:
            return None

        in_string = False
        escaped = False
        depth = 0
        for index in range(start, len(cleaned)):
            char = cleaned[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return cls._try_parse_json(cleaned[start : index + 1])
        return None

    def _parse_markdown_fallback(self, response_text: str, topic: Topic) -> tuple[str, str, str]:
        content = self._strip_json_fence(response_text).strip()
        title = topic.master_topic
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if lines and lines[0].startswith("#"):
            title = lines[0].lstrip("#").strip() or title
        summary = ""
        for line in lines:
            if not line.startswith("#") and len(line) >= 30:
                summary = line[:220]
                break
        return title, summary, content

    @staticmethod
    def _strip_json_fence(text: str) -> str:
        cleaned = text.strip()
        fenced_match = re.fullmatch(r"```(?:json|markdown|md)?\s*(.*?)\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
        if fenced_match:
            return fenced_match.group(1).strip()
        return cleaned

    @staticmethod
    def _looks_like_json_response(text: str) -> bool:
        cleaned = text.strip().lower()
        return cleaned.startswith("{") or cleaned.startswith("```json")

    def _validate_generated_content(self, result: tuple[str, str, str], *, platform: str) -> None:
        title, summary, content = result
        content_text = content.strip()
        platform_key = platform.lower()
        if len(title.strip()) < 8:
            raise RuntimeError("Generated title is too short.")
        min_summary_length = 8 if platform_key in {"x", "bluesky"} else 30
        if len(summary.strip()) < min_summary_length:
            raise RuntimeError("Generated summary is too short.")
        if platform_key == "x":
            if len(content_text) < 20:
                raise RuntimeError("Generated X content is too short.")
            if self._x_weighted_length(content_text) > 280:
                raise RuntimeError("Generated X content is too long.")
        elif platform_key == "bluesky":
            if len(content_text) < 20:
                raise RuntimeError("Generated Bluesky content is too short.")
            if len(content_text) > 300:
                raise RuntimeError("Generated Bluesky content is too long.")
        elif len(content_text) < 700:
            raise RuntimeError("Generated content is too short.")
        forbidden_tokens = [
            "```",
            "思考过程",
            "推論",
            "以下に",
            "JSON",
            "�",
            "ã",
            "å",
            "ç",
            "è",
            "é",
        ]
        if any(token in content_text for token in forbidden_tokens):
            raise RuntimeError("Generated content contains formatting or encoding artifacts.")
        heading_count = len(re.findall(r"(?m)^##\s+\S", content_text))
        long_form_platforms = {"ameba", "hatena", "livedoor", "note", "zenn"}
        if platform_key in long_form_platforms and heading_count < 2:
            raise RuntimeError("Generated article must include at least two markdown H2 sections.")
        oversized_headings = [
            match.group(2).strip()
            for match in re.finditer(r"(?m)^(#{2,6})\s+(.+)$", content_text)
            if self._is_oversized_markdown_heading(match.group(2))
        ]
        if platform_key in long_form_platforms and oversized_headings:
            raise RuntimeError("Generated article contains body-like oversized markdown headings.")
