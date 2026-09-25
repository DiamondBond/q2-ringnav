# Standard release procedure

Keep the proprietary stock ZIP local. Use the Python environment with `requirements.txt`
installed for these commands:

```sh
python3 tools/release.py package 'Q2 Firmware V1.32.zip' --out /tmp/q2-v33-release
python3 tools/test_release.py
# Create or update the release with both validated ZIPs and verify remote bytes.
python3 tools/release.py upload /tmp/q2-v33-release
# Same, then publish after verification.
python3 tools/release.py upload /tmp/q2-v33-release --publish
```

Packaging requires a fresh output directory, builds each variant twice, runs the shared MIPS
suite and asset checks on each build, and compares update.tar and ZIP bytes. It writes both
ZIPs, manifests, SHA256SUMS, release notes and source revision/hash. Normal is the default for
direct builds; a single direct build is never a release input. Upload revalidates both variants
and refuses stale, missing or changed artifacts and published releases. An upload/download
failure leaves the release unpublished; rerun upload to repair the draft. Packaging uses no
GitHub credentials or network. The [compact checklist](compact.md) is a device test guide,
not a release gate.
