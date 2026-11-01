# AI Agent Bot — Vercel version
Static frontend + Python serverless function. No API key needed.
Run locally: python app.py (port 8002) — same agent logic.
On Vercel: /api/chat handles chat, / serves index.html.
Note: Vercel functions are stateless — "make repo" returns the generated files as text in the reply, it does not persist a folder on the server. Download/copy the output to keep it.
