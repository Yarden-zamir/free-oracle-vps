# free-oracle-vps

[![kitshn prod](https://img.shields.io/github/deployments/Yarden-zamir/free-oracle-vps/prod?label=kitshn%20%C2%B7%20prod&labelColor=2F3532&logo=data:image/svg%2Bxml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxNCAxNCI+PGcgZmlsbD0iI2ZmZiI+PHJlY3QgeD0iNiIgeT0iMS4yIiB3aWR0aD0iMiIgaGVpZ2h0PSIxLjYiIHJ4PSIwLjUiLz48cmVjdCB4PSIyLjIiIHk9IjMuNCIgd2lkdGg9IjkuNiIgaGVpZ2h0PSIxLjUiIHJ4PSIwLjc1Ii8+PHJlY3QgeD0iMyIgeT0iNS42IiB3aWR0aD0iOCIgaGVpZ2h0PSI2LjYiIHJ4PSIxLjYiLz48cmVjdCB4PSIwLjgiIHk9IjYuOCIgd2lkdGg9IjIuNCIgaGVpZ2h0PSIxLjQiIHJ4PSIwLjciLz48cmVjdCB4PSIxMC44IiB5PSI2LjgiIHdpZHRoPSIyLjQiIGhlaWdodD0iMS40IiByeD0iMC43Ii8+PC9nPjwvc3ZnPgo=)](https://free-oracle-vps.yarden-zamir.com)

Get a free Oracle Cloud ARM server: 4 cores, 24 GB RAM, 200 GB disk, $0 a month. One script sets it up with quotas and a budget alert that block surprise bills.

Guide: https://free-oracle-vps.yarden-zamir.com

## Quick start

Do the account steps in the guide first: sign up, pick the home region, turn on two-factor login. Then:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
uvx --from oci-cli oci setup bootstrap
uv run https://free-oracle-vps.yarden-zamir.com/oracle-free-server.py --plan
uv run https://free-oracle-vps.yarden-zamir.com/oracle-free-server.py
```

`--plan` shows what the script would do and changes nothing. Run `--help` for all options.

If you prefer a coding agent, use [agent-prompt.md](agent-prompt.md).

## Files

- `oracle-free-server.py`: the setup script, a uv script with its dependencies in the header.
- `agent-prompt.md`: the same setup as a prompt for a coding agent.
- `web/index.html`: the guide page. `build.py` embeds the script and the prompt into it and writes `site/`.
- `compose.yml`, `Dockerfile`, `container/Caddyfile`, `Caddyfile.j2`, `.kitshn.yaml`: the [KitSHn](https://github.com/Yarden-zamir/kitshn) deployment. A push to `main` deploys the site.

## Local preview

```sh
python3 build.py
python3 -m http.server --directory site
```

## License

MIT
