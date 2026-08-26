# Issue Tracker: GitHub

Issues and specifications for this repository live as GitHub Issues. Use the `gh` CLI for operations and infer the repository from `git remote -v`.

## Operations

- Create: `gh issue create --title "..." --body "..."`
- Read: `gh issue view <number> --comments`
- List: `gh issue list --state open --json number,title,body,labels,comments`
- Comment: `gh issue comment <number> --body "..."`
- Add or remove labels: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`
- Close: `gh issue close <number> --comment "..."`

Use a platform-native temporary body file for long issue text when shell quoting would be fragile. Never place secrets in an issue body, comment, command line, or attachment.

## Pull requests as a triage surface

Pull requests are not a request surface. Do not place external pull requests into the issue triage state machine unless this document is explicitly changed.

GitHub shares one number space across issues and pull requests. Resolve ambiguous references with `gh pr view <number>` and fall back to `gh issue view <number>`.

## Skill terminology

When a skill says "publish to the issue tracker," create a GitHub issue. When it says "fetch the relevant ticket," use `gh issue view <number> --comments`.

## Wayfinding

Use one issue labelled `wayfinder:map` as the map and GitHub sub-issues as child tickets. Prefer native GitHub issue dependencies for blocking edges. If sub-issues or dependencies are unavailable, use a task list in the map and a `Blocked by: #<number>` line in each child.

Claim work by assigning the issue to the active developer. Resolve it by adding the durable result, closing the issue, and updating the map's decisions.
