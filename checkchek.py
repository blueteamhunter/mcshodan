import requests
from datetime import datetime
import subprocess
import os

# Configuration
GITHUB_TOKEN = 'your_github_token'
ORG_NAME = 'your_organization_name'
REPOS = []  # List to hold repository names
AUDIT_LOG = 'audit_log.txt'

# Function to get all repositories in the organization
def get_repositories():
    url = f'https://api.github.com/orgs/{ORG_NAME}/repos'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        repos = response.json()
        for repo in repos:
            REPOS.append(repo['name'])
    else:
        print(f'Failed to fetch repositories: {response.status_code}')

# Function to audit changes to application.xml in a repository
def audit_repository(repo):
    repo_dir = f'/tmp/{repo}'
    if os.path.exists(repo_dir):
        subprocess.run(['rm', '-rf', repo_dir])
    subprocess.run(['git', 'clone', f'https://github.com/{ORG_NAME}/{repo}.git', repo_dir])
    os.chdir(repo_dir)
    result = subprocess.run(['git', 'log', '--pretty=format:%H %an %ad', '--date=iso', '--', '.checkmarx/application.xml'], capture_output=True, text=True)
    changes = result.stdout.strip().split('\n')
    if changes:
        with open(AUDIT_LOG, 'a') as log_file:
            log_file.write(f'Changes in {repo}:\n')
            for change in changes:
                log_file.write(f'{change}\n')
            log_file.write('\n')
    os.chdir('/tmp')

# Main execution
if __name__ == '__main__':
    get_repositories()
    for repo in REPOS:
        audit_repository(repo)
    print(f'Audit completed. Check {AUDIT_LOG} for details.')
