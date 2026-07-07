# Publisher Integration Protocol

This document defines how existing publisher systems should integrate with Content Orchestrator in Phase 2.

## Goal

Existing publishers should stop generating content themselves and instead:

1. Claim publish-ready artifacts from Content Orchestrator.
2. Publish the artifact using their existing platform-specific logic.
3. Report the publish result back to Content Orchestrator.

This keeps each publisher focused on execution only.

## Authentication

If `PUBLISHER_API_KEY` is configured on the orchestrator, publisher endpoints require:

```http
Authorization: Bearer <PUBLISHER_API_KEY>
```

If `PUBLISHER_API_KEY` is unset, the publisher endpoints remain open for local integration and testing.

## Required Flow

### 1. Claim artifacts

Publisher calls:

```http
POST /publisher/claims
Content-Type: application/json
Authorization: Bearer <PUBLISHER_API_KEY>
```

Example request:

```json
{
  "platform": "note",
  "consumer_name": "note-auto-publisher",
  "account": "note_a",
  "limit": 1
}
```

`account` is the generic account or lane key used by multi-account publishers,
for example `ta_x`, `ta_bsky`, `A`, `B`, or `note_a`.
`note_account` is still accepted for existing note workers and is treated as a
legacy alias of `account` when `platform` is `note`.

Example response:

```json
{
  "consumer_name": "note-auto-publisher",
  "claimed_count": 1,
  "artifacts": [
    {
      "artifact_id": "art_001",
      "topic_id": "topic_001",
      "platform": "note",
      "content_type": "article",
      "title": "Why real estate SNS posting stalls",
      "summary": "Operator-focused content for note.",
      "content": "# Markdown body",
      "format": "markdown",
      "status": "publishing",
      "metadata": {
        "objective": "brand_awareness",
        "target_keyword": "不動産 SNS 投稿 AI"
      }
    }
  ]
}
```

### 2. Publish with existing publisher logic

Publisher should reuse all existing platform-specific logic such as:

- login
- markdown conversion
- upload / deploy
- retry
- cooldown
- publish throttling

Publisher should no longer handle:

- topic selection
- AI generation
- prompt selection
- SEO planning
- distribution planning

### 3. Report result

Publisher calls:

```http
POST /publisher/artifacts/{artifact_id}/publish-result
Content-Type: application/json
Authorization: Bearer <PUBLISHER_API_KEY>
```

Success example:

```json
{
  "published": true,
  "published_url": "https://note.com/example/n/abc123",
  "external_publish_id": "abc123",
  "status": "published",
  "error_message": null
}
```

Failure example:

```json
{
  "published": false,
  "published_url": null,
  "external_publish_id": null,
  "status": "failed",
  "error_message": "login session expired"
}
```

## Artifact Semantics

Important fields:

- `artifact_id`: stable identifier for result reporting
- `platform`: target publisher platform
- `content_type`: article, short_post, slides, and so on
- `title`: human title when applicable
- `summary`: optional summary
- `content`: final content body to publish
- `format`: markdown, text, json, and so on
- `metadata`: extra execution context such as keyword, tags, or objective
- `metadata.account`: generic publisher account key when the lane is account-specific
- `metadata.note_account`: legacy note account key for existing note workers

## State Machine

Expected state changes:

1. `generated`
2. `publish_pending`
3. `publishing`
4. `published` or `failed`

`publishing` means the artifact has been leased to one publisher worker and should not be claimed by another worker at the same time.

## Retry Expectations

Recommended behavior:

1. Retry inside the publisher for transient platform errors.
2. If all retries fail, report `failed`.
3. Let the orchestrator decide whether to reset the artifact or create a new retry flow later.

Do not silently swallow failed publishes.

## Manual Recovery

If an artifact is marked as `failed`, an operator can re-queue it with:

```http
POST /artifacts/{artifact_id}/requeue
Content-Type: application/json
```

Example request:

```json
{
  "requested_by": "ops",
  "reason": "session refreshed",
  "clear_error": true
}
```

This resets the artifact to `publish_pending` so a publisher worker can claim it again.

## Security

Recommended next step:

- Add bearer-token auth between publishers and Content Orchestrator.

Current scaffold exposes open endpoints for local integration and testing.
