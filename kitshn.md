# kitshn

This repository deploys with [kitshn 2](https://kit.yarden-zamir.com).

- `kitshn.config.ts` names the app and its deploys: a Compose app on a machine labelled `docker`. `container/Caddyfile` serves the built `site/` on the kitshn socket.
- `.github/workflows/kitshn.yml` calls `kitshn2-deploy.yml`. It signs in to kitshn with GitHub OIDC, so the repo needs no deploy secrets.
- A push to `main` deploys `prod` at `free-oracle-vps.yarden-zamir.com`. Each pull request deploys a `pr-<number>` preview at `free-oracle-vps-pr-<number>.yarden-zamir.com`, and kitshn removes it when the pull request closes.
