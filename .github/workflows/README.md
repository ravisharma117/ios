# iOS simulator build on GitHub Actions

`ios-build.yml` builds the app for the **iOS Simulator** on a GitHub-hosted macOS runner and uploads the
compiled `.app` (zipped) as an artifact. No Mac, no Apple Developer account, no secrets are required.

Files: `.github/workflows/ios-build.yml` (the workflow) and `.github/scripts/inspect_project.py` (finds the
workspace, scheme and Firebase file location at run time, so nothing is hardcoded in the YAML).

These files belong to the **iOS repo** (`src/ios`, remote `github.com/ravisharma117/ios`), because GitHub only
reads workflows from the root of the repository it hosts.

## Run it

- **By hand:** GitHub repo > **Actions** > **iOS Build (Simulator)** > **Run workflow**. Choose the branch and,
  if you want, a configuration or Xcode version. The first time on a fork you may have to click
  *I understand my workflows, go ahead and enable them*.
- **Automatically:** every push to `main` or `master` (the repo's default branch is `master`). Pushes that only
  change Markdown files, `LICENSE` or issue templates are skipped. A newer push cancels a build still running
  on the same branch.

Inputs (all optional): `configuration` (`Release` default, or `Debug`), `xcode_version` (default 16.4),
`workspace`, `scheme` (empty = detected). The build is always arm64 (see Limitations).

`Release` uses `prod.xcconfig` (the Geia test server over TLS); `Debug` uses `devel.xcconfig` (`127.0.0.1:6060`,
which a cloud simulator cannot reach), so `Release` is the useful default.

## Get the `.app`

1. Open the finished run (Actions > the run).
2. Scroll to **Artifacts** at the bottom of the Summary page.
3. Download `Tinodios-Release-iphonesimulator.zip`. Unzip it to get `Tinodios.app`.

`build-logs` (pod install and xcodebuild logs) is next to it; on failure `build-xcresult` is added. The job
summary lists the bundle ID, version, architectures and, on failure, the compiler errors. Artifacts are kept
14 days.

## What the workflow does

1. Checks out the repo with full history (`Scripts/set_build_number.sh` counts commits and reads tags).
2. Selects Xcode 16.4 on `macos-15` (pinned, not `macos-latest`).
3. Detects the workspace (`Tinodios.xcworkspace`) and shared application scheme (`Tinodios`).
4. Runs `pod install` (CocoaPods is the only dependency manager; `Podfile.lock` pins all versions, cached by
   lock-file hash, retried on download failures).
5. Provides `GoogleService-Info.plist`, which is gitignored but required by the target (see below).
6. Runs `xcodebuild build` for `generic/platform=iOS Simulator` with `CODE_SIGNING_ALLOWED=NO`.
7. Verifies the `.app` (architectures, bundle ID, app extension), zips it with `ditto`, uploads it.

All third-party actions are the official `actions/*` ones, pinned to commit SHAs.

## Optional secret: real Firebase config

Without it, the workflow generates a placeholder `GoogleService-Info.plist` so the build succeeds; push
notifications, analytics and crash reporting then do nothing in that build. To use the real file, add a
repository secret **`GOOGLE_SERVICE_INFO_PLIST_BASE64`** (Settings > Secrets and variables > Actions) holding
the file base64-encoded, for example in PowerShell:
`[Convert]::ToBase64String([IO.File]::ReadAllBytes("GoogleService-Info.plist"))`. The workflow never prints it.

## Limitations

- **A simulator `.app` runs only in an iOS Simulator on a Mac**, or in a hosted-simulator service that accepts a
  zipped simulator `.app`. It cannot be installed on an iPhone, TestFlight or the App Store. That needs signing
  with an Apple Developer account and a separate archive/IPA workflow, which is not part of this.
- **Not run on a real runner from this machine.** The YAML, the shell steps and the detection script were
  checked locally (parse, `actionlint`, `bash -n`, script run against the repo), but the first real run happens
  on GitHub. The project was last upgraded with Xcode 15.3 and `macos-15` only has Xcode 16.0+, so the first run
  may show new compiler errors that need a fix in the app.
- **No code signing means no entitlements.** `BaseDb.swift` force-unwraps the App Group container
  (`group.com.geia.messaging.db`). If the unsigned build crashes at launch in the simulator for that reason,
  build with ad-hoc signing (`CODE_SIGN_IDENTITY=-`, `CODE_SIGNING_ALLOWED=YES`) instead.
- **Placeholder Firebase config** (see above) unless the secret is set.
- **Version number:** `Scripts/set_build_number.sh` takes the version from the latest git tag and the build
  number from the commit count. The repo has no tags, so the marketing version in CI may be empty or odd. This
  does not affect a simulator build.
- **UI tests are not run;** the workflow only builds.
- **arm64 simulators only.** The `.app` runs on Apple-silicon Macs' simulators and in hosted services that run
  ARM simulators (Appetize.io recommends ARM builds). It does not run on an Intel Mac's simulator: the x86_64
  slice cannot link, because `Tinodios/CallViewController.swift` (`setupViews`) uses `RTCEAGLVideoView` on
  non-arm64 and the WebRTC-lib 139 binary no longer contains that class. Fixing it means changing that code to
  `RTCMTLVideoView` on simulators; that has not been done. To retry x86_64, set `SIMULATOR_ARCHS` in the
  workflow.
- **Time and cost:** the first run measured about 5 minutes of job time (pod install about 1.5 minutes, the
  rest build), plus up to roughly 5 minutes waiting for a macOS runner, which is not billed. A cold pod cache
  adds the 260 MB MobileVLCKit download. macOS minutes are free on public repositories; on private ones they
  draw from the plan's monthly dollar allowance at a much higher per-minute rate than Linux.
- **Podfile.lock:** the runner's CocoaPods (1.17) is newer than the one that wrote the lock file (1.15.2), so
  `pod install` may rewrite it. The workflow reports what changed as a warning and in `podfile-lock.diff` in
  the `build-logs` artifact; it never fails the build for it.
- **Runner pinning:** `macos-15` and Xcode 16.4 are fixed on purpose. Update `runs-on` and
  `DEFAULT_XCODE_VERSION` when GitHub retires that image (`macos-14` was retired on 2 November 2026).
