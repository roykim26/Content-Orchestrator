# Zenn and Hatena Publisher 8221

This service publishes Content Orchestrator artifacts for:

- `zenn`
- `hatena` accounts `A` and `B`

It exposes the health and trigger endpoints expected by `PublishAutopilotService`.

By default, the service reuses the existing production publisher config from:

```text
E:\yanque\海外投放\zenn-bot\.env
```

Set `PLATFORM_PUBLISHER_ENV_PATH` only if that path changes.
The service also loads the Content Orchestrator `.env` first, so internal
settings such as `PUBLISHER_API_KEY` can stay in this repository.

## Start

```powershell
.\scripts\start-platform-publisher-8221.ps1
```

Health check:

```http
GET http://127.0.0.1:8221/health
```

Manual autopilot lanes:

```powershell
.\scripts\invoke-publish-autopilot.ps1 -Lane zenn
.\scripts\invoke-publish-autopilot.ps1 -Lane hatena_a
.\scripts\invoke-publish-autopilot.ps1 -Lane hatena_b
```

`all` intentionally keeps the existing note/Ameba rollout. Add these lanes to
`PUBLISH_AUTOPILOT_LANES` only after credentials have been configured and a
manual run succeeds.

## Shared Env

- `ORCHESTRATOR_BASE_URL`: defaults to `http://127.0.0.1:8020`
- `PUBLISHER_API_KEY`: must match Content Orchestrator when publisher auth is enabled
- `ORCHESTRATOR_CONSUMER_NAME`: defaults to `platform-publisher-8221`
- `PLATFORM_PUBLISHER_LOCAL_ENV_PATH`: defaults to `.env`
- `PLATFORM_PUBLISHER_ENV_PATH`: defaults to `E:\yanque\海外投放\zenn-bot\.env`

## Zenn Env

- `ZENN_REPO_PATH`: local Zenn repository path, required
- `ZENN_USERNAME`: used to build public article URLs. Current Zenn account: `takkenai26`.
- `ZENN_GIT_REMOTE` or existing `GIT_REMOTE`: defaults to `origin`
- `ZENN_GIT_BRANCH` or existing `GIT_BRANCH`: defaults to `main`
- `ZENN_DEFAULT_TOPICS`: defaults to `ai,edtech,ukamiru`
- `ZENN_DEFAULT_EMOJI`: defaults to `📝`
- `ZENN_ARTICLE_TYPE`: defaults to `tech`
- `ZENN_PUSH_ENABLED`: set `false` to commit locally without pushing

## Hatena Env

Generic fallback:

- `HATENA_ID`
- `HATENA_BLOG_ID`
- `HATENA_API_KEY`

Account-specific values are preferred when running `hatena_a` or `hatena_b`:

- `HATENA_ID_A`, `HATENA_BLOG_ID_A`, `HATENA_API_KEY_A`
- `HATENA_ID_B`, `HATENA_BLOG_ID_B`, `HATENA_API_KEY_B`

`HATENA_BLOG_ID` values may be provided either as the Hatena blog ID
(`takkenai.hatenablog.com`) or as a full blog URL
(`https://takkenai.hatenablog.com/`); the publisher normalizes full URLs
before calling the Hatena API.

The existing `zenn-bot` names are also supported:

- A account: `HATENA_ID`, `HATENA_BLOG_ID`, `HATENA_API_KEY`
- B account: `HATENA_ACCOUNT_B_ID`, `HATENA_ACCOUNT_B_BLOG_ID`, `HATENA_ACCOUNT_B_API_KEY`
- B export dir: `HATENA_ACCOUNT_B_EXPORT_DIR`

Other optional values:

- `HATENA_BASE_URL`: defaults to `https://blog.hatena.ne.jp`
- `HATENA_CONTENT_TYPE`: defaults to `text/x-markdown`
- `HATENA_EXPORT_DIR`: defaults to `hatena_exports`
- `HATENA_DEFAULT_DRAFT`: defaults to `no`
- `HATENA_ENABLE_CUSTOM_URL`: defaults to `true`
- `HATENA_ENABLE_PREVIEW`: defaults to `no`
- `HATENA_USE_SCHEDULED`: defaults to `no`
- `HATENA_TIMEZONE`: defaults to `Asia/Tokyo`
