# NOVA — demo commands

While the backend is running (and the desktop orb is up), try these. The
deterministic heuristic planner handles every one of them even without a
configured AI model — set `AI_PROVIDER=mock` for a fully offline demo.

| Command | What it does |
|---|---|
| "Open Chrome." | launches the browser |
| "Open VS Code." | opens VS Code (via `code`) |
| "Find my Downloads folder." | lists your Downloads |
| "Create a folder called AI Projects." | creates the folder (asks first) |
| "Take a screenshot." | captures the screen via ScreenObserver |
| "Open WhatsApp." | WhatsApp Desktop/web |
| "Open Rahul's chat." | opens the chat/search |
| "Download the latest photo." | fetches the newest WhatsApp media |
| "Build a complete React portfolio." | scaffolds + installs + builds + opens |
| "Run the project." | npm run dev in the current project |
| "Fix the errors." | inspects + repairs (self-repair dev mode) |
| "Search the web for the latest AI news." | live web search |
| "Start work mode." | runs your saved workflow macro |
| "Stop everything." / "Never mind." | cancels the active task |
| Ctrl+Alt+X | emergency stop (any time) |

Follow-ups ("Open Rahul's chat." → "Download the latest photo.") resolve via
conversational memory; remembered folders ("college_projects") via local memory.
