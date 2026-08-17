# Publishing this handoff as a public GitHub repository

The intended repository name is:

```text
danielkope/scheiber-can-analysis-nmea2000
```

## One-command publisher

From the project checkout, run:

```bash
./scripts/publish_public_repo.sh
```

The script verifies the current branch, GitHub CLI authentication, existing remotes, public visibility, and the resulting default branch. It refuses to overwrite a mismatched `origin`.

## GitHub CLI method

From the directory that contains this project:

```bash
gh auth status
gh repo create danielkope/scheiber-can-analysis-nmea2000 \
  --public \
  --description "Scheiber proprietary CAN reverse engineering, Raspberry Pi/SH-C30A capture workflow, and proposed NMEA 2000 mapping" \
  --source . \
  --remote origin \
  --push
```

## Web plus Git method

1. Create a new public repository named `scheiber-can-analysis-nmea2000` under the `danielkope` account.
2. Do not initialize it with another README, license, or `.gitignore` because those files are already present here.
3. From this project directory, run:

```bash
git remote add origin https://github.com/danielkope/scheiber-can-analysis-nmea2000.git
git branch -M main
git push -u origin main
```

## Recommended repository settings

- Visibility: Public.
- Default branch: `main`.
- Enable Issues for validation findings and new labelled captures.
- Protect `main` after the first push and require the included test workflow.
- Keep control/transmit code disabled by default. Accept only receive-only decoder changes until marine-electrical safety behavior is independently validated.

## Suggested first release

Tag the verified handoff as `v1.0.0` and attach:

- `Scheiber_CAN_Engineering_Report_v1.0.pdf`
- `Scheiber_CAN_Analysis_for_NMEA2000_v1.0.zip`
- the original candump log, or a link to the copy under `data/raw/`

Before publishing any future capture, calculate and record its SHA-256 hash and remove unrelated personal or navigation data.
