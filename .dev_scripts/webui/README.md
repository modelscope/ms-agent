# WebUI build tools

These tools prepare the WebUI resources included in MS-Agent packages and check
packages and images before release. Run the commands below from the repository
root with Python 3.12+, Node.js 22.22.0+, pnpm 10.17.1 and uv installed.

## Build a package

```bash
python .dev_scripts/webui/check_webui_release.py
python .dev_scripts/webui/prepare_webui.py
uv build --python 3.12
uvx --from twine==6.2.0 twine check dist/*.whl dist/*.tar.gz
```

The package also includes a fixed models.dev snapshot, its SHA256 manifest and
upstream MIT license. To refresh it during release preparation, use
`python .dev_scripts/webui/prepare_webui.py --update-model-catalog`. Without that
option, preparation and wheel/sdist builds only validate the bundled data and
never fetch it. Images inherit the same data from the wheel and default to local catalog data.
Source WebUI startup can refresh its separate SDK HOME cache; runtime updates never
rewrite the snapshot packaged by this build. The SDK query API is `ms_agent.llm.model_catalog.get_model`.
For an offline update, run `python .dev_scripts/update_model_catalog.py --input
FILE --fetched-at ORIGINAL_ISO_TIMESTAMP`; `--check` verifies the fixed bundle.
The update script normalizes the final newline before computing the snapshot
hash, so repository text-format hooks cannot invalidate the manifest.

Preparation installs locked frontend dependencies, builds CSS and frontend
output, then records file hashes and the SDK version/commit in
`webui/RESOURCE-MANIFEST.json`. Use `--skip-build` to reuse an unchanged, validated
frontend build. When preparing a source tree without Git metadata, pass the full
SDK commit with `--sdk-sha`.

The wheel includes WebUI source and prebuilt frontend output. The sdist contains
the same resources and this build helper, so rebuilding a wheel from the sdist
does not need Node.js or pnpm. SDK installation from an unprepared source tree
or Git URL also works without frontend tools: its wheel carries WebUI source,
and `ms-agent ui` builds the frontend in a writable cache on first use.
Editable SDK installation builds in the checkout when first started.
Published packages must pass the release checker, which requires prebuilt
resources. An existing but invalid release manifest is always an error.

## Package inputs

The image installs SDK dependencies into `/opt/venv` and shell utility packages
into system Python. These image-only packages are declared in `docker/webui-shell.in`;
regenerate their lock with the command recorded in `docker/webui-shell.txt`.
Package CI copies that lock to `shell-requirements.txt` alongside the wheel and
service dependency export. Both locks are covered by `release.json` and
`SHA256SUMS`. Image checks verify that shell package installation leaves the SDK
environment unchanged.

Backend code and data are collected from `webui/backend/app/`. Frontend source
files use the same discovery rules as build validation; generated outputs come
from the frontend build manifest. New source files are included automatically.
Hidden local files and Python caches are excluded, and dependency directories
are outside the selected source directories. No Git metadata is needed to
build a wheel from an sdist.

`setup.py` loads [`webui_packaging.py`](webui_packaging.py) directly, and
`MANIFEST.in` includes the helper in the sdist. `.gitignore` controls Git tracking;
package contents are controlled separately by the build rules.

## Validation tools

| File | Purpose |
| --- | --- |
| `prepare_webui.py` | Build and record WebUI package resources |
| `check_webui_release.py` | Check version, tag and dependencies; validate wheel/sdist and write release checksums |
| `check_webui_install.py` | Exercise an installed wheel outside the checkout, including pages, CSS, streaming, cache reuse and shutdown |
| `check_webui_image.py` | Exercise a built Docker image and record its identity |
| `release_artifacts.py` | Find original workflow artifacts and save/restore the exact tested image |
| `webui_smoke.py` | Shared HTTP checks used by package and image validation |
| `publish_webui_release.py` | Publish already validated artifacts and reject conflicting existing versions |
| `development_version.py` | Assign a development version in an isolated package source without changing the working checkout |
| `oss_distribution.py` | Deliver a verified development wheel and record its matching published image using runner-local settings |

The installed-package check needs the Python interpreter from a fresh wheel
environment. Run it from outside the checkout, passing its absolute script path
and `--logs` with a directory for test logs. Image validation uses test containers
and volumes and removes them when finished. Neither check calls a real model.

For exact automated commands, see the [package workflow](../../.github/workflows/webui-check.yaml)
and [image workflow](../../.github/workflows/webui-image.yaml).

## Workflow responsibilities

- `webui-check.yaml` runs package and application checks on GitHub-hosted runners.
- `webui-image.yaml` is the manual image entry point and the release build dependency.
- `webui-image-runner.yaml` runs image work on the dedicated `ms-agent-image` runner.
- `publish.yaml` publishes PyPI on a GitHub-hosted runner after image validation,
  then asks the image runner to restore and publish the tested image.

Manual package and image runs use `X.Y.Z.devN`, where `N` is the GitHub run ID.
The optional `dev_base_version` input selects `X.Y.Z`; leaving it blank uses the
SDK version without its RC suffix. Retries keep the original run ID and artifacts.
The version is applied to the package source copy and its backend lock entry,
so the wheel metadata and installed SDK report the same version.

In the image workflow, `push_dev=false` builds and checks the package and image.
Selecting `push_dev=true` also delivers the wheel and publishes the matching image
under the same development version. Release tags keep the existing release/RC
flow, and the PyPI publisher rejects development versions.

Business delivery uses an installed `ossutil` and the encrypted `ms-agent` profile
in runner-local `credentials.ini`, with a `destination.json` containing the target
`uri`. Set `MS_AGENT_OSS_ROOT` to this directory. Keep both files
private and outside the checkout. Upload only the verified wheel as public-read;
delivery manifests remain private and the workflow does not change Bucket ACLs.
To use OSS transfer acceleration, enable it for the bucket and set `endpoint`
in the runner-local `destination.json` to `https://oss-accelerate.aliyuncs.com`.
Keep the signing region set to the bucket's region. Uploads and authenticated
verification downloads use this endpoint; published download URLs keep their
regional domain. Acceleration traffic is billed separately by OSS.
Large wheels use resumable parallel upload to a private staging object, followed
by a server-side copy that rejects overwriting an existing final object. The
temporary object is then removed. Credentials need object upload, download, ACL,
multipart upload and staging-object deletion permissions within the target prefix.

The delivery helper checks uploaded bytes and anonymous downloads before recording
success. A versioned delivery manifest and `channels/dev/latest.json` are written
after the matching image is published. Older retries cannot replace a newer latest
record. Download URLs are recorded in the runner-local `deliveries/` directory;
they are not printed in workflow logs or included in workflow artifacts.

`release_artifacts.py` saves images by immutable image ID, checks the archive
checksum before loading, and finds the original artifacts when a job is retried.
`publish_webui_release.py` skips already published identical files/images and
rejects conflicting content. Retrying failed jobs reuses the workflow artifacts;
do not delete them or rebuild a version already published to PyPI.

The image jobs receive no PyPI token. Their registry credentials come from a
runner-local Docker configuration, selected by `MS_AGENT_ACR_AUTH_FILE`.
Each registry operation makes a temporary, registry-scoped copy and
removes it afterward. PR checks do not run on the image runner.

Set these paths in repository Actions variables or the runner service environment:

| Variable | Required for | Value |
| --- | --- | --- |
| `MS_AGENT_ACR_AUTH_FILE` | ACR checks and image publication | Absolute path to a readable Docker credential file |
| `MS_AGENT_OSS_ROOT` | Business wheel delivery | Absolute path to the private OSS configuration directory |

Repository variables take precedence over the runner environment. There are no
default paths; a missing setting stops the relevant job before building or
publishing. Build-only runs do not require publication credentials. When running
the OSS helper directly, `--config-root` can explicitly override `MS_AGENT_OSS_ROOT`.
Keep credential contents and download addresses out of repository variables.
