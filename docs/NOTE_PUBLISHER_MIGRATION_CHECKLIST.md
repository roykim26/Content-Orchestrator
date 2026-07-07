# note-auto-publisher Migration Checklist

Use this checklist when migrating the existing `note-auto-publisher` to Content Orchestrator.

## Keep

- note login and session handling
- note publish implementation
- markdown rendering logic
- retry logic
- status logging

## Remove Or Bypass

- topic selection from upstream sheets or Feishu
- direct AI generation
- note-specific prompt assembly
- distribution logic
- SEO planning logic

## Add

1. Content Orchestrator client
2. Artifact claim flow
3. Artifact-to-note publish mapping
4. Publish result callback

## Required Mapping

Map orchestrator artifact fields to note publisher inputs:

- `title` -> note article title
- `content` -> note markdown body
- `metadata.target_keyword` -> optional tags or editorial metadata
- `artifact_id` -> publish result correlation id

## Suggested Worker Loop

1. Claim `note` artifacts from `/publisher/claims`
2. For each artifact:
   1. Validate title/content
   2. Reuse existing note publish code
   3. Report success or failure

## Failure Handling

If note publishing fails:

1. Keep platform-side retry behavior inside the publisher.
2. When retries are exhausted, call publish-result with:
   - `published=false`
   - `status=failed`
   - `error_message=<reason>`

## Definition Of Done

- note publisher no longer calls any LLM
- note publisher can publish claimed artifacts end to end
- publish result is written back to orchestrator
- duplicate publish is prevented by claim flow
