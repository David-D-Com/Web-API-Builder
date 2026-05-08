# Project Guidelines

## Repo goals

- Build this as a proper Python module that can be imported and reused elsewhere.
- Favor portability in the core package.
- Keep platform-specific helpers outside the reusable module when practical.
- Treat credential handling as a first-class security concern.

## Before building a new category of functionality

- First, quickly check whether a mature existing library already solves the problem.
- Prefer well-maintained libraries for common concerns like:
  credential storage, HTTP auth helpers, CLI scaffolding, packaging, retries, parsing, and testing.
- Only implement custom code when the need is Solis-specific, the dependency would be too heavy, or the library is a poor fit.
- If we choose custom code over a library, document why.

## Python packaging expectations

- Use a `src/` layout.
- Keep importable code inside the package, not in top-level scripts.
- Define metadata and entry points in `pyproject.toml`.
- Expose a small clean public API from `__init__.py`.
- Keep CLI code separate from business logic.

## Security expectations

- Do not hardcode user credentials in package code, tests, docs, or examples.
- Avoid printing secrets in logs, exceptions, or debug output.
- Store credentials using OS-native or well-supported secure storage when possible.
- Keep the core module credential-source agnostic.
- Treat captured HAR files and reverse-engineered details as sensitive implementation data.

## Maintainability

- Prefer small focused modules over large all-in-one scripts.
- Keep platform-specific helpers isolated.
- Add smoke tests for real integration paths when possible.
- Make docs good enough that the package can be installed and used without reading the source first.
