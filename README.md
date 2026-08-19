# 🤖 OpenProject AI Agent

An AI-powered natural language agent for [OpenProject](https://www.openproject.org/) that lets you manage work packages, projects, and tasks using plain English — no manual UI clicks required.

Built with **FastAPI**, **LangChain**, and **Ollama** (local LLM), with a clean browser-based chat interface.

---

## ✨ Features

- 🗣️ **Natural language interface** — describe what you want in plain English
- 📋 **Create** work packages across any project
- 🗑️ **Delete** tasks by title with confirmation
- 🔍 **Search & filter** tasks by status, sprint/version, or project
- ✏️ **Update** task fields (status, assignee, etc.)
- 💬 **Add comments** to existing work packages
- 🔒 Supports both **API token** and **username/password** authentication
- 🌐 Simple **web UI** served directly from FastAPI

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Backend | [FastAPI](https://fastapi.tiangolo.com/) + Python |
| AI / LLM | [LangChain](https://www.langchain.com/) + [Ollama](https://ollama.com/) (local) |
| Frontend | Vanilla HTML / CSS / JavaScript |
| Project Management API | [OpenProject REST API v3](https://www.openproject.org/docs/api/) |

---

## 🚀 Getting Started

### 1. Prerequisites

- Python 3.10+
- A running [OpenProject](https://www.openproject.org/) instance
- [Ollama](https://ollama.com/) running locally or on a reachable server with a model pulled (e.g. `qwen3.5:35b`)

### 2. Clone the repo

```bash
git clone https://github.com/vidit-arca/AI.git
cd AI
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
# Your OpenProject instance URL (no trailing slash)
OPENPROJECT_URL=https://your-openproject-instance.com

# Authentication — use either API token OR username/password
OPENPROJECT_API_TOKEN=your_api_token_here

# OR
OPENPROJECT_USERNAME=your_username
OPENPROJECT_PASSWORD=your_password
```

> **Note:** API token is recommended over username/password.
> Generate one in OpenProject → *My Account → Access Tokens*.

### 5. Run the server

```bash
uvicorn main:app --reload
```

Open your browser at **http://localhost:8000** to start chatting with the agent.

---

## 💬 Example Prompts

```
Create a task "Fix login bug" in the Backend project
Delete the task "Update documentation" from Sprint 2
Find all open tasks in the Frontend project
Show me all closed tasks in Sprint 3
Add a comment "Reviewed and approved" to the task "Code review"
Update the status of "Fix login bug" to In Progress
```

---

## 📁 Project Structure

```
openproject_agent/
├── main.py              # FastAPI app + LangChain agent logic
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (not committed)
├── .gitignore
└── static/
    ├── index.html       # Chat UI
    ├── script.js        # Frontend logic
    └── style.css        # Styling
```

---

## 🔐 Security Notes

- `.env`, `*.pem`, and `*.key` files are excluded from version control via `.gitignore`
- Never commit credentials or TLS certificates to the repository

---

## 📄 License

This project is open source. Feel free to fork and adapt it for your own OpenProject setup.
