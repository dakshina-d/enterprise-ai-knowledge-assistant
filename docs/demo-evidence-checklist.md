# Demonstration Evidence Checklist

Capture evidence during rehearsal/recording, not as committed screenshots. Hide browser address bars
for private trace pages and never expose bearer tokens, credentials, password input, `.env.demo`,
private run/workspace IDs, raw prompts, or evidence bodies.

| Evidence | Required? | Where to capture | Suggested timestamp | Keep hidden |
|---|---|---|---|---|
| Public GitHub repository | Required | Repository landing page | 00:30 | Signed-in account details/notifications |
| Green GitHub Actions run | Required | Actions summary for final commit | 42:10 | Any secret-bearing job output |
| Final architecture diagram | Required | `docs/final-architecture.md` / SVG | 03:00 | Nothing sensitive |
| API and Streamlit startup | Required | Safe terminals plus health pages | 09:30 | Environment values/container internals |
| Viewer policy response with citations | Required | Streamlit answer and sources | 13:00 | Token, raw evidence IDs/paths |
| Multi-turn continuation | Required | Same Viewer conversation | 15:30 | Internal memory/checkpoint state |
| Viewer Python denial | Required | Streamlit activity/result | 17:15 | Raw policy internals |
| Viewer MCP denial | Required | Streamlit activity/result | 18:00 | Protocol internals |
| Restricted-content denial | Required | Streamlit activity/result | 18:45 | Restricted title/content/IDs |
| Direct prompt-injection rejection | Required | Streamlit safe outcome | 19:30 | System prompt/private reasoning |
| Analyst MCP result | Required | Streamlit result/provenance | 22:30 | Raw MCP payload or internal trace IDs |
| Analyst Python result | Required | Streamlit result/provenance | 28:30 | Source rows, paths, parameters |
| Recursive research activity | Required | Expanded Agent Activity Panel | 34:30 | Internal task state/prompts |
| Citation rendering | Required | Final research response sources | 38:00 | Internal evidence UUIDs/paths |
| Memory update | Required | Activity panel/follow-up | 16:00 or 38:30 | Stored sanitized turn contents beyond UI |
| Token Bucket 429 | Required evidence; live optional | Automated test output or rehearsed safe 429 | 43:00 | Bearer token/network fingerprint |
| Graceful dependency failure | Required evidence | Failure-matrix test output | 42:40 | Raw provider/SDK exceptions |
| LangSmith successful hierarchy | Required manual trace evidence | LangSmith project screen | 39:30 | Key, private URL, workspace/run IDs, raw content |
| LangSmith denied Viewer trace | Required manual trace evidence | LangSmith project screen | 41:00 | Private identifiers; restricted request text |
| Full test-suite result | Required | Terminal or GitHub Actions | 42:10 | Local absolute paths/usernames |
| Assumptions and trade-offs | Required | Documentation | 44:05 | Nothing sensitive |
| Public video URL | Required after upload | Submission document | After recording | Private draft/share-management URLs |
| Live OpenAI answer | Optional | Streamlit | Separate appendix | API key, request/response trace body |
| Live Pinecone query | Optional | CLI/UI | Separate appendix | API key, index host/private metadata |
| Container runtime proof | Available local bonus evidence | Compose `ps` and smoke output | 10:30 | Container IDs, environment, mounted paths |

Before publishing, replay the recording at normal speed and inspect every terminal, address bar,
notification, password field, and trace screen. Redact by re-recording; do not rely on viewers to
ignore exposed secrets.
