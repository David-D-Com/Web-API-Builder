Local secrets for this workspace live here.

Recommended file:
- `.local-secrets/.env`

Why this exists:
- easier for local scripts and the builder to read than Windows Credential Manager
- stays out of the tracked repo because `.gitignore` excludes the real secret files

Expected format:
```env
FRONIUS_USERNAME=you@example.com
FRONIUS_PASSWORD=your-password
SOLIS_USERNAME=you@example.com
SOLIS_PASSWORD=your-password
```

Notes:
- values here are only for local development
- explicit function args and current process environment vars should still be able to override them
- do not commit the real `.env` file
