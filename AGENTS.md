# AI Agent Guidelines (`FaserF/ha-rclone-backup`)

- Follow Python 3.14, Ruff (`ruff format --check`, `ruff check`), strict `mypy` (`mypy custom_components/rclone_backup`), and `pytest tests/` checks before pushing.
- Never commit credentials, tokens, or live tailnet URLs into tests or fixtures.
- Preserve strict async I/O (`aiohttp`), avoid `raise e` (`raise ... from err` or `raise`), and keep modules concise (`<= 600` lines).
