# Ghost Data Deletion Audit

This project audits account deletion requests against the supplied identities, identity history, system activity, deletion policy, evidence manifest, and evidence files. The full-dataset CSV generator is a deterministic Python audit pipeline; the separate per-case investigation and chat API can use Groq when configured. The generated challenge output is written to root `output.csv`.

## Run the application

Requirements: Python 3.10+, Node.js, and npm.

```bash
python3 -m pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
python3 code/server.py
```

Open `http://localhost:8001`. For frontend development, run `npm run dev` from `frontend/`; Vite serves the UI at `http://localhost:5173` and connects to the API at `http://localhost:8001` by default. Port 8001 avoids collisions with older local services that may already use port 8000.

The interface contains only:

- An overview of the supplied CSV files, their row counts, columns, evidence count, and output validation.
- Deletion request rows with case details from identity history, system activity, matched evidence, and the output CSV.
- A paginated viewer for every CSV under `dataset/`.
- The evidence manifest with extracted text and a link to each original file.
- A paginated root `output.csv` viewer, structural validation, CSV download, and generation action.

There are no example metrics or UI mock-data fallbacks. The dashboard refreshes from the local API and files. Case answers use the evidence available by that case's `audit_at` cutoff.

## API connection

The frontend uses `VITE_API_BASE` when set. Otherwise, it uses `http://localhost:8001` in Vite development and the current origin in the built app. If an API request fails, the interface shows the failing URL and server error. You can enter a replacement API base URL in the error panel and reconnect. To configure a different model provider, supply its API integration and credentials through the backend environment; credentials are never displayed in the interface.

## Generate the challenge output

```bash
python3 code/main.py
```

The output must use the columns `case_id,deletion_status,steps_json`. Generation stops at contract validation errors. The validator checks row coverage and order, step schema and numbering, allowed operations and states, phase ordering, and evidence references. Passing these checks confirms the output contract; it does not prove every audit decision is correct.

## Evaluate changes

```bash
python3 -m unittest evaluation.test_custom_cases -v
python3 code/benchmark_samples.py
```

The benchmark compares the 32 public sample requests against `dataset/sample_output.csv` and writes diagnostics to `evaluation_report.json`. The exact sequence score is currently lower than status accuracy; review this report after changing the auditor. The public sample reference is used by the evaluator only, not as input to full-dataset prediction generation.

## Development UI

Start the backend in one terminal:

```bash
python3 code/server.py
```

For Vite hot reload, start the frontend in a second terminal:

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173`. The backend API uses port `8001`.

## Source files

All CSVs and the evidence manifest/files are read from `dataset/`. `sample_output.csv` is shown as a supplied dataset reference; it is not used as the prediction source. The UI's generic CSV viewer exposes all rows and columns with pagination and search.
# ghst
# ghst
