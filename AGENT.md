# Agent conventions for robotsix-linkedin

## CI conventions

- **Least-privilege job permissions:** Every GitHub Actions job declares its
  own `permissions:` block with the minimum scopes it needs (default
  `contents: read`); never rely on the repository default `GITHUB_TOKEN`
  scope. Grant write scopes only on the specific job that requires them,
  with an inline comment naming the reason (e.g.
  `packages: write  # push the image to GHCR`).
