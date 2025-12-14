# Fantasy Hoops Analyzer (Streamlit)

A local Streamlit app that connects to an ESPN Fantasy Basketball league and shows roster/matchup analysis using NBA stats.

## Run it (fresh machine)

### 1) Install Python

Install **Python 3.10+** from python.org, then confirm:

```bash
python --version
```

(If `python` doesn’t work on Mac/Linux, try `python3`.)

### 2) Set up + install deps

In the project folder:

```bash
python -m venv venv
```

Activate the virtual environment:

- **Mac/Linux**

```bash
source venv/bin/activate
```

- **Windows**

```bash
venv\Scripts\activate
```

Install dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Start the app

```bash
streamlit run app.py
```

Open the URL Streamlit prints (usually `http://localhost:8501`).

## Using your league

In the left sidebar, enter:

- **ESPN League ID** (use 512360879)
- **Season Year**

For **public leagues**, that’s enough.

For **private leagues**, also paste your cookies:

- `espn_s2`
- `SWID`

(Find these in your browser’s cookies for `espn.com`.)
