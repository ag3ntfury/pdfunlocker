# Field-by-field regression tests

This directory contains independent pytest modules for each active profile field family. The tests are intentionally isolated from the older broad profile tests so a future validator change can be traced to one field.

## Coverage

- Personal identity: TITLE, FIRST_NAME, MIDDLE_NAME, LAST_NAME, MOTHER_NAME, DOB.
- Contact: MOBILE, EMAIL, PINCODE.
- Identity and tax: PAN, AADHAAR, TAN, GSTIN.
- Banking: BANK_NAME, IFSC, CIF, CUSTOMER_ID, ACCOUNT_NUMBER, CARD_NO, bank groups 1200-1699.
- Employment and policy: INCORPORATION_DATE, EMPLOYEE_ID, UAN, PPO_NUMBER, PRAN, POLICY_NUMBER.
- Cross-field contracts: permanent field IDs, repeatable profile values, empty optional values, normalization requirements, and bank field cardinality/persistence metadata.

Each field module includes valid and invalid inputs, boundary/format cases, and normalization assertions where normalization is part of the contract. Repeated-value tests use `_01`, `_02`, and higher suffixes. Bank tests cover all six bank slots and multiple bank groups.

## Run

From the repository root, with the project's dependencies installed:

```bash
python -m pytest -q tests/fields
```

Run only one field when changing a validator, for example:

```bash
python -m pytest -q tests/fields/test_aadhaar.py
python -m pytest -q tests/fields/test_gstin.py
python -m pytest -q tests/fields/test_bank_groups.py tests/fields/test_bank_group_persistence.py
```

Then run the complete regression suite:

```bash
python -m pytest -q
```

The Aadhaar value in these tests is a synthetic checksum-valid test vector, not a real person's identifier. Card numbers are public test numbers used only to test formatting and Luhn validation; the existing card-crypto tests cover encryption and storage.
