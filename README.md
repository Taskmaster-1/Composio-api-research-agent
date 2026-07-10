# Composio Take-Home — API Research Agent

An agentic research pipeline that profiles **100 SaaS apps** for AI-agent toolkit buildability. It extracts critical metadata (authentication models, self-serve credentials access, API surfaces, and existing MCP servers), fact-checks itself via an independent verification loop, and compiles the results into a polished, responsive web dashboard.

**🖥️ Live Case Study:** See the generated [index.html](file:///c:/Users/vivek/Desktop/Composio/index.html) (also deployable to GitHub Pages).

---

## 🛠️ Architecture & Workflow

```
               apps.json (100 apps)
                         │
                         ▼
   ┌───────────────────────────────────────────┐
   │                 agent.py                  │ (Google Serper Search + Web Page Scraper)
   │   Research app docs, auth details, & MCP  │
   └─────────────────────┬─────────────────────┘
                         │
                         ▼
   ┌───────────────────────────────────────────┐
   │                  llm.py                   │ (Multi-provider Fallback Chain)
   │  Extract details to structured JSON using  │
   │      Groq ──► OpenRouter ──► Gemini       │
   └─────────────────────┬─────────────────────┘
                         │
                         ▼
                 results.json (Incrementally saved after each app)
                         │
                         ▼
   ┌───────────────────────────────────────────┐
   │             verify.py --check             │ (Verification Pass 1)
   │ Re-fetch evidence URLs & verify claims    │
   └─────────────────────┬─────────────────────┘
                         │
                         ▼
   ┌───────────────────────────────────────────┐
   │              verify.py --fix              │ (Correction Loop)
   │ Re-research flagged apps using verifier   │
   │ objections in the prompt context          │
   └─────────────────────┬─────────────────────┘
                         │
                         ▼
   ┌───────────────────────────────────────────┐
   │             verify.py --check             │ (Verification Pass 2)
   │   Re-verify claims and measure accuracy   │
   └─────────────────────┬─────────────────────┘
                         │
                         ▼
   ┌───────────────────────────────────────────┐
   │               build_site.py               │ (Static Site Builder)
   │ Compiles results and stats to index.html  │
   └───────────────────────────────────────────┘
```

---

## 💡 Core Design Choices

* **Full Page Scraping (Not Just Snippets):** Search snippets often lack detail or contain stale marketing text. The agent downloads and parses the actual documentation web page text to extract deep details (e.g. distinguishing developer sandbox availability from enterprise gates).
* **Independent Fact-Checking:** The verification script (`verify.py`) runs in a separate process. It fetches the evidence URLs saved by the research agent and uses an independent LLM call to grade each claim as `supported`, `contradicted`, or `insufficient`. If the evidence URL is broken, the claim cannot be verified.
* **Provider Fallback & Rate-Limit Resilience:** To handle free-tier API rate limits, `llm.py` rotates requests through Groq, OpenRouter, and Gemini, using exponential backoff to handle HTTP `429` errors gracefully.
* **Integrity & Transparency:** Hallucinated values, entity confusion, or edge cases corrected manually by a developer are explicitly tracked and documented on the final dashboard page.

---

## 🚀 How to Run It

### 1. Installation
Install the required dependencies:
```powershell
pip install -r requirements.txt
```

### 2. Environment Variables
Create a `.env` file in the project root containing your API keys (refer to `.env.example`):
```ini
GEMINI_API_KEY=your_gemini_api_key
SERPER_API_KEY=your_serper_api_key
# Optional: Add GROQ_API_KEY and OPENROUTER_API_KEY for the fallback chain
```

### 3. Execution Pipeline

* **Run the Research Agent:**
  Resumes automatically if interrupted.
  ```powershell
  python agent.py
  ```
  *(To research/re-run a single app by ID, use: `python agent.py --only 42`)*

* **Perform Verification (Pass 1):**
  Inspects the evidence URLs and grades the claims, writing results to `verification.json`.
  ```powershell
  python verify.py --check
  ```

* **Run the Fix Loop:**
  Re-researches any claims flagged during the verification check, incorporating the verifier's objections into the prompt context to find better sources.
  ```powershell
  python verify.py --fix
  ```

* **Perform Verification (Pass 2):**
  Re-runs the checker to verify the updated results and display final accuracy metrics.
  ```powershell
  python verify.py --check
  ```

* **Compile the Dashboard:**
  Builds the final data visualizations, statistics, and tables into `index.html`.
  ```powershell
  python build_site.py
  ```

---

## 📂 Repository Layout

| File | Description |
| :--- | :--- |
| `apps.json` | Definition set of the 100 SaaS apps across 10 categories. |
| `agent.py` | Research agent orchestration loop (Google search ──► Scrape page ──► LLM Extract). |
| `llm.py` | Multi-LLM provider client supporting Groq, OpenRouter, and Gemini fallback routing. |
| `tools.py` | Web scraping and Google search integrations. |
| `verify.py` | Verification and fix loop logic (`--check` / `--fix`). |
| `build_site.py` | Computes statistics and compiles findings into the visual web dashboard. |
| `results.json` | Research agent output data with structured details and evidence URLs. |
| `verification.json` | Log of claim-level verification verdicts across passes. |
| `manual_checks.json` | Logs of manual human spot-checks showing hits and misses. |
| `requirements.txt` | Python dependencies. |
| `index.html` | The compiled visual dashboard showing the final case study. |

---

## 🌍 Deploys

The generated `index.html` is completely static and can be deployed easily to any static hosting provider. To host it via **GitHub Pages**:
1. Commit all files and push them to your repository on GitHub.
2. Under your repository settings, click **Pages**.
3. Select **Deploy from a branch** and set it to `main` (root directory).
4. Save, and your live site will be ready in under a minute!
