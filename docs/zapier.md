# Zapier (deferred)

Do **not** wire Zapier into the FastAPI app until the core pipeline works: upload → transcribe → summarize (AgentRouter) → PDF → Discord webhook.

Zapier is the later **human-tools layer**. Native LoWi still owns Neon, ElevenLabs, ARQ, and AgentRouter LLM calls. Object storage (R2/S3) is deferred; PDFs are generated on demand and audio is not archived long-term in v1.

## What it is

[Zapier MCP](https://mcp.zapier.com) lets the coding agent reach 9,000+ apps in chat (reads and, after confirmation, writes). That is different from a Zap that runs unattended on Zapier.com.

Use Zapier MCP while developing and operating LoWi. Optionally add Zapier webhooks later if a step must run without an agent in the loop.

## Already connected (2026-09-23)

| App | Account | Why it matters for LoWi |
|---|---|---|
| **GitHub** | Lil-mast #2 (second GitHub account also exists) | Issues/PRs for this repo; not part of the meeting pipeline |
| **Discord** | Salamander X Hapo Group | Target for summary delivery after the native webhook path is solid |

Verified live: GitHub **Find Repository** for `Lil-mast/lowi`. Discord **Find Channel** needs an exact channel name; do not guess. Confirm the `#channel` before enabling send actions.

## Native vs Zapier

| Step | Ship first (native) | Add with Zapier after core |
|---|---|---|
| Prep trigger | `POST /meetings` | Google Calendar: find upcoming events → create meeting + prep |
| Transcribe | ElevenLabs Scribe v2 | — |
| Summarize / prep brief | AgentRouter models | — |
| Distribute | Discord webhook in `app/services/discord.py` | Slack, extra Discord channels, richer routing |
| Archive | PDF on demand + Neon | Notion page, Google Docs |
| Notify | — | Gmail / email when a summary is ready |
| Build | — | GitHub issues from action items |

## Recommended apps and actions (when we add this)

Aim for 2–4 actions per app: one or two lookups, one or two writes. Prefer **Find/Get** lookups over **New/Updated** triggers for on-demand agent reads.

| Workflow | App | Lookups | Writes |
|---|---|---|---|
| Calendar prep | Google Calendar | Find Events | Create Detailed Event (optional) |
| Email notify | Gmail | Find Email | Send Email or Create Draft |
| Chat distribute | Discord (already on MCP) | Find Channel, Find User | Send Channel Message |
| Chat distribute | Slack (optional) | Find Message | Send Channel Message |
| Notes archive | Notion or Google Docs | Find Page / Get Document | Create Page / Create Document |
| Repo | GitHub (already on MCP) | Find Issue, Find Pull Request | Create Issue |

**Starter kit for LoWi:** Google Calendar + Gmail + Discord (+ Notion if we want a knowledge base). GitHub stays for engineering, not the meeting path.

## Suggested later flow

1. Calendar lookup: next meeting on the default calendar.
2. Native `POST /meetings` (or a thin Zapier → LoWi HTTP call) with title + `scheduled_at`.
3. Native pipeline: transcribe → AgentRouter summarize → PDF → store.
4. Zapier write: Discord channel message and/or Gmail draft with the summary link.
5. Optional: Notion/Docs page for the archive copy.

Writes (send, create, update) need an explicit confirm in chat. Reads can run without asking.

## Agent setup notes

- Server is **Agentic** Zapier MCP (inspect / discover / enable / execute tools).
- `auto_provision_mcp` can import existing Zapier connections if more apps are already on the Zapier account.
- Multiple accounts per app: default is fine unless work vs personal is obvious; then say which account and offer to switch.
- Do not duplicate Discord: native webhook first; Zapier Discord only if we need channel search or bot-style send without storing a webhook URL.

## When to implement

After:

- [ ] Meetings API + Neon schema
- [ ] Upload → ElevenLabs → AgentRouter summary
- [ ] PDF on demand (no object storage yet)
- [ ] Discord webhook send

Then add Calendar + Gmail (and optional Notion) via Zapier MCP, and document the chosen channel / calendar IDs here.
