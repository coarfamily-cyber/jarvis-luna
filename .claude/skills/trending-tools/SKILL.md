---
name: trending-tools
description: JARVIS LUNA 9-tool Trending AI Suite (Scrapling, Agent Desktop, WorkTrunk, Heretic, Local AI, Kronos)
---

# JARVIS LUNA Trending AI Suite Skill

Provides unified command-line access to the 9 GitHub Trending tools:

## Available Commands

1. **Scrapling Adaptive Scraper**
   `python automation/scrapling_crawler.py --url <URL>`
   Bypasses Cloudflare, auto-detects layout changes, extracts title, price, images.

2. **Agent Desktop Background App Automation**
   `python automation/agent_desktop.py --app <notepad|browser> --action write --payload <TEXT>`
   Controls desktop apps in background without stealing mouse or keyboard focus.

3. **WorkTrunk Multi-Agent Workspace Manager**
   `python automation/worktrunk_manager.py list`
   `python automation/worktrunk_manager.py create --agent <NAME>`
   `python automation/worktrunk_manager.py remove --agent <NAME>`
   Manages parallel git worktrees for concurrent AI coding instances.

4. **Heretic Direct Prompting & Uncensored Calibrator**
   `python automation/heretic_filter.py --text <TEXT> --mode <clean|system_prompt>`
   Strips corporate fluff, sycophancy, and artificial refusals.

5. **Local AI Hub (NanoChat / FreeToken / Colibri)**
   `python automation/local_ai_engines.py --engine <nanochat|freetoken|colibri> --prompt <PROMPT>`
   Unified local offline model execution.

6. **Kronos Time-Series & Price Forecaster**
   `python automation/kronos_forecaster.py --days 7 --prices 15000 15200 15800`
   Ecommerce price and demand trend predictions.

7. **Master Orchestrator Pipeline**
   `python automation/trending_ai_orchestrator.py pipeline --url <URL>`
   Runs Scrapling -> Kronos -> Heretic -> AgentDesktop end-to-end.
