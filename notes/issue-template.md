# Issue authoring template

Use this Markdown template when creating issues through the GitHub API, CLI, or
another automation path. It mirrors the repository's interactive GitHub issue
form in `.github/ISSUE_TEMPLATE/work-item.yml`.

```markdown
## Type

Feature | Improvement | Bug | Research / spike | Documentation | Maintenance

## Description

Describe the desired outcome clearly and concisely.

## Motivation / context

Explain the problem, user need, or technical constraint behind this work.

## Proposed work

Outline a likely implementation approach when one is already known.

## Completion criteria

- [ ] List observable conditions that must be true before this issue can close.
- [ ] Include failure and recovery behavior where applicable.
- [ ] Require automated or repeatable validation for the change.

## Validation

Explain how the completion criteria will be verified: tests, hardware matrix,
manual checks, logs, or measurements.

## Out of scope

Record related work that this issue deliberately does not include.

## Dependencies / notes

Link prerequisites, related issues, design notes, or external constraints.
```
