# Skills

Skill folders live here, one per skill: `data/skills/<name>/SKILL.md`.

Claude Code only loads skills from `.claude/skills`, and it refuses every write
under `.claude/` no matter what the permission rules say - so the bridge agent
could never create one there. `.claude/skills` is therefore a junction pointing
at this folder: Claude Code reads the skills through the link, while writes land
in `data/`, which `writable_paths` in `bridge/config.json` already allows.

`scripts/start-bridge.ps1` recreates the junction on every start, so a fresh
clone needs no manual setup.

A skill is a Markdown file with frontmatter:

    ---
    name: refund-policy
    description: How to answer refund questions. Use when a customer asks about refunds.
    ---

    ...instructions for the agent...

`description` is what the agent matches against, so say when the skill applies,
not just what it contains. A new skill is picked up by the next run - no restart.
