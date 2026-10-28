# PDF Unlocker Rules

Rules describe how profile fields are combined into candidate passwords. Use
these rules only for PDFs you own or are authorized to access.

## Rule lifecycle

- `pdfunlocker rules add` creates the next available five-digit rule number.
- New rules default to the `capitalize`, `upper`, and `lower` case-transform variants.
- `pdfunlocker rules modify RULE` changes rule metadata, priority, and optionally
  field components. Existing transform settings are preserved.
- `pdfunlocker rules show RULE` displays one rule identifier plus its metadata,
  field combination, and transform information.
- `pdfunlocker rules list` lists active rules in execution order.
- `pdfunlocker rules remove RULE` asks for confirmation and archives the rule;
  it does not permanently delete it.

Archived rule files are not loaded as active rules. Their numbers and readable
IDs remain reserved to avoid accidental reuse.

## Priorities

Priorities are case-insensitive on input and stored in uppercase:

- `A1` through `A10`, then `B1` through `B10`, continuing through `W10`.
- `X1`, `X2`, `X3`, and onward. `X` priorities are not capped at `X99999`.
- `Z` means unapproved. It remains visible in rule-management output but is
  excluded from password attempts and profile rule evaluation.

Active non-`Z` priorities must be unique. `Z` can be assigned to multiple rules.
Canonical forms are required: for example, `A01`, `X0`, `X01`, and `Z1` are
invalid.

## Rule file format

Active rules are stored as `rules/ruleNNNNN.yml`. New rules use the field-based
schema:

```yaml
rule:
  number: "00001"
  id: "00001"
  name: "Example"
  category: "profile"
  priority: "Z"
pattern:
  fields:
    - field_id: "001"
      slice:
        mode: "full"
transform:
  case: "raw"
```

A field slice may use `full`, `first` with a character count, or `last` with a
character count. Existing rules using the legacy `pattern.components` schema
remain parseable. Existing YAML files using `transform.cases` remain supported;
the add workflow offers the default case-transform variants.

## Safety and validation

- Rule filenames must match their five-digit rule number.
- Rule IDs must be non-empty and contain only letters, digits, `_`, or `-`.
- A rule file is created exclusively; an existing file is never overwritten.
- Malformed rules fail validation rather than being silently accepted.
- Rule-number and ID allocation considers archived rule files when readable.
