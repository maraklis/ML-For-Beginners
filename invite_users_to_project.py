#!/usr/bin/env python3
import csv
import requests
import getpass
import os
import json
from pathlib import Path

# This script invites existing users as collaborators on a specific Edge Impulse project.
# Implementation note / assumption:
# - The official organization invite endpoint (/v1/api/organizations/{org_id}/members/invite)
#   accepts a `projects` array in the payload to attach the invited member to one or more projects.
# - To invite an already-existing user use the `userId` field (if available). If you only have an
#   email address the script will invite by email and attach the project.
# If your Edge Impulse account/API uses a different project-level endpoint, update `invite_url` accordingly.

# --- Login and JWT token retrieval ---
def studio_login(username, password, studio_api_url="studio.edgeimpulse.com"):
    api_url = f"https://{studio_api_url}/v1/api-login"
    payload = {
        "username": username,
        "password": password,
        "uuid": "",
        "ssoType": "cli"
    }
    headers = { 'Content-Type': "application/json" }
    response = requests.post(api_url, json=payload, headers=headers)
    data = response.json()
    success = data.get("success", False)
    if not success and "ERR_TOTP_TOKEN IS REQUIRED" in data.get("error", ""):
        totp_token = getpass.getpass(prompt='Enter your TOTP (MFA) token: ')
        payload["totpToken"] = totp_token
        response = requests.post(api_url, json=payload, headers=headers)
        data = response.json()
        success = data.get("success", False)
    if not success:
        message = f'Login failed: {data.get("error", "Unknown error")}'
        raise ValueError(message)
    print("Login Successful")
    jwt_token = data["token"]
    return jwt_token


# --- Invite users from CSV to a project ---
def get_org_members(organization_id, jwt_token, studio_api_url="studio.edgeimpulse.com"):
    """
    Retrieve members (or users) from the organization API.

    Tries multiple reasonable endpoints and response shapes and returns a list of
    member dicts. Each member dict is expected to possibly contain one of: id, userId,
    email. The function is robust to several shapes returned by Edge Impulse APIs.

    Returns: list of dict
    """
    headers = {"x-jwt-token": jwt_token}

    candidate_paths = [
        f"/v1/api/organizations/{organization_id}/members",
        f"/v1/api/organizations/{organization_id}",
        f"/v1/api/organizations/{organization_id}/users",
        f"/v1/api/organizations"
    ]

    base = f"https://{studio_api_url}"
    last_err = None
    for path in candidate_paths:
        url = base + path
        try:
            resp = requests.get(url, headers=headers)
        except Exception as e:
            last_err = e
            continue

        if resp.status_code != 200:
            last_err = f"{resp.status_code}: {resp.text[:200]}"
            continue

        try:
            data = resp.json()
        except ValueError:
            # not JSON, skip
            last_err = f"non-json response from {url}"
            continue

        # Possible shapes: a list of users, or {"members": [...]}, or {"users": [...]},
        # or nested under "organization" key.
        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in ("members", "users", "data", "results"):
                if key in data and isinstance(data[key], list):
                    return data[key]

            # Some APIs return organization object with members inside
            if "organization" in data and isinstance(data["organization"], dict):
                org = data["organization"]
                for key in ("members", "users"):
                    if key in org and isinstance(org[key], list):
                        return org[key]

        # fallback: skip to next candidate
    # if we reach here, no successful parse
    raise RuntimeError(f"Could not retrieve organization members: {last_err}")


def fetch_user_email(user_id, jwt_token, organization_id=None, studio_api_url="studio.edgeimpulse.com"):
    """
    Try to retrieve an email address for a given user id from likely endpoints.
    Returns email string or None.
    """
    headers = {"x-jwt-token": jwt_token}
    base = f"https://{studio_api_url}"
    candidate_paths = []
    # common user endpoints
    candidate_paths.append(f"/v1/api/users/{user_id}")
    if organization_id:
        candidate_paths.append(f"/v1/api/organizations/{organization_id}/members/{user_id}")
        candidate_paths.append(f"/v1/api/organizations/{organization_id}/users/{user_id}")
    candidate_paths.append(f"/v1/api/users?id={user_id}")

    last_err = None
    for path in candidate_paths:
        url = base + path
        try:
            resp = requests.get(url, headers=headers)
        except Exception as e:
            last_err = e
            continue

        if resp.status_code != 200:
            last_err = f"{resp.status_code}: {resp.text[:200]}"
            continue

        try:
            data = resp.json()
        except ValueError:
            last_err = f"non-json response from {url}"
            continue

        # Try to extract email from returned shapes
        if isinstance(data, dict):
            for key in ("email", "mail", "user_email"):
                if key in data and data[key]:
                    return data[key]

            # sometimes user is nested
            for key in ("user", "data", "result"):
                if key in data and isinstance(data[key], dict):
                    for k2 in ("email", "mail"):
                        if k2 in data[key] and data[key][k2]:
                            return data[key][k2]

            # or return a list
            for key in ("users", "members", "data", "results"):
                if key in data and isinstance(data[key], list) and data[key]:
                    first = data[key][0]
                    for k2 in ("email", "mail"):
                        if k2 in first and first[k2]:
                            return first[k2]

        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                for k in ("email", "mail"):
                    if k in first and first[k]:
                        return first[k]

    # nothing found
    print(f"Could not fetch email for user {user_id}: {last_err}")
    return None


def invite_members(members, organization_id, project_id, jwt_token, studio_api_url="studio.edgeimpulse.com"):
    """
    Invite a list of member dicts to the specified project. Each member dict may
    contain 'id' / 'userId' / 'user_id' or 'email'. If role or datasets are present
    they will be used; otherwise role defaults to 'member'.
    """
    base = f"https://{studio_api_url}"
    # documented project-level add-collaborator endpoint
    project_add_url = f"https://{studio_api_url}/v1/api/{project_id}/collaborators/add"

    # organization-level invite URL (kept as last-resort fallback)
    org_invite_url = f"https://{studio_api_url}/v1/api/organizations/{organization_id}/members/invite"

    headers = {
        "x-jwt-token": jwt_token,
        "Content-Type": "application/json"
    }

    for m in members:
        # normalize
        user_id = str(m.get('id') or m.get('userId') or m.get('user_id') or '').strip()
        email = (m.get('email') or m.get('mail') or '').strip()
        role = m.get('role') or m.get('roles') or 'member'
        datasets = m.get('datasets') or []

        # API expects a 'datasets' key in the invite body. Default to empty list.
        payload = {"role": role, "projects": [str(project_id)], "datasets": []}
        if datasets:
            # if datasets is a string, split on semicolon
            if isinstance(datasets, str):
                payload['datasets'] = [d.strip() for d in datasets.split(';') if d.strip()]
            else:
                payload['datasets'] = datasets

        # Ensure the API receives an email when possible. Some Edge Impulse invite
        # endpoints require 'email' in the body even when a userId is supplied.
        if email:
            payload['email'] = email

        if user_id:
            payload['userId'] = user_id
            # If we didn't have an email, try to fetch it from likely user endpoints
            if not email:
                fetched_email = fetch_user_email(user_id, jwt_token, organization_id, studio_api_url)
                if fetched_email:
                    payload['email'] = fetched_email
                    email = fetched_email

        if 'email' not in payload:
            print("Skipping member (no email available):", m)
            continue


        # Prepare a project-specific payload per docs: it expects usernameOrEmail.
        project_payload = dict(payload)
        # project endpoint already has projectId in URL, remove projects array
        project_payload.pop('projects', None)
        # Map email/userId -> usernameOrEmail required by the project endpoint
        username_or_email = project_payload.get('email') or user_id or None
        if username_or_email:
            project_payload['usernameOrEmail'] = username_or_email
        else:
            # try to fetch email if we don't have one (should have been attempted earlier)
            fetched_email = None
            if user_id:
                fetched_email = fetch_user_email(user_id, jwt_token, organization_id, studio_api_url)
            if fetched_email:
                project_payload['usernameOrEmail'] = fetched_email
            else:
                print(f"Skipping member for project endpoint (no usernameOrEmail): {m}")
                continue

        # First try the documented project-level add collaborator endpoint
        try:
            resp = requests.post(project_add_url, json=project_payload, headers=headers)
            used_url = project_add_url
        except Exception as e:
            resp = None
            used_url = None
            print(f"Project endpoint request error for {username_or_email}: {e}")

        # If project endpoint failed or returned non-200, fallback to org invite (use original payload)
        if resp is None or resp.status_code != 200:
            try:
                resp = requests.post(org_invite_url, json=payload, headers=headers)
                used_url = org_invite_url
            except Exception as e:
                print(f"Invite request failed for {email or user_id}: {e}")
                continue

        print(f"Invited {email or user_id} to project {project_id} as {role}: {resp.status_code} (endpoint: {used_url})")
        try:
            print(resp.json())
        except ValueError:
            print(resp.text)


if __name__ == "__main__":
    print("Edge Impulse Project Collaborator Inviter (org -> project)")

    def load_secrets():
        """Load credentials from environment variables or a local secrets.json file.

        Priority:
          1) Environment variables EDGEIMPULSE_USERNAME, EDGEIMPULSE_PASSWORD,
             EDGEIMPULSE_ORG_ID, EDGEIMPULSE_PROJECT_ID
          2) Local file ./secrets.json with keys: username, password, organization_id, project_id
        Returns a dict with keys when available.
        """
        secrets = {}
        # Env vars
        if os.getenv('EDGEIMPULSE_USERNAME'):
            secrets['username'] = os.getenv('EDGEIMPULSE_USERNAME')
        if os.getenv('EDGEIMPULSE_PASSWORD'):
            secrets['password'] = os.getenv('EDGEIMPULSE_PASSWORD')
        if os.getenv('EDGEIMPULSE_ORG_ID'):
            secrets['organization_id'] = os.getenv('EDGEIMPULSE_ORG_ID')
        if os.getenv('EDGEIMPULSE_PROJECT_ID'):
            secrets['project_id'] = os.getenv('EDGEIMPULSE_PROJECT_ID')

        # Local file fallback (developer: do NOT commit real secrets)
        if not all(k in secrets for k in ('username','password','organization_id','project_id')):
            p = Path('secrets.json')
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding='utf-8'))
                    # accept both snake_case and env-like keys
                    secrets.setdefault('username', data.get('username') or data.get('EDGEIMPULSE_USERNAME'))
                    secrets.setdefault('password', data.get('password') or data.get('EDGEIMPULSE_PASSWORD'))
                    secrets.setdefault('organization_id', data.get('organization_id') or data.get('EDGEIMPULSE_ORG_ID'))
                    secrets.setdefault('project_id', data.get('project_id') or data.get('EDGEIMPULSE_PROJECT_ID'))
                    if secrets:
                        print('Loaded secrets from ./secrets.json (ensure this file is not committed)')
                except Exception as e:
                    print('Could not read ./secrets.json:', e)

        return secrets

    secrets = load_secrets()

    # use secrets when present, otherwise prompt interactively
    username = secrets.get('username') or input('Enter your Edge Impulse Studio username: ')
    if secrets.get('password'):
        password = secrets.get('password')
    else:
        password = getpass.getpass(prompt='Enter your Studio password: ')

    jwt_token = studio_login(username, password)

    organization_id = secrets.get('organization_id') or input('Enter organization ID (from URL https://studio.edgeimpulse.com/organization/[ORG_ID]): ')
    # Always prompt for project_id via terminal (do not take from secrets)
    project_id = input('Enter project ID (from URL https://studio.edgeimpulse.com/studio/[PROJECT_ID] or project dashboard): ')

    try:
        members = get_org_members(organization_id, jwt_token)
        print(f"Retrieved {len(members)} member(s) from organization {organization_id}")
        invite_members(members, organization_id, project_id, jwt_token)
    except Exception as e:
        print("Failed to retrieve or invite members:", e)
