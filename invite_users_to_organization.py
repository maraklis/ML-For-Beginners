#!/usr/bin/env python3
import csv
import requests
import getpass

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

# --- Invite users from CSV ---
def invite_users(csv_path, organization_id, jwt_token):
    url = f"https://studio.edgeimpulse.com/v1/api/organizations/{organization_id}/members/invite"
    with open(csv_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            email = row.get('email')
            role = row.get('role', 'member')
            datasets = row.get('datasets', '').split(';') if row.get('datasets') else []
            payload = {
                "email": email,
                "role": role,
                "datasets": datasets
            }
            headers = {
                "x-jwt-token": jwt_token,
                "Content-Type": "application/json"
            }
            response = requests.post(url, json=payload, headers=headers)
            print(f"Inviting {email} as {role}: {response.status_code}")
            print(response.json())

if __name__ == "__main__":
    print("Edge Impulse Organization Bulk Inviter")
    username = input('Enter your Edge Impulse Studio username: ')
    password = getpass.getpass(prompt='Enter your Studio password: ')
    jwt_token = studio_login(username, password)
    csv_path = input('Enter path to CSV file (with columns: email,[role,datasets]): ')
    organization_id = input('Enter organization ID (can be found in the URL for your organization https://studio.edgeimpulse.com/organization/[ORG_ID]): ')
    invite_users(csv_path, organization_id, jwt_token)
