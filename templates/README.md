# PDF Unlocker Templates

Current template release: **Alpha v1**

## Profile Template

File: `profile/default_profile_template.yml`

The profile template defines exactly 14 permanent fields.

- Single-value fields use their field ID directly.
- Multiple-value fields use alphabetic suffixes, such as `1008A` and `1008B`.
- Rules reference the parent field ID, not an individual value suffix.
- Date of birth is stored as `DDMMYYYY`.
- Personal profile values belong in private profile data, never in the public rules repository.

## Rule Template

File: `rules/default_rule_template.yml`

Rules are reusable password-pattern definitions.

- Rule IDs are unique five-digit strings.
- Rules reference profile field IDs.
- Supported slice modes: `first`, `last`, and `full`.
- `count` is used with `first` and `last`.
- Supported transformations: `lower`, `upper`, and `raw`.
- Rule status is `active` or `inactive`.
- Rules contain no personal profile values.

## Alpha v1 Compatibility

Alpha v1 is the baseline schema for profiles and rules.

Changes to field IDs, field definitions, date storage, rule structure, or supported operations must be reviewed before introducing a future template version.

Existing rule files must remain compatible with this schema. Template changes do not automatically change the status or contents of existing rules.

Profile data is private and must not be committed to the public rules repository.
