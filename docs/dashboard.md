# Dashboard

Run `agentctl dashboard` and open `http://127.0.0.1:8787`. Select a saved run to replay its DAG and event timeline. Nodes expose real owner/status/model/reasoning/confidence/duration and token usage. Routing, performance, escalation, and efficiency panels are derived from SQLite. SSE refreshes the selected run as events arrive. Token values show `measured`, `estimated`, or `unavailable` explicitly.
