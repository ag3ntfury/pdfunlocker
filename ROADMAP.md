# PDF Unlocker Roadmap

This roadmap defines the planned development stages for PDF Unlocker.

## Phase 1 — CLI Foundation

- Establish the Python package structure.
- Implement the main CLI entry point.
- Add version information.
- Add clean command handling.
- Handle Ctrl+C and CLI errors cleanly.
- Implement the init command.
- Implement basic configuration management.

## Phase 2 — Profile Management

- Define the profile format.
- Support multiple user profiles.
- Support multiple bank accounts per profile.
- Validate profile fields.
- Ignore empty fields.
- Add profile add command.
- Add profile list command.
- Add profile show command.
- Keep real profile data outside Git.

## Phase 3 — SQLite Database

- Create the SQLite database layer.
- Create the PDF processing table.
- Store SHA-256 hashes.
- Store processing status.
- Store profile and bank information used.
- Store password pattern identifiers.
- Store attempt counts.
- Store timestamps and error information.
- Prevent unnecessary reprocessing.

## Phase 4 — PDF Scanner

- Scan the configured inbox directory.
- Detect PDF files.
- Calculate SHA-256 hashes.
- Register new files in SQLite.
- Detect previously processed files.
- Support safe movement of processed originals.
- Add the scan command.

## Phase 5 — QPDF Integration

- Integrate QPDF as the PDF processing backend.
- Detect encrypted PDFs.
- Attempt configured password candidates.
- Verify successful decryption.
- Create unlocked PDF files.
- Handle invalid, corrupted, and unsupported PDFs.
- Prevent passwords from appearing in logs or process arguments.
- Use private temporary password files for QPDF operations.
- Restrict temporary password-file permissions.
- Guarantee temporary password-file cleanup on every exit path.

## Phase 6 — Password Candidate Engine

- Build the controlled candidate-generation engine.
- Generate candidates from profile information.
- Generate bank-specific candidates.
- Support numbered bank priority.
- Support configured combinations.
- Deduplicate candidates.
- Add configurable attempt limits.
- Keep candidate generation separate from PDF processing.

## Phase 7 — Password Learning

- Record successful password patterns.
- Store pattern identifiers instead of plaintext passwords where possible.
- Prioritize previously successful patterns.
- Associate successful patterns with relevant banks or document sources.
- Improve candidate ordering based on previous results.

## Phase 8 — Watch Mode

- Monitor the inbox directory.
- Detect newly added PDFs.
- Automatically process new files.
- Support configurable intervals.
- Support hourly processing.
- Support daily processing.
- Prevent duplicate processing.

## Phase 9 — Linux Support

- Test on Ubuntu/Linux.
- Verify filesystem handling.
- Verify QPDF integration.
- Verify SQLite operation.
- Document Linux installation.
- Keep the application portable between Termux and Linux.

## Phase 10 — Testing

- Add unit tests.
- Add profile validation tests.
- Add database tests.
- Add scanner tests.
- Add PDF engine tests.
- Add candidate-generation tests.
- Add duplicate-detection tests.
- Add integration tests.
- Test failure and recovery scenarios.
- Verify passwords never appear in QPDF subprocess arguments.
- Verify temporary password-file permissions and cleanup after success, failure, and timeout.

## Phase 11 — Documentation

- Complete README documentation.
- Document installation.
- Document configuration.
- Document profile format.
- Document CLI commands.
- Document database behavior.
- Document security considerations.
- Document Linux setup.

## Phase 12 — Public Release

- Review the complete source tree.
- Remove temporary development files.
- Verify .gitignore rules.
- Ensure no personal or banking information is committed.
- Review security-sensitive code.
- Review documentation.
- Prepare the first public GitHub release.
- Add a license.
- Create release documentation.

## Current Priority

**P1 — Prevent QPDF password disclosure.**

This security fix takes precedence over further password candidate-engine work.

Immediate order:

1. Replace command-line password arguments with private temporary password files.
2. Restrict temporary file permissions to the owning user.
3. Guarantee cleanup after success, failure, and timeout.
4. Add regression tests proving passwords never enter QPDF argument lists.
5. Run the complete test suite and CI checks.

After this P1 fix, continue with the remaining QPDF integration work, then the controlled password candidate engine.

The existing profile priority order, sequential profile fallback, candidate ordering, and configured attempt pacing must remain unchanged by this security fix.
