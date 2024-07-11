import requests
from datetime import datetime
import subprocess
import os

# Configuration
GITHUB_TOKEN = 'your_github_token'
ORG_NAME = 'your_organization_name'
AUDIT_LOG = '/tmp/audit_log.txt'  # Use an absolute path to avoid any relative path issues
REPOS = []  # List to hold repository names

headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

# Function to get all repositories in the organization
def get_repositories():
    global REPOS
    url = f'https://api.github.com/orgs/{ORG_NAME}/repos?per_page=100'
    while url:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            repos = response.json()
            for repo in repos:
                REPOS.append(repo['name'])
            # Check if there's another page of results
            if 'next' in response.links:
                url = response.links['next']['url']
            else:
                url = None
        else:
            print(f'Failed to fetch repositories: {response.status_code} - {response.text}')
            break

# Function to audit changes to files in .checkmarx directory in a repository
def audit_repository(repo):
    repo_dir = f'/tmp/{repo}'
    if os.path.exists(repo_dir):
        subprocess.run(['rm', '-rf', repo_dir])
    clone_result = subprocess.run(['git', 'clone', f'https://github.com/{ORG_NAME}/{repo}.git', repo_dir])
    
    if clone_result.returncode != 0:
        print(f"Failed to clone repository {repo}")
        return
    
    os.chdir(repo_dir)
    
    # Logging the current directory for debugging
    print(f"Changed directory to {repo_dir}")

    # Check for changes in the .checkmarx directory
    result = subprocess.run(['git', 'log', '--pretty=format:%H %an %ad %s', '--date=iso', '--', '.checkmarx/'], capture_output=True, text=True)
    changes = result.stdout.strip().split('\n')
    
    if result.returncode != 0:
        print(f"Failed to get git log for repository {repo}")
        return
    
    # Logging the changes for debugging
    print(f"Found changes: {changes}")

    if changes and changes != ['']:
        try:
            with open(AUDIT_LOG, 'a') as log_file:
                log_file.write(f'Changes in {repo}:\n')
                for change in changes:
                    log_file.write(f'{change}\n')
                log_file.write('\n')
            print(f"Changes written to {AUDIT_LOG}")
        except Exception as e:
            print(f"Failed to write to log file {AUDIT_LOG}: {e}")
    else:
        print(f"No changes found in {repo} for .checkmarx directory")
    
    os.chdir('/tmp')

# Main execution
if __name__ == '__main__':
    if os.path.exists(AUDIT_LOG):
        os.remove(AUDIT_LOG)
        print(f"Existing audit log {AUDIT_LOG} removed.")

    get_repositories()
    print(f"Found {len(REPOS)} repositories: {REPOS}")

    for repo in REPOS:
        audit_repository(repo)
    
    if os.path.exists(AUDIT_LOG):
        print(f'Audit completed. Check {AUDIT_LOG} for details.')
    else:
        print(f"Audit log {AUDIT_LOG} was not created.")
