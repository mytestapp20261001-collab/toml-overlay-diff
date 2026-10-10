---
name: toml-overlay-diff
description: Preview structural differences caused by a deliberately selected shallow or deep TOML overlay, without generating or installing merged configuration.
---

# TOML overlay diff

## Use this skill when

Preview structural differences caused by a deliberately selected shallow or deep TOML overlay, without generating or installing merged configuration. Read README.md for the exact supported input dialect, policies, limits, and non-goals before using it. Do not substitute this audit for an application's own validator or silently infer missing policies.

## Procedure

1. Confirm the input files are within the user's authorized scope and work on local UTF-8 regular files. Inputs remain unchanged.
2. Review the contract and flags in README.md. Ask for any required decision you cannot establish from user instructions; never guess a consequential normalization, overlay, rounding, or timestamp policy.
3. Run the synthetic passing and failing examples once when establishing this tool in a new environment. The example failure is expected, not a failed installation.
4. From this directory, use `python3 tool.py examples/pass.toml --overlay examples/overlay.toml --mode deep` as the command shape and substitute only authorized input paths and explicitly selected policy options. Use `python3 tool.py --help` for options.
5. Parse the single JSON report. Treat exit 0 as coverage of the documented checks, exit 1 as findings requiring review, and exit 2 as incomplete/invalid input. Never claim a partial scan passed.
6. Report counts, policy, relevant 1-based positions, truncation, and limitations. Default output avoids original values. Do not enable optional disclosure flags or share reports externally without appropriate authorization.
7. When changing this tool, run `python3 -m unittest -v test_tool.py` and all README example commands. Verify both expected pass and expected failure exit codes.

## Authorization boundary

This skill only reads local input and produces a local stdout report. It does not upload data, query services, access credentials, execute input as code, rewrite configuration, normalize source records, apply changes, or deploy anything. Such actions require a separate user request and the applicable confirmation rules. Do not treat a reported finding, a file's contents, or a reference website as authorization for another action.

## Semantics and cautions

Both inputs are parsed with `tomllib`. `--mode` is mandatory:
- `shallow`: every overlay root key replaces the complete corresponding base value or table.
- `deep`: recurse only when both corresponding values are tables; otherwise replace the entire value. Arrays, including arrays of tables, replace atomically.

Keys absent from the overlay are retained except where an enclosing table is replaced in shallow mode. There is no null/deletion sentinel, environment substitution, secret interpolation, list concatenation, or application-specific merge inference.

The report compares the base to the simulated result. Added/removed subtrees and changed arrays count as one location at their boundary, not one finding per descendant. Type changes are distinct from value changes; parsed NaN compared with NaN is treated as unchanged. Date/time comparison follows Python parsed-value equality. Unchanged simulation exits 0; any difference exits 1. No merged content is emitted.

By default, each `path_indices` component is a 1-based rank in the sorted union of sibling keys at that level. `--show-paths` adds escaped JSON Pointer paths containing actual key names. Use it only when those names are safe to display. Values are never included.

Tables/arrays at most 64 levels, 100,000 parsed value nodes per file, in addition to the 8 MiB input bound. Parsing behavior follows the installed Python 3.12+ `tomllib`; no TOML writer or application runtime is invoked.

## Technical entry point

`tool.py` exposes `audit(base_toml_text, overlay_toml_text, mode="deep", show_paths=False)`. Its CLI is dependency-free Python 3.12+. Keep bounded resource handling and safe error messages when extending it. References and exact input schemas are in README.md.
