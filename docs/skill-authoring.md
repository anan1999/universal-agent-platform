# Authoring a Skill

Create `.agent/skills/<id>/skill.json` and `.agent/skills/<id>/SKILL.md`. Use a stable lowercase
identifier and semantic version. Declare only capabilities the procedure actually covers.

Minimal example:

```json
{
  "id": "accessibility-review",
  "version": "1.0.0",
  "description": "Review an interface against a bounded accessibility checklist.",
  "capabilities": ["accessibility"],
  "inputs": {"artifact": "path"},
  "outputs": {"report": "markdown"},
  "references": {"wcag-checklist": "references/wcag-checklist.md"},
  "evaluation": ["required_sections"],
  "security": {"scripts": false, "network": false},
  "trust": "project_local",
  "status": "active"
}
```

Keep `SKILL.md` procedural and bounded: define preconditions, ordered steps, output evidence, and
failure conditions. Put large or optional knowledge in named references so it is loaded only when
needed. Dependencies name other Skill IDs and must form an acyclic graph.

Validate and inspect resolution before use:

```bash
agentctl skill validate accessibility-review
agentctl skill explain accessibility-review
agentctl skill candidates "accessibility"
```

Never edit a released version in place. Create a new version after evaluation. Existing run
records continue to point to the exact version used.

