import os
import requests
import json
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Load environment variables
load_dotenv()
OPENPROJECT_URL = os.getenv("OPENPROJECT_URL")
API_TOKEN = os.getenv("OPENPROJECT_API_TOKEN")
USERNAME = os.getenv("OPENPROJECT_USERNAME")
PASSWORD = os.getenv("OPENPROJECT_PASSWORD")

# Determine authentication method
if API_TOKEN:
    # OpenProject uses "apikey" as username when using an API token
    AUTH = ('apikey', API_TOKEN)
elif USERNAME and PASSWORD:
    AUTH = (USERNAME, PASSWORD)
else:
    raise ValueError("No authentication credentials found in .env (need either Username/Password or API Token)")

app = FastAPI()

# Request models for the API
class AgentRequest(BaseModel):
    prompt: str

class ConfirmDeleteRequest(BaseModel):
    task_ids: list[int]

class ConfirmCreateRequest(BaseModel):
    payloads: list[dict]

def fetch_projects():
    url = f"{OPENPROJECT_URL}/api/v3/projects"
    response = requests.get(url, auth=AUTH)
    response.raise_for_status()
    data = response.json()
    projects = []
    if '_embedded' in data and 'elements' in data['_embedded']:
        for p in data['_embedded']['elements']:
            projects.append({'id': p['id'], 'name': p['name']})
    return projects

def fetch_project_versions(project_id):
    url = f"{OPENPROJECT_URL}/api/v3/projects/{project_id}/versions"
    response = requests.get(url, auth=AUTH)
    if response.status_code != 200:
        return []
    data = response.json()
    versions = []
    if '_embedded' in data and 'elements' in data['_embedded']:
        for v in data['_embedded']['elements']:
            versions.append({'id': v['id'], 'name': v['name']})
    return versions

def fetch_types():
    url = f"{OPENPROJECT_URL}/api/v3/types"
    response = requests.get(url, auth=AUTH)
    if response.status_code != 200:
        return []
    data = response.json()
    types = []
    if '_embedded' in data and 'elements' in data['_embedded']:
        for t in data['_embedded']['elements']:
            types.append({'id': t['id'], 'name': t['name']})
    return types

def fetch_statuses():
    url = f"{OPENPROJECT_URL}/api/v3/statuses"
    response = requests.get(url, auth=AUTH)
    if response.status_code != 200:
        return []
    data = response.json()
    statuses = []
    if '_embedded' in data and 'elements' in data['_embedded']:
        for s in data['_embedded']['elements']:
            statuses.append({'id': s['id'], 'name': s['name']})
    return statuses

def fetch_work_packages(project_id=None, filters_json=None):
    params = ["pageSize=200"]
    if filters_json:
        import urllib.parse
        params.append(f"filters={urllib.parse.quote(filters_json)}")
    
    query_string = "&".join(params)
    
    if project_id:
        url = f"{OPENPROJECT_URL}/api/v3/projects/{project_id}/work_packages?{query_string}"
    else:
        url = f"{OPENPROJECT_URL}/api/v3/work_packages?{query_string}"
    response = requests.get(url, auth=AUTH)
    if response.status_code != 200:
        return []
    data = response.json()
    tasks = []
    if '_embedded' in data and 'elements' in data['_embedded']:
        for t in data['_embedded']['elements']:
            project_href = t.get('_links', {}).get('project', {}).get('href', '')
            project_title = t.get('_links', {}).get('project', {}).get('title', '')
            project_id_val = int(project_href.split('/')[-1]) if project_href else None
            tasks.append({
                'id': t['id'],
                'subject': t['subject'],
                'project_id': project_id_val,
                'project_name': project_title
            })
    return tasks

def find_task_by_title(title, tasks, project_ids=None):
    """Find the best matching task, optionally scoped to specific project IDs."""
    # Filter to only tasks in the specified projects first
    search_pool = tasks
    if project_ids:
        filtered = [t for t in tasks if t.get('project_id') in project_ids]
        if filtered:  # Only restrict if we actually found tasks in that project
            search_pool = filtered
    
    title_lower = title.lower().strip()
    
    # Exact match first
    for t in search_pool:
        if t['subject'].lower().strip() == title_lower:
            return t
    
    # Partial match: score by common words
    best_match = None
    best_score = 0
    for t in search_pool:
        subject_lower = t['subject'].lower()
        title_words = set(title_lower.split())
        subject_words = set(subject_lower.split())
        common = len(title_words & subject_words)
        if common > best_score and common >= 2:
            best_score = common
            best_match = t
    return best_match

def parse_input_with_ollama(prompt, projects):
    """Phase 1: Ask LLM only to classify intent and extract task details/titles.
    The LLM does NOT need to know task IDs - Python resolves those later."""
    llm = ChatOllama(model="qwen3.5:35b", base_url="http://192.168.112.2:11434", temperature=0)
    
    projects_str = ", ".join([f"{p['name']} (ID: {p['id']})" for p in projects])
    
    system_prompt = f"""You are an API command extractor. Extract structured commands from the user's message.
Available projects: {projects_str}

Return a JSON array. Each object must have:
- "action": one of "create", "delete", "find", "update", "comment", "search"
- For "search": used when asking to find or list multiple tasks. Fields: "query_text" (free text to search), "status" ("open" or "closed"), "version_name" (e.g., "Sprint 1"), "project_name" (if mentioned)
- For "delete" or "find": "task_title" and optionally "project_name". ("find" is for finding a SINGLE specific task by its title/name)
- For "comment": "task_title", optionally "project_name", and "comment" (the text to add as an activity/note)
- For "create": "subject", "description", "project_id", "type_name" (e.g., "Task", "User story", "Epic", "Bug"), "priority_id" (7=Low, 8=Normal, 9=High), and optionally "version_name" (e.g., "Sprint 1") and "parent_task_title"
- For "update": "task_title", "project_name" if mentioned, and the fields to update (subject, description, version_name, parent_task_title, or status)

IMPORTANT: If the user says "add activity", "log activity", "update activity", "add note", or "add comment" on a task, use action="comment" with the "comment" field.
Only use action="update" when the user explicitly wants to change the task's title or description field.

Do NOT invent task IDs. Use "task_title" for delete/find/update/comment.
Only return the JSON array, no other text.

Examples:
User: "in FLA project update the activity on task FLA Extraction saying we finished section 1"
Output: [{{"action": "comment", "task_title": "FLA Extraction – Section 1", "project_name": "FLA", "comment": "We have completed the section 1 data extraction"}}]

User: "Find all open bugs in Sprint 1 for FLA"
Output: [{{"action": "search", "project_name": "FLA", "status": "open", "version_name": "Sprint 1"}}]

User: "Find tasks containing login"
Output: [{{"action": "search", "query_text": "login"}}]

User: "in Akshayam project in FLA sub project delete task: Fix login bug"
Output: [{{"action": "delete", "task_title": "Fix login bug", "project_name": "FLA"}}]

User: "create a bug in project 19 to fix the header"
Output: [{{"action": "create", "subject": "Fix the header", "description": "Fix the header styling", "project_id": 19, "type_name": "Bug", "priority_id": 8}}]

User: "create a child under MedValidator Module called test task"
Output: [{{"action": "create", "subject": "test task", "description": "", "project_id": 1, "type_name": "Task", "priority_id": 8, "parent_task_title": "MedValidator Module"}}]

User: "move task 'Fix header' under parent 'Frontend Epic'"
Output: [{{"action": "update", "task_title": "Fix header", "parent_task_title": "Frontend Epic"}}]
"""
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt)
    ]
    
    response = llm.invoke(messages)
    
    import re
    try:
        content = response.content.strip()
        match = re.search(r'```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```', content, re.DOTALL)
        if match:
            json_str = match.group(1)
            if json_str.strip().startswith('{'):
                json_str = f"[{json_str}]"
        else:
            start_array = content.find('[')
            end_array = content.rfind(']')
            start_obj = content.find('{')
            end_obj = content.rfind('}')
            
            if start_array != -1 and end_array != -1 and (start_obj == -1 or start_array < start_obj):
                json_str = content[start_array:end_array+1]
            elif start_obj != -1 and end_obj != -1:
                json_str = content[start_obj:end_obj+1]
                if not json_str.startswith('['):
                    json_str = f"[{json_str}]"
            else:
                json_str = content
                
        parsed_data = json.loads(json_str)
        if isinstance(parsed_data, dict):
            return [parsed_data]
        return parsed_data
    except json.JSONDecodeError:
        raise ValueError(f"Failed to parse LLM response as JSON. Output was: {response.content}")

@app.post("/api/agent")
async def process_agent_request(req: AgentRequest):
    try:
        projects = fetch_projects()
        if not projects:
            raise HTTPException(status_code=500, detail="Could not fetch projects from OpenProject.")
            
        # Phase 1: LLM extracts intent and task titles (no IDs needed)
        task_data_list = parse_input_with_ollama(req.prompt, projects)
        print(f"\n--- LLM OUTPUT ---\n{json.dumps(task_data_list, indent=2)}\n------------------\n")
        
        # Phase 2: Python resolves task_titles to IDs using fuzzy matching
        # Fetching all work packages is now deferred so we don't do it unnecessarily if there are only search requests
        all_tasks = None
        
        resolved_tasks = []
        for t in task_data_list:
            action = t.get("action", "").lower()
            if action in ("delete", "find", "update", "comment") and "task_title" in t and "task_id" not in t:
                if all_tasks is None:
                    all_tasks = fetch_work_packages()
                # Resolve project scope: match project name hint against the projects list
                project_name_hint = t.get("project_name", "").lower().strip()
                search_tasks = all_tasks
                
                if project_name_hint:
                    # Find matching project from the projects list (case-insensitive)
                    matched_project = next(
                        (p for p in projects if project_name_hint in p['name'].lower()),
                        None
                    )
                    if matched_project:
                        print(f"Fetching tasks specifically from project: {matched_project['name']} (ID: {matched_project['id']})")
                        # Fetch tasks directly from that project for more complete results
                        project_tasks = fetch_work_packages(project_id=matched_project['id'])
                        if project_tasks:
                            search_tasks = project_tasks
                        else:
                            # Fall back to filtering all_tasks by project_id
                            filtered = [t2 for t2 in all_tasks if t2.get('project_id') == matched_project['id']]
                            if filtered:
                                search_tasks = filtered
                    else:
                        print(f"Warning: No project found matching '{project_name_hint}'")
                
                matched = find_task_by_title(t["task_title"], search_tasks)
                if matched:
                    t["task_id"] = matched["id"]
                    t["subject"] = matched["subject"]
                    t["resolved_project"] = matched.get("project_name", "")
                else:
                    t["_resolve_error"] = f"Could not find any task matching '{t['task_title']}'{(' in project \'' + project_name_hint + '\'' if project_name_hint else '')}"
            
            # Resolve parent task if requested
            if "parent_task_title" in t and "parent_task_id" not in t:
                if all_tasks is None:
                    all_tasks = fetch_work_packages()
                matched_parent = find_task_by_title(t["parent_task_title"], all_tasks)
                if matched_parent:
                    t["parent_task_id"] = matched_parent["id"]
                else:
                    t["_resolve_error"] = f"Could not find parent task '{t['parent_task_title']}'"

            resolved_tasks.append(t)
        
        print(f"\n--- RESOLVED TASKS ---\n{json.dumps(resolved_tasks, indent=2)}\n----------------------\n")
        
        created_tasks = []
        failed_tasks = []
        for task_data in resolved_tasks:
            action = task_data.get("action", "create").lower()
            task_id = task_data.get("task_id")
            subject = task_data.get("subject", f"Task #{task_id}" if task_id else "Unknown Task")
            
            # If Python couldn't find the task by title, report the error
            if "_resolve_error" in task_data:
                failed_tasks.append({"subject": task_data.get("task_title", "Unknown"), "error": task_data["_resolve_error"]})
                continue
            
            headers = {"Content-Type": "application/json"}
            
            if action == "delete":
                if not task_id:
                    failed_tasks.append({"subject": subject, "error": "Missing task_id for deletion."})
                    continue
                # Stage the task for confirmation preview instead of immediately deleting
                created_tasks.append({
                    "action": "pending_delete",
                    "id": task_id,
                    "subject": subject,
                    "url": f"{OPENPROJECT_URL}/work_packages/{task_id}"
                })
                    
            elif action == "search":
                # Construct filter JSON
                filters_list = []
                # 1. Text filter
                q_text = task_data.get("query_text")
                if q_text:
                    filters_list.append({"subjectOrId": {"operator": "**", "values": [q_text]}})
                
                # 2. Status filter
                status_str = task_data.get("status", "").lower()
                if status_str in ("open", "closed"):
                    op = "o" if status_str == "open" else "c"
                    filters_list.append({"status": {"operator": op, "values": []}})
                
                # 3. Version filter & Project Resolution
                project_id = None
                proj_hint = task_data.get("project_name")
                if proj_hint:
                    matched_proj = next((p for p in projects if proj_hint.lower() in p['name'].lower()), None)
                    if matched_proj:
                        project_id = matched_proj['id']
                
                version_str = task_data.get("version_name")
                if version_str and project_id:
                    proj_versions = fetch_project_versions(project_id)
                    matched_ver = next((v for v in proj_versions if version_str.lower() in v['name'].lower()), None)
                    if matched_ver:
                        filters_list.append({"version": {"operator": "=", "values": [str(matched_ver['id'])]}})
                    else:
                        failed_tasks.append({"subject": "Search", "error": f"Could not find version '{version_str}' in project '{matched_proj['name']}'"})
                        continue
                
                filters_json = json.dumps(filters_list) if filters_list else None
                search_results = fetch_work_packages(project_id=project_id, filters_json=filters_json)
                
                for res in search_results:
                    created_tasks.append({
                        "action": "search",
                        "id": res['id'],
                        "subject": res['subject'],
                        "url": f"{OPENPROJECT_URL}/work_packages/{res['id']}",
                        "details": {
                            "project": res.get('project_name', '')
                        }
                    })

            elif action == "find":
                if not task_id:
                    failed_tasks.append({"subject": subject, "error": "Missing task_id for lookup."})
                    continue
                url = f"{OPENPROJECT_URL}/api/v3/work_packages/{task_id}"
                response = requests.get(url, auth=AUTH)
                if response.status_code == 200:
                    t_data = response.json()
                    
                    project_title = t_data.get('_links', {}).get('project', {}).get('title', '')
                    status_title = t_data.get('_links', {}).get('status', {}).get('title', '')
                    version_title = t_data.get('_links', {}).get('version', {}).get('title', '')
                    
                    created_tasks.append({
                        "action": "find",
                        "id": t_data['id'],
                        "subject": t_data['subject'],
                        "url": f"{OPENPROJECT_URL}/work_packages/{t_data['id']}",
                        "details": {
                            "project": project_title,
                            "status": status_title,
                            "version": version_title
                        }
                    })
                else:
                    try: error_msg = response.json().get("message", response.text)
                    except: error_msg = response.text
                    failed_tasks.append({"subject": subject, "error": f"Task #{task_id} lookup failed: {error_msg}"})
                    
            elif action == "comment":
                if not task_id:
                    failed_tasks.append({"subject": subject, "error": "Missing task_id for comment."})
                    continue
                comment_text = task_data.get("comment", "")
                if not comment_text:
                    failed_tasks.append({"subject": subject, "error": "No comment text provided."})
                    continue
                url = f"{OPENPROJECT_URL}/api/v3/work_packages/{task_id}/activities"
                payload = {"comment": {"format": "markdown", "raw": comment_text}}
                response = requests.post(url, json=payload, headers=headers, auth=AUTH)
                if response.status_code in (200, 201):
                    created_tasks.append({
                        "action": "comment",
                        "id": task_id,
                        "subject": subject,
                        "url": f"{OPENPROJECT_URL}/work_packages/{task_id}"
                    })
                else:
                    try: error_msg = response.json().get("message", response.text)
                    except: error_msg = response.text
                    failed_tasks.append({"subject": subject, "error": error_msg})

            elif action == "update":
                if not task_id:
                    failed_tasks.append({"subject": subject, "error": "Missing task_id for update."})
                    continue
                # Must GET first to obtain lockVersion
                get_url = f"{OPENPROJECT_URL}/api/v3/work_packages/{task_id}"
                get_resp = requests.get(get_url, auth=AUTH)
                if get_resp.status_code != 200:
                    failed_tasks.append({"subject": subject, "error": "Could not fetch work package for update."})
                    continue
                lock_version = get_resp.json().get("lockVersion", 0)
                
                payload = {"lockVersion": lock_version}
                if "subject" in task_data and task_data["subject"] != subject:
                    payload["subject"] = task_data["subject"]
                if "description" in task_data:
                    payload["description"] = {"format": "markdown", "raw": task_data["description"]}
                    
                version_str = task_data.get("version_name")
                if version_str:
                    # To update version, we need project_id. Try to get it from the get_resp
                    project_href = get_resp.json().get("_links", {}).get("project", {}).get("href", "")
                    if project_href:
                        project_id = project_href.split("/")[-1]
                        proj_versions = fetch_project_versions(project_id)
                        matched_ver = next((v for v in proj_versions if version_str.lower() in v['name'].lower()), None)
                        if matched_ver:
                            if "_links" not in payload: payload["_links"] = {}
                            payload["_links"]["version"] = {"href": f"/api/v3/versions/{matched_ver['id']}"}
                            
                if "parent_task_id" in task_data:
                    if "_links" not in payload: payload["_links"] = {}
                    payload["_links"]["parent"] = {"href": f"/api/v3/work_packages/{task_data['parent_task_id']}"}
                
                status_str = task_data.get("status")
                if status_str:
                    all_statuses = fetch_statuses()
                    matched_status = next((s for s in all_statuses if status_str.lower() in s['name'].lower()), None)
                    if matched_status:
                        if "_links" not in payload: payload["_links"] = {}
                        payload["_links"]["status"] = {"href": f"/api/v3/statuses/{matched_status['id']}"}
                    else:
                        failed_tasks.append({"subject": subject, "error": f"Could not find status '{status_str}'"})
                        continue
                
                url = f"{OPENPROJECT_URL}/api/v3/work_packages/{task_id}"
                response = requests.patch(url, json=payload, headers=headers, auth=AUTH)
                if response.status_code == 200:
                    updated_task = response.json()
                    created_tasks.append({
                        "action": "update",
                        "id": updated_task['id'],
                        "subject": updated_task['subject'],
                        "url": f"{OPENPROJECT_URL}/work_packages/{updated_task['id']}"
                    })
                else:
                    try: error_msg = response.json().get("message", response.text)
                    except: error_msg = response.text
                    failed_tasks.append({"subject": subject, "error": error_msg})
                    
            elif action == "create":
                project_id = task_data.get('project_id', 1)
                url = f"{OPENPROJECT_URL}/api/v3/work_packages"
                
                # Resolve type name to type ID
                type_id = 1 # Default to Task
                type_name_str = task_data.get("type_name")
                if type_name_str:
                    all_types = fetch_types()
                    matched_type = next((t for t in all_types if type_name_str.lower() in t['name'].lower()), None)
                    if matched_type:
                        type_id = matched_type['id']
                
                payload = {
                    "subject": task_data.get("subject", "Untitled"),
                    "description": {
                        "format": "markdown",
                        "raw": task_data.get("description", "")
                    },
                    "_links": {
                        "project": {"href": f"/api/v3/projects/{project_id}"},
                        "type": {"href": f"/api/v3/types/{type_id}"},
                        "priority": {"href": f"/api/v3/priorities/{task_data.get('priority_id', 8)}"}
                    }
                }
                
                version_str = task_data.get("version_name")
                if version_str:
                    proj_versions = fetch_project_versions(project_id)
                    matched_ver = next((v for v in proj_versions if version_str.lower() in v['name'].lower()), None)
                    if matched_ver:
                        payload["_links"]["version"] = {"href": f"/api/v3/versions/{matched_ver['id']}"}
                
                if "parent_task_id" in task_data:
                    payload["_links"]["parent"] = {"href": f"/api/v3/work_packages/{task_data['parent_task_id']}"}
                
                # Stage task for creation confirmation instead of immediately creating it
                created_tasks.append({
                    "action": "pending_create",
                    "subject": task_data.get("subject", "Untitled"),
                    "description": task_data.get("description", ""),
                    "project_id": project_id,
                    "version_str": version_str,
                    "parent_title": task_data.get("parent_task_title", ""),
                    "payload": payload
                })
            else:
                failed_tasks.append({"subject": subject, "error": f"Unrecognized action '{action}'. No task was created."})
                
        # If all tasks are pending_delete, return a confirmation request
        all_pending_delete = created_tasks and all(t["action"] == "pending_delete" for t in created_tasks)
        if all_pending_delete:
            return {
                "status": "pending_delete",
                "tasks": created_tasks,
                "failed": failed_tasks
            }
            
        # If all tasks are pending_create, return a confirmation request
        all_pending_create = created_tasks and all(t["action"] == "pending_create" for t in created_tasks)
        if all_pending_create:
            return {
                "status": "pending_create",
                "tasks": created_tasks,
                "failed": failed_tasks
            }
        
        return {
            "status": "success",
            "tasks": created_tasks,
            "failed": failed_tasks
        }
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/confirm-delete")
async def confirm_delete(req: ConfirmDeleteRequest):
    """Execute actual deletion after user confirmation."""
    try:
        deleted = []
        failed = []
        for task_id in req.task_ids:
            url = f"{OPENPROJECT_URL}/api/v3/work_packages/{task_id}"
            response = requests.delete(url, auth=AUTH)
            if response.status_code == 204:
                deleted.append({"action": "delete", "id": task_id, "subject": f"Task #{task_id}", "url": None})
            else:
                try: error_msg = response.json().get("message", response.text)
                except: error_msg = response.text
                failed.append({"subject": f"Task #{task_id}", "error": error_msg})
        return {"status": "success", "tasks": deleted, "failed": failed}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/confirm-create")
async def confirm_create(req: ConfirmCreateRequest):
    """Execute actual creation after user confirmation."""
    try:
        created = []
        failed = []
        headers = {"Content-Type": "application/json"}
        url = f"{OPENPROJECT_URL}/api/v3/work_packages"
        
        for payload in req.payloads:
            subject = payload.get("subject", "Untitled")
            response = requests.post(url, json=payload, headers=headers, auth=AUTH)
            if response.status_code == 201:
                created_task = response.json()
                project_id = created_task.get("_links", {}).get("project", {}).get("href", "").split("/")[-1]
                created.append({
                    "action": "create",
                    "id": created_task['id'],
                    "subject": created_task['subject'],
                    "url": f"{OPENPROJECT_URL}/projects/{project_id}/work_packages/{created_task['id']}"
                })
            else:
                try: error_msg = response.json().get("message", response.text)
                except: error_msg = response.text
                failed.append({"subject": subject, "error": error_msg})
                
        return {"status": "success", "tasks": created, "failed": failed}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files to serve the frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))

if __name__ == "__main__":
    import uvicorn
    # Use port 3000 and run with HTTPS
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True, ssl_keyfile="key.pem", ssl_certfile="cert.pem")
