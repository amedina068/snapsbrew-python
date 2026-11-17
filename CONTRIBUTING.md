# Contributing

Thank you for your help. This file tells you how to set up the project, run the checks and send a change.

## Set up the project

1. Install [uv](https://docs.astral.sh/uv/).
2. Clone the repository.
3. Install the dependencies:

   ```bash
   uv sync
   ```

## Run the checks

Run all four checks before you send a change. CI runs the same checks on Python 3.10 to 3.14.

```bash
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format --check .
uv run mypy                # type check, strict mode
```

To run the tests on one Python version:

```bash
uv run --python 3.10 pytest
```

## Integration tests

The integration tests call a live Snapsbrew instance. They run only when these two variables are set. Otherwise pytest skips them.

```bash
SNAPSBREW_TEST_URL=https://snapsbrew.example.com \
SNAPSBREW_TEST_TOKEN=... \
uv run pytest -m integration
```

The integration tests are read-only, except for one preview call. A preview costs no credit.

> **CAUTION:** Do not put a token in a file of the repository. Do not paste a token in an issue or a pull request.

## Rules for code

- Keep the sync client and the async client the same. A change to one client needs the same change to the other client.
- Put shared logic in the functions at the top of `_client.py`, or in `_base.py`.
- Add a unit test with a mocked HTTP layer (respx) for each change of behavior.
- Do not add a dependency if the standard library can do the job.
- Do not add telemetry.

## Rules for text

Write docs, comments, error messages and commit messages in Simple English (ASD-STE100):

- Write short sentences. Use 20 words maximum in an instruction and 25 words maximum in a description.
- Use the active voice. Use the imperative for an instruction.
- Use one word for one meaning.
- Do not use contractions or semicolons.

## Send a change

1. Make a branch from `main`.
2. Make the change and run the checks.
3. Add a line to `CHANGELOG.md` under `Unreleased`.
4. Open a pull request. Fill in the template.
