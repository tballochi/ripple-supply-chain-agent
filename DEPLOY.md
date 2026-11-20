# Deploy the live demo (Streamlit Community Cloud, free)

The app needs no database server and no API key: the Relate store is a folder
in the repo (`data/ripple.relate`) opened read-only, and without a key the
agent runs in its deterministic rule-based mode.

## Steps

1. Push the repo to GitHub and make sure the **tests** workflow is green.
2. Open <https://share.streamlit.io> and sign in with GitHub.
3. Click **Create app**, then **Yup, I have an app**.
4. Fill in:
   - **Repository:** `tballochi/ripple-supply-chain-agent`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** pick a short subdomain, for example `ripple-supply-chain`
5. Click **Advanced settings**:
   - **Python version:** `3.13` (3.12 also works; both are tested).
   - **Secrets:** leave empty for the rule-based mode. To enable the LLM mode,
     paste one free key:
     ```toml
     GROQ_API_KEY = "gsk_..."
     ```
     or `MISTRAL_API_KEY = "..."`. The app copies these into environment
     variables at start-up (see the top of `app.py`).
6. Click **Save**, then **Deploy**. The first build installs
   `requirements.txt` and takes a few minutes.
7. Check the app:
   - Home page: click **Port of Rotterdam closed for 3 days** under the question box. You should
     see 29 late shipments, then the **Impact map** tab with arcs around the world.
   - Switch the radar to **Live news**: today's real events appear (or a short "skipped" note if
     a news source does not answer from the cloud; the rest of the app is unaffected).
   - In the sidebar, open **Network weak points** (Rotterdam first) and **Inside the graph**.
8. Copy the URL into the README (`Live demo` line at the top) and into the
   Devpost form.

## What to expect

- **First question after a cold start:** the app downloads the small
  embedding model (about 70 MB) for search by meaning, which adds a few
  seconds once. If the download fails, it prints one line in the logs and
  keeps working with full-text search only.
- **Sleeping app:** a free app that gets no traffic for a while goes to
  sleep. Open it yourself shortly before judging and before recording the
  video so it is awake.
- **Updates:** every push to `main` redeploys the app automatically.
- **Saved plans and memory** live in a writable copy of the graph on the server; they are reset
  whenever the app restarts or redeploys. The committed store itself is never modified.
- **Maps** load their background from CARTO (free, no key) and **Live news** calls GDACS and
  Google News: both need the server's internet access, which Community Cloud provides.

## If something goes wrong

- **Build fails on a package:** check the Python version in Advanced
  settings is 3.12 or 3.13 (the pinned `relate-db` wheel needs 3.9+, and
  `pandas==3.1.1` needs 3.11+).
- **"No store at .../data/ripple.relate":** the `data/` folder was not
  pushed. Run `git ls-files data | head` locally; it must list
  `data/ripple.relate/graph.json`.
- **LLM toggle missing although a key is set:** check the secret name is
  exactly `GROQ_API_KEY` or `MISTRAL_API_KEY`, then reboot the app from the
  **Manage app** menu.
