# Changelog

## [0.2.0](https://github.com/damien-robotsix/robotsix-linkedin/compare/v0.1.0...v0.2.0) (2026-10-29)


### Features

* Add deploy compose with config-target label and wire settings loading from config file (20260831T081206Z-add-deploy-compose-with-config-target-la-2fb3) ([#5](https://github.com/damien-robotsix/robotsix-linkedin/issues/5)) ([6bf2c41](https://github.com/damien-robotsix/robotsix-linkedin/commit/6bf2c4125dc687b5430a9ceb935f2dd03781981e))
* Add organization/company-read endpoint(s) to expose LinkedIn Company Page data (20260901T204405Z-add-organization-company-read-endpoint-s-ffbe) ([#13](https://github.com/damien-robotsix/robotsix-linkedin/issues/13)) ([98c5c21](https://github.com/damien-robotsix/robotsix-linkedin/commit/98c5c210c665cea059d8de5c91fabb737729c2a3))
* Adopt fleet structured logging in robotsix-linkedin (currently no logging setup) (20260925T171646Z-adopt-fleet-structured-logging-in-robots-053b) ([#23](https://github.com/damien-robotsix/robotsix-linkedin/issues/23)) ([40e80b4](https://github.com/damien-robotsix/robotsix-linkedin/commit/40e80b4ff9e8abd393d7ad6234fc510eb40d67c7))


### Bug Fixes

* Dockerfile: install from uv.lock (uv sync --frozen) instead of hand-pinned `pip install <pkg> @ git+…[@sha](https://github.com/sha)` lines (20261013T003347Z-dockerfile-install-from-uv-lock-uv-sync-c5bb) ([#27](https://github.com/damien-robotsix/robotsix-linkedin/issues/27)) ([3942b81](https://github.com/damien-robotsix/robotsix-linkedin/commit/3942b8104a0a1fcf40b594d3e685e107feb769a2))
* **docker:** install robotsix-http at the rev pyproject/uv.lock pin (952d984b, adds robotsix_http.oauth) ([#26](https://github.com/damien-robotsix/robotsix-linkedin/issues/26)) ([ca8b414](https://github.com/damien-robotsix/robotsix-linkedin/commit/ca8b414d4444e19281f72172574c65c042d7dff0))
* Fix refresh_access_token sending SecretStr placeholders as client credentials, and add refresh tests (20261022T153025Z-fix-refresh-access-token-sending-secrets-d107) ([#46](https://github.com/damien-robotsix/robotsix-linkedin/issues/46)) ([b9cdfaf](https://github.com/damien-robotsix/robotsix-linkedin/commit/b9cdfafe8ae2ebc2a304c022f35d9fa1aa161919))
* Harden the OAuth state check: reject empty state and make state single-use (20261022T153025Z-harden-the-oauth-state-check-reject-empt-6885) ([#47](https://github.com/damien-robotsix/robotsix-linkedin/issues/47)) ([8836281](https://github.com/damien-robotsix/robotsix-linkedin/commit/88362814f717dfb40efb0329018ae59d78c60416))
* Rename robotsix-linkedin periodic presence files to &lt;name&gt;.yaml so the loader discovers them (20261022T150536Z-rename-robotsix-linkedin-periodic-presen-39aa) ([#45](https://github.com/damien-robotsix/robotsix-linkedin/issues/45)) ([a7accf2](https://github.com/damien-robotsix/robotsix-linkedin/commit/a7accf29df56d655cb8227d0f346b5ec32813fef))


### Documentation

* AGENT.md: CI conventions — Every GitHub Actions job declares its own `permissions:` block with the minimum… (20261023T233550Z-agent-md-ci-conventions-every-github-act-1367) ([#57](https://github.com/damien-robotsix/robotsix-linkedin/issues/57)) ([9991501](https://github.com/damien-robotsix/robotsix-linkedin/commit/9991501d3a6c156cd050c84f1ab91e8fc869ae45))
* CI: verify and document least-privilege permission model in ci.yml (20261023T233602Z-ci-verify-and-document-least-privilege-p-c16f) ([#60](https://github.com/damien-robotsix/robotsix-linkedin/issues/60)) ([85013c0](https://github.com/damien-robotsix/robotsix-linkedin/commit/85013c0e78fd9e2721c5cc1f5c2b0cd9751336dc))
* health scan: 2 findings (2026-10-22) (20261022T160832Z-health-scan-2-findings-2026-10-22-07d2) ([#56](https://github.com/damien-robotsix/robotsix-linkedin/issues/56)) ([5c52aec](https://github.com/damien-robotsix/robotsix-linkedin/commit/5c52aec026ec2fce18b292d57c6450e7d48c5aab))
